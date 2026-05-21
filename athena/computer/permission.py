"""Action classification + the tiered permission gate (T6-04, T6-04R).

This module is the entire safety boundary. There is no sandbox
behind it — computer use is the inverse of T5-02; the gate is
all there is. Treat the tests in
``tests/computer/test_permission.py`` as load-bearing.

T6-04R refactors the gate to route through athena's
:mod:`athena.safety.approval_guard` ContextVar approval system
instead of holding its own bespoke ``confirm`` callback. The
classifier is unchanged.

Three concepts:

  1. :func:`classify` — assign every :class:`Action` to a tier
     (``observe`` / ``input`` / ``destructive``). Conservative:
     unknown / unreadable targets default to **destructive** so
     we never auto-execute something we can't describe.

  2. :class:`PermissionGate` — given ``cfg`` (allowlist /
     denylist / mode), decide whether to allow an action. The
     decision routes through ``approval_guard.request_approval_sync``:

       observe                always passes (no approval)
       denylist                always blocks (no prompt burned)
       not in allowlist        blocks (no prompt burned)
       observe_only mode       blocks every input (no prompt)
       goal-loop active        blocks input/destructive (the
                               continuation loop runs in
                               FOREGROUND origin so we add this
                               check on top of approval_guard's
                               background-deny)
       background context      raises ApprovalDeniedInBackground
                               via approval_guard
       destructive             always prompts via approval_guard
                               with a per-action resource_id so
                               the grant cache NEVER hits — every
                               destructive action freshly confirms
       input                   prompts via approval_guard with
                               a stable resource_id so the grant
                               caches per turn / per scope

  3. ``computer_use_panic(cfg=None)`` — the kill switch. Drops
     every cached grant via ``reset_approvals(scope_fresh_approvals())``,
     sets the process-wide disable flag the gate consults at the
     top of every check, and logs at WARNING.

Nothing in this module touches the OS. Everything is pure
classification + decision logic + the ContextVar approval call.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
from typing import Any

from ..safety.approval_callback import get_approval_callback
from ..safety.approval_guard import (
    ApprovalDeniedInBackground,
    clear_grants,
    request_approval_sync,
)
from .contract import Action, Tier

logger = logging.getLogger(__name__)


# Resource-id prefixes — the keys under which the gate stores
# grants in approval_guard's ContextVar. The input tier uses a
# single stable key so once granted, the user isn't re-prompted
# on every keystroke within the same approved task. The
# destructive tier embeds a per-action discriminator so the cache
# misses every time.
_RESOURCE_INPUT = "computer_input"
_RESOURCE_DESTRUCTIVE_PREFIX = "computer_destructive::"

# Known permission_mode values. Kept for back-compat with old
# config files even though T6-04R's tier-driven approval cache
# largely replaces the per_action / per_session distinction
# (input always caches now; destructive never does). Any other
# string in cfg.computer_permission_mode is treated like
# observe_only (defensive refuse on typos).
_KNOWN_PERMISSION_MODES = frozenset({
    "observe_only",
    "per_action",
    "per_session",
})


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


# Words on a target element (or in the action's text payload)
# that mark an action destructive / irreversible. Tuned for
# false-positive bias — an extra prompt is cheap; missing a
# destructive verb is the failure mode that matters.
_DESTRUCTIVE_HINTS = re.compile(
    r"\b("
    r"delete|remove|send|submit|pay|buy|purchase|order|confirm|"
    r"overwrite|replace|discard|erase|format|wipe|sudo|trash|"
    r"reset|restart|shutdown|reboot|uninstall|drop|destroy|"
    r"clear all|sign out|log out|unlink|disable account|"
    r"don'?t save|close without saving|do not save"
    r")\b",
    re.IGNORECASE,
)


# Sensitive key combinations that should always confirm even
# when no target_desc is visible (e.g. a key action without an
# accessibility-tree element).
_DESTRUCTIVE_KEYS = frozenset(
    {
        "alt+f4",
        "cmd+q",
        "ctrl+w",
        "cmd+w",
        "ctrl+shift+w",
        "delete",
        "shift+delete",
        "cmd+delete",
        "ctrl+alt+delete",
        "f5",  # browser refresh / could discard unsaved
        # power
        "power",
    }
)


_CLICK_VERBS: frozenset[str] = frozenset(
    ("click", "double_click", "right_click", "drag")
)


def classify(action: Action) -> Tier:
    """Map ``action`` to a tier.

    Order of checks is deliberate:

      1. Non-input → ``observe`` (no further questions).
      2. Destructive hints in the target description / text →
         ``destructive`` (the hard wins).
      3. Sensitive key combination → ``destructive``.
      4. Click verbs with NO readable target → ``destructive``
         (we don't know what this button does → assume the
         worst).
      5. Otherwise → ``input``.
    """
    if not action.is_input:
        return "observe"

    haystack = _classification_text(action)
    if haystack and _DESTRUCTIVE_HINTS.search(haystack):
        return "destructive"

    if action.type == "key" and action.key:
        normalised = action.key.strip().lower().replace(" ", "")
        if normalised in _DESTRUCTIVE_KEYS:
            return "destructive"

    if action.type in _CLICK_VERBS and not action.target_desc:
        # Conservative default: a click with no readable target
        # (the a11y tree had nothing; vision couldn't label it)
        # is treated as destructive. Confirming an extra time
        # is cheap; an unconfirmed mystery click is not.
        return "destructive"

    return "input"


def _classification_text(action: Action) -> str:
    """Concatenate the bits the destructive-hint regex scans —
    target description, typed text, and (defensively) the app
    name. Returns the lowercased blob; callers regex on it."""
    parts = [
        action.target_desc or "",
        action.text or "",
        # We don't read the app name into the regex by default;
        # the allow/denylist handles app scoping. Including it
        # here is defensive when a hostile app name embeds a
        # destructive verb. But low-risk to include.
        action.app or "",
    ]
    return " ".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# Permission gate
# ---------------------------------------------------------------------------


# Process-wide panic flag. Set by computer_use_panic(); cleared
# by computer_use_unpanic() (operator-driven, after they decide
# the situation is safe again). The gate consults this at the
# top of every check — engaged → every input/destructive call
# is refused without prompting.
_panic_engaged: bool = False
_panic_lock = threading.Lock()


def panic_engaged() -> bool:
    """Read-only: is the panic kill switch currently engaged?"""
    return _panic_engaged


def _classifier_resource_id(action: Action) -> str:
    """Stable per-action id for the destructive cache key.

    SHA-256 short hash of the action description so two
    semantically distinct destructive actions get distinct
    resource_ids — the cache never accidentally bleeds a grant
    for "submit form A" into "submit form B" / "delete file"
    etc.
    """
    payload = (action.describe() or "?").encode("utf-8", errors="replace")
    return _RESOURCE_DESTRUCTIVE_PREFIX + hashlib.sha256(payload).hexdigest()[:16]


def _goal_loop_active(cfg: Any) -> bool:
    """Best-effort check: is the autonomous /goal continuation
    loop currently driving turns?

    The goal loop runs in FOREGROUND origin (T5-07 design — it
    re-uses the main agent context to inject synthetic
    continuation turns). approval_guard's background-deny alone
    wouldn't catch it, so the gate consults this directly. When
    the loop is active and cfg.computer_deny_during_goal_loop is
    True (default), input + destructive are refused.

    Defensive: any exception in the path returns False so a goal-
    module bug never auto-engages the deny. Pinned by test."""
    if not getattr(cfg, "computer_deny_during_goal_loop", True):
        return False
    try:
        from ..config import profile_dir
        from ..goal.state import load_state
        profile = getattr(cfg, "profile", None) or "default"
        state = load_state(profile_dir(profile))
        if state is None:
            return False
        return state.status == "active"
    except Exception:  # noqa: BLE001
        logger.debug("goal loop state lookup failed", exc_info=True)
        return False


class PermissionGate:
    """The single decision point for whether an action runs.

    Construction:

      cfg          athena Config (reads computer_app_allowlist /
                   computer_app_denylist / computer_permission_mode
                   / computer_deny_during_goal_loop)

    Surface:

      check(action) -> bool        the gate
      reset_session()              drop every cached input grant
                                   (loop calls this on stop)

    The gate consults :mod:`athena.safety.approval_guard` for
    every action that needs user confirmation — there is no
    bespoke confirm callback here. Prompts surface via whatever
    is bound to :func:`approval_callback.get_approval_callback`
    (interactive ``ui.confirm``, ACP ``permission_request``, etc.)
    so the IDE / chat platform / terminal all get the same UX.
    """

    def __init__(self, *, cfg: Any):
        self.cfg = cfg

    def check(self, action: Action) -> bool:
        """Return True iff ``action`` is allowed to execute."""
        tier = classify(action)
        if tier == "observe":
            return True

        # Panic kill switch — refuses everything below observe
        # tier without burning a prompt.
        if _panic_engaged:
            logger.warning(
                "computer permission: refused (panic engaged; action=%r)",
                action.describe(),
            )
            return False

        # Denylist wins over everything. No prompt, no appeal.
        if self._denylisted(action.app):
            logger.info(
                "computer permission: refused (denylisted app=%r action=%r)",
                action.app,
                action.describe(),
            )
            return False

        # Allowlist: when non-empty, the app MUST match. Empty
        # allowlist = "no app approved for control" — the safest
        # default. Control requires the user to explicitly list
        # the apps they want to delegate.
        if not self._allowlisted(action.app):
            logger.info(
                "computer permission: refused (app %r not in allowlist; "
                "action=%r)",
                action.app,
                action.describe(),
            )
            return False

        mode = getattr(self.cfg, "computer_permission_mode", "observe_only")

        # observe_only mode blocks every input regardless of
        # allowlist — no prompt burned. Unknown modes (typos in
        # the config file) get the same treatment defensively —
        # opening into an unrecognised branch would be unsafe.
        if mode == "observe_only" or mode not in _KNOWN_PERMISSION_MODES:
            logger.info(
                "computer permission: refused (mode=%r non-permissive; "
                "action=%r)",
                mode, action.describe(),
            )
            return False

        # The /goal autonomous loop runs in FOREGROUND, so
        # approval_guard wouldn't catch it. Refuse here, AFTER
        # the cheap config-driven checks but BEFORE any prompt.
        if _goal_loop_active(self.cfg):
            logger.warning(
                "computer permission: refused (goal loop active; "
                "computer_deny_during_goal_loop=True; action=%r)",
                action.describe(),
            )
            return False

        # Route through approval_guard. The resource_id picks
        # the cache policy:
        #   input         → stable "computer_input" → cached
        #                   per turn / per scope
        #   destructive   → per-action hash → cache NEVER hits,
        #                   every destructive freshly prompts
        if tier == "destructive":
            resource_id = _classifier_resource_id(action)
        else:
            resource_id = _RESOURCE_INPUT

        prompt = _build_prompt_callback(action, tier)
        try:
            allowed = request_approval_sync(resource_id, prompt)
        except ApprovalDeniedInBackground:
            logger.warning(
                "computer permission: refused (background context; action=%r)",
                action.describe(),
            )
            return False
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "computer permission: approval surface raised (%s); "
                "treating as denial",
                e,
            )
            return False

        logger.info(
            "computer permission: %s %s — %s",
            tier, action.describe(),
            "approved" if allowed else "refused",
        )
        return allowed

    def reset_session(self) -> None:
        """Drop every cached input grant. Called by the loop on
        task end so the next task re-confirms (or on panic).
        Uses ``clear_grants()`` rather than the scope token
        round-trip — the latter would IMMEDIATELY restore the
        prior cache, which is the opposite of what we want.
        """
        clear_grants()

    # ----- internals -----

    def _denylisted(self, app: str | None) -> bool:
        deny = list(getattr(self.cfg, "computer_app_denylist", []) or [])
        if not deny or not app:
            return False
        haystack = app.lower()
        return any(d.lower() in haystack for d in deny)

    def _allowlisted(self, app: str | None) -> bool:
        allow = list(getattr(self.cfg, "computer_app_allowlist", []) or [])
        if not allow:
            return False
        if not app:
            return False
        haystack = app.lower()
        return any(a.lower() in haystack for a in allow)


def _build_prompt_callback(action: Action, tier: Tier):
    """Construct the sync prompt callback approval_guard will
    invoke on a cache miss. Bridges into athena's existing
    :func:`approval_callback.get_approval_callback` so the
    prompt surface (interactive ``ui.confirm``, ACP
    ``permission_request``, gateway adapter, etc.) is the same
    one every other tool uses.

    Tool name shown to the user is ``computer_<tier>``; args
    carry the human-readable action description + app + tier
    for the UI to render.
    """
    def _prompt(_resource_id: str) -> bool:
        cb = get_approval_callback()
        tool_name = f"computer_{tier}"
        args = {
            "action": action.describe(),
            "app": action.app or "?",
            "tier": tier,
            "target_desc": action.target_desc or "",
        }
        try:
            verdict = cb(tool_name, args)
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "computer permission: approval callback raised (%s); "
                "treating as denial",
                e,
            )
            return False
        return verdict == "allow"

    return _prompt


def computer_use_panic(cfg: Any = None) -> None:
    """Engage the panic kill switch.

    Two effects:

      1. Every cached grant is dropped via
         ``reset_approvals(scope_fresh_approvals())`` — the
         input tier can't ride a stale approval after panic.

      2. The process-wide ``_panic_engaged`` flag flips True.
         The gate consults it at the top of every check; an
         engaged panic refuses every input/destructive action
         WITHOUT prompting (so a hostile UI can't dance around
         the panic by re-prompting).

    Called by:
      - the configured panic hotkey (existing ``killswitch.py``
        wiring; this just adds the grant-drop)
      - a future ``computer_panic`` tool the model can invoke
        on its own initiative
      - tests

    Disengage via :func:`computer_use_unpanic` — operator-
    driven; the gate stays disabled until they decide it's safe.
    """
    global _panic_engaged
    with _panic_lock:
        _panic_engaged = True
    try:
        clear_grants()
    except Exception:  # noqa: BLE001
        logger.debug("computer_use_panic: clear_grants failed", exc_info=True)
    logger.warning(
        "computer_use_panic engaged — input/destructive disabled, "
        "all cached approvals dropped"
    )


def computer_use_unpanic() -> None:
    """Clear the panic flag. Cached grants remain dropped
    (rebuild them via fresh approval prompts)."""
    global _panic_engaged
    with _panic_lock:
        _panic_engaged = False
    logger.info("computer_use_panic disengaged — gate accepts prompts again")

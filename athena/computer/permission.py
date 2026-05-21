"""Action classification + the permission gate (T6-04.1).

This module is the entire safety boundary. There is no sandbox
behind it — computer use is the inverse of T5-02; the gate is
all there is. Treat the tests in
``tests/computer/test_permission.py`` as load-bearing.

Three concepts:

  1. :func:`classify` — assign every :class:`Action` to a tier
     (``observe`` / ``input`` / ``destructive``). Conservative:
     unknown / unreadable targets default to **destructive** so
     we never auto-execute something we can't describe.

  2. :class:`PermissionGate` — given ``cfg`` (allowlist /
     denylist / mode) + a ``confirm`` callback, decide whether
     to allow an action. Encodes the invariants:

       observe                always passes (no input)
       denylist                always blocks (no prompt)
       not in allowlist        blocks
       observe_only mode       blocks every input
       destructive             ALWAYS confirms — every mode,
                               every session, no exception
       per_action mode         confirms each input
       per_session mode        confirms once for input;
                               destructive still confirms each
       default cfg mode        observe_only (safest)

  3. Confirm-callback contract: ``(action, tier) -> bool``. The
     gate calls it; the caller (REPL prompt / ACP UI / test
     fixture) returns True iff the user approved.

Nothing in this module touches the OS. Everything is pure
classification + decision logic so tests can run with no
backend installed.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable

from .contract import Action, Tier

logger = logging.getLogger(__name__)


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


ConfirmFn = Callable[[Action, Tier], bool]


class PermissionGate:
    """The single decision point for whether an action runs.

    Construction:

      cfg          athena Config (reads computer_app_allowlist /
                   computer_app_denylist / computer_permission_mode)
      confirm      callable invoked when a tier requires
                   confirmation. Returns True iff the user
                   approved this specific action.

    Surface:

      check(action) -> bool        the gate
      reset_session()              forget a per_session grant
                                   (loop calls this on stop)
    """

    def __init__(self, *, cfg: Any, confirm: ConfirmFn):
        self.cfg = cfg
        self.confirm = confirm
        # State that survives across check() calls within one
        # session; reset by reset_session() (e.g. on loop exit).
        # Tristate: None (not asked yet) / True (granted) /
        # False (denied — and persists through the session so
        # the user isn't re-prompted with the same question
        # over and over).
        self._session_decision: bool | None = None

    # ------------------------------------------------------------------
    # The gate
    # ------------------------------------------------------------------

    def check(self, action: Action) -> bool:
        """Return True iff ``action`` is allowed to execute."""
        tier = classify(action)
        if tier == "observe":
            return True

        # Denylist wins over everything else. No prompt, no
        # appeal — a denylisted app is never controlled.
        if self._denylisted(action.app):
            logger.info(
                "computer permission: refused (denylisted app=%r action=%r)",
                action.app,
                action.describe(),
            )
            return False

        # Allowlist: when non-empty, the app MUST match.
        # Empty allowlist means "no app is approved for control" —
        # the safest possible default. Control requires the user
        # to explicitly list the apps they want to delegate.
        if not self._allowlisted(action.app):
            logger.info(
                "computer permission: refused (app %r not in allowlist; "
                "action=%r)",
                action.app,
                action.describe(),
            )
            return False

        mode = getattr(self.cfg, "computer_permission_mode", "observe_only")

        # observe_only blocks every input regardless of allowlist.
        if mode == "observe_only":
            logger.info(
                "computer permission: refused (observe_only mode; "
                "action=%r)",
                action.describe(),
            )
            return False

        # Destructive ALWAYS confirms — every mode, every session.
        # This is the load-bearing invariant.
        if tier == "destructive":
            allowed = self._safe_confirm(action, tier)
            logger.info(
                "computer permission: destructive %s — %s",
                action.describe(),
                "approved" if allowed else "refused",
            )
            return allowed

        # tier == "input" path. Mode picks per-action vs
        # per-session behaviour.
        if mode == "per_action":
            allowed = self._safe_confirm(action, tier)
            return allowed
        if mode == "per_session":
            if self._session_decision is None:
                self._session_decision = self._safe_confirm(action, tier)
            return self._session_decision

        # Unknown mode → treat as observe_only (refuse). The
        # config validator should never let an unknown value
        # land, but defensive refusal protects against a typo.
        logger.warning(
            "computer permission: unknown mode %r — refusing (treat as observe_only)",
            mode,
        )
        return False

    def reset_session(self) -> None:
        """Forget any per-session decision. Called by the loop
        when a task ends so the next task re-confirms."""
        self._session_decision = None

    # ------------------------------------------------------------------
    # Internals — keep narrow; safety logic stays in check()
    # ------------------------------------------------------------------

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
            # No app name reported → can't match any allowlist
            # entry → refuse. Conservative.
            return False
        haystack = app.lower()
        return any(a.lower() in haystack for a in allow)

    def _safe_confirm(self, action: Action, tier: Tier) -> bool:
        """Run the confirm callback inside a defensive try/except
        — a buggy callback must not crash the gate (open-fail
        would be unsafe). Any exception → treat as denial."""
        try:
            return bool(self.confirm(action, tier))
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "computer permission: confirm callback raised (%s); "
                "treating as denial",
                e,
            )
            return False

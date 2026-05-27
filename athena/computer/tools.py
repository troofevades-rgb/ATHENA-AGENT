"""Computer-use tools (T6-04.4 observe surface + T6-04.5 input).

Observe-only tools land first:

  computer_screenshot()              capture the screen, return
                                      a base64 PNG / file ref +
                                      a hash-logged audit row
  computer_observe(question)         capture + route to a
                                      vision-capable provider
                                      ("what's on my screen
                                      right now?")

Input tools and computer_do (the observe-act loop) land in
T6-04.5 once the loop is in place.

Every tool checks ``cfg.computer_use_enabled`` first — disabled
returns a structured "not enabled" payload rather than crashing.
"""

from __future__ import annotations

import base64
import json
import logging
import tempfile
from pathlib import Path
from typing import Any

from ..tools.registry import tool
from .audit import ActionAuditLog, default_audit_path
from .contract import Action, Screenshot
from .detect import select_backend

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level cached backend + audit log
# ---------------------------------------------------------------------------


_backend: Any = None
_audit: ActionAuditLog | None = None


def _resolve_backend(cfg: Any):
    """Lazy backend resolution — picked once per process so a
    series of computer_* calls reuses the same handle."""
    global _backend
    if _backend is None:
        _backend = select_backend(cfg)
    return _backend


def _resolve_audit(cfg: Any) -> ActionAuditLog:
    global _audit
    if _audit is None:
        from ..config import profile_dir as _pd

        profile = getattr(cfg, "profile", None) or "default"
        path = default_audit_path(cfg, _pd(profile))
        _audit = ActionAuditLog(path)
    return _audit


def _reset_for_tests() -> None:
    """Test-only — clear the module cache so a test that
    monkeypatches cfg gets a freshly-resolved backend / log."""
    global _backend, _audit
    _backend = None
    _audit = None


def _load_cfg():
    """Indirection so tests can monkeypatch."""
    from ..config import load_config

    return load_config()


def _disabled_payload(reason: str) -> str:
    return json.dumps(
        {
            "available": False,
            "reason": reason,
            "backend": None,
        }
    )


# ---------------------------------------------------------------------------
# computer_screenshot
# ---------------------------------------------------------------------------


@tool(
    name="computer_screenshot",
    toolset="computer",
    description=(
        "Capture the user's screen and write the image to disk. Observe-"
        "tier action — no confirmation needed, no input performed. "
        "Returns a JSON payload with the FILE PATH (not inline bytes — "
        "a 4K screen is ~30 MB and would blow the model's context "
        "window). To describe what's on screen, use `computer_observe` "
        "instead; to act on the file, the path is on disk. Off by "
        "default (computer_use_enabled=False)."
    ),
    parameters={"type": "object", "properties": {}},
)
def computer_screenshot(**_kwargs: Any) -> str:
    cfg = _load_cfg()
    if not getattr(cfg, "computer_use_enabled", False):
        return _disabled_payload("computer_use_enabled is False")

    backend = _resolve_backend(cfg)
    if not backend.is_available():
        return json.dumps(
            {
                "available": False,
                "reason": f"backend {backend.name!r} not available on this host",
                "backend": backend.name,
            }
        )

    try:
        shot = backend.screenshot()
    except Exception as e:  # noqa: BLE001
        logger.warning("computer_screenshot: backend failed: %s", e)
        return json.dumps(
            {
                "available": False,
                "reason": f"backend error: {e}",
                "backend": backend.name,
            }
        )

    # Log the observe action.
    audit = _resolve_audit(cfg)
    audit.log(
        action=Action(type="screenshot", app=backend.active_app()),
        tier="observe",
        confirmed=None,
        executed=True,
        screenshot=shot,
        result="ok",
    )

    try:
        path = _persist_screenshot(shot, cfg=cfg)
    except OSError as e:
        logger.warning("computer_screenshot: write-to-disk failed: %s", e)
        return json.dumps(
            {
                "available": False,
                "reason": f"could not persist screenshot: {e}",
                "backend": backend.name,
            }
        )

    return json.dumps(
        {
            "available": True,
            "backend": backend.name,
            "width": shot.width,
            "height": shot.height,
            "scale": shot.scale,
            "format": "image/bmp",  # T6-04.3 ships BMP on Windows
            "path": path,
            "sha256": _sha(shot),
            "bytes": len(shot.png_bytes),
        }
    )


# ---------------------------------------------------------------------------
# computer_observe
# ---------------------------------------------------------------------------


@tool(
    name="computer_observe",
    toolset="computer",
    description=(
        "Capture the user's screen and route it to a vision-capable "
        "provider with a question. Returns the vision model's answer. "
        "Observe-tier — no input performed. Use to answer questions "
        'like "what app is on my screen?" or "describe the current '
        'window". Routes via T5-01\'s vision capability (local-preferred).'
    ),
    parameters={
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": (
                    "What to ask the vision model about the current "
                    "screen. Example: \"summarize what I'm reading\"."
                ),
            },
        },
        "required": ["question"],
    },
)
def computer_observe(question: str = "", **_kwargs: Any) -> str:
    cfg = _load_cfg()
    if not getattr(cfg, "computer_use_enabled", False):
        return _disabled_payload("computer_use_enabled is False")

    if not question or not question.strip():
        return json.dumps(
            {"available": False, "reason": "question required"}
        )

    backend = _resolve_backend(cfg)
    if not backend.is_available():
        return json.dumps(
            {
                "available": False,
                "reason": f"backend {backend.name!r} not available",
                "backend": backend.name,
            }
        )

    try:
        shot = backend.screenshot()
    except Exception as e:  # noqa: BLE001
        return json.dumps(
            {"available": False, "reason": f"screenshot failed: {e}"}
        )

    audit = _resolve_audit(cfg)
    audit.log(
        action=Action(type="screenshot", app=backend.active_app()),
        tier="observe",
        confirmed=None,
        executed=True,
        screenshot=shot,
        result="ok",
    )

    # Vision dispatch — go through MediaRegistry's
    # backend_for("vision"). The result handoff is intentionally
    # narrow: the broker resolves the backend; the actual
    # multimodal call is the agent-runtime's job (the same
    # pattern as the T5-05 differentiated MCP analyze_image
    # tool). The tool surfaces the routing decision + the
    # screenshot path; the agent runtime reads the file when
    # dispatching to the vision provider.
    from ..media import MediaRegistry

    # Persist FIRST so even the no-vision-backend branch can
    # return a path the caller can act on (open in viewer, pass
    # to a different tool, etc).
    try:
        path = _persist_screenshot(shot, cfg=cfg)
    except OSError as e:
        return json.dumps(
            {
                "available": False,
                "reason": f"could not persist screenshot: {e}",
            }
        )

    media = MediaRegistry(cfg=cfg)
    vision_cls = media.backend_for("vision")
    if vision_cls is None:
        return json.dumps(
            {
                "available": True,
                "vision_backend": None,
                "reason": (
                    "no vision backend declared in capability manifest — "
                    "screenshot captured but cannot be described"
                ),
                "screenshot_sha256": _sha(shot),
                "path": path,
                "width": shot.width,
                "height": shot.height,
                "question": question,
            }
        )

    # Tool contract says "Returns the vision model's answer" —
    # honor it by dispatching the multimodal call here instead of
    # returning the path and hoping the agent runtime picks it up
    # (it doesn't, and the model spam-retries waiting for an
    # answer that will never come). Reuse vision_analyze's
    # describe handler so capture + analysis share one code path.
    answer: str | None = None
    vision_error: str | None = None
    try:
        from ..vision.analyze import (
            _default_provider_factory,
            _handle_describe,
        )
        from ..vision.hashlog import HashLogger

        described = _handle_describe(
            Path(path),
            HashLogger(cfg=cfg),
            cfg,
            prompt=question,
            provider_factory=_default_provider_factory,
        )
        if "error" in described:
            vision_error = str(described["error"])
        else:
            answer = str(described.get("answer", "")).strip()
    except Exception as e:  # noqa: BLE001
        vision_error = f"{type(e).__name__}: {e}"

    payload: dict[str, Any] = {
        "available": True,
        "vision_backend": vision_cls.name,
        "screenshot_sha256": _sha(shot),
        "question": question,
        "width": shot.width,
        "height": shot.height,
        "path": path,
        "bytes": len(shot.png_bytes),
    }
    if answer:
        payload["answer"] = answer
    if vision_error:
        payload["vision_error"] = vision_error
        payload["note"] = (
            "screenshot captured but vision analysis failed; "
            "see vision_error. Do NOT retry computer_observe — "
            "the failure is in the vision provider, not the "
            "screenshot."
        )
    return json.dumps(payload)


def _sha(shot: Screenshot) -> str:
    from .audit import hash_screenshot

    return hash_screenshot(shot)


def _persist_screenshot(shot: Screenshot, *, cfg: Any) -> str:
    """Write the screenshot bytes to disk + return the absolute
    path. The path goes into the tool result instead of inline
    base64 — a 4K screen is ~30 MB base64 which blows local
    model context windows (the original T6-04.4 bug).

    Location: ``<profile_dir>/screenshots/<isoTs>-<sha8>.bmp``
    (or ``cfg.computer_screenshots_dir`` when set). The
    parent dir is created at 0o700 mode where the OS honours
    it — these are user screen captures, treat as sensitive.
    """
    import datetime
    import os

    from .audit import hash_screenshot

    explicit = getattr(cfg, "computer_screenshots_dir", None)
    if explicit:
        base = Path(str(explicit)).expanduser()
    else:
        from ..config import profile_dir as _pd

        profile = getattr(cfg, "profile", None) or "default"
        base = _pd(profile) / "screenshots"
    base.mkdir(parents=True, exist_ok=True)
    # Best-effort restrictive perms on POSIX; Windows ACLs
    # differ and a chmod is a no-op there.
    try:
        if os.name != "nt":
            os.chmod(base, 0o700)
    except OSError:
        pass

    sha = hash_screenshot(shot)
    ts = (
        datetime.datetime.now(datetime.timezone.utc)
        .strftime("%Y%m%dT%H%M%SZ")
    )
    target = base / f"{ts}-{sha[:8]}.bmp"
    target.write_bytes(shot.png_bytes)
    return str(target)


# ---------------------------------------------------------------------------
# T6-04.5 input tools — every one routes through the gate.
# ---------------------------------------------------------------------------


def _gate_for(cfg: Any):
    """Build a PermissionGate. T6-04R: the gate routes through
    :mod:`athena.safety.approval_guard` directly — there is no
    longer a bespoke confirm callback here. Prompts surface via
    whatever is bound to
    :func:`athena.safety.approval_callback.get_approval_callback`,
    which is the interactive ``ui.confirm`` in REPL sessions,
    the ACP ``permission_request`` in IDE sessions, and
    ``AUTO_DENY`` inside forks.
    """
    from .permission import PermissionGate

    return PermissionGate(cfg=cfg)


def _single_action_path(action: Action) -> str:
    """Common preamble for the one-shot input tools: enable
    check → backend resolve → screenshot for context →
    classify → gate → perform → audit.

    The single-action tools are mostly for testing + scripted
    use; the real path is computer_do which runs the loop. We
    still expose them — the gate semantics are identical."""
    cfg = _load_cfg()
    if not getattr(cfg, "computer_use_enabled", False):
        return _disabled_payload("computer_use_enabled is False")

    backend = _resolve_backend(cfg)
    if not backend.is_available():
        return json.dumps(
            {
                "available": False,
                "reason": f"backend {backend.name!r} not available",
                "backend": backend.name,
            }
        )

    audit = _resolve_audit(cfg)
    shot = None
    try:
        if "screenshot" in backend.supports():
            shot = backend.screenshot()
    except Exception:  # noqa: BLE001
        shot = None
    if action.app is None:
        try:
            action.app = backend.active_app()
        except Exception:  # noqa: BLE001
            action.app = None

    from .permission import classify

    gate = _gate_for(cfg)
    tier = classify(action)
    allowed = gate.check(action)

    if not allowed:
        audit.log(
            action=action,
            tier=tier,
            confirmed=False,
            executed=False,
            screenshot=shot,
            result="denied",
        )
        return json.dumps(
            {
                "available": True,
                "performed": False,
                "tier": tier,
                "reason": "denied by permission gate",
            }
        )

    try:
        backend.perform(action)
    except Exception as e:  # noqa: BLE001
        logger.warning("computer tool: backend.perform failed: %s", e)
        audit.log(
            action=action,
            tier=tier,
            confirmed=True,
            executed=False,
            screenshot=shot,
            result=f"error: {e}",
        )
        return json.dumps(
            {
                "available": True,
                "performed": False,
                "tier": tier,
                "reason": f"perform failed: {e}",
            }
        )
    audit.log(
        action=action,
        tier=tier,
        confirmed=True,
        executed=True,
        screenshot=shot,
        result="ok",
    )
    return json.dumps(
        {
            "available": True,
            "performed": True,
            "tier": tier,
            "action": action.describe(),
        }
    )


@tool(
    name="computer_click",
    toolset="computer",
    description=(
        "Click at the given screen coordinates. The action is "
        "classified (destructive when target_desc names 'Delete' / "
        "'Send' / 'Pay' / similar; destructive when target_desc is "
        "missing — conservative default) and runs through the "
        "permission gate."
    ),
    parameters={
        "type": "object",
        "properties": {
            "x": {"type": "integer"},
            "y": {"type": "integer"},
            "target_desc": {
                "type": "string",
                "description": (
                    "What's at (x, y) — button label / role. Used by "
                    "the destructive-tier classifier; a missing "
                    "target_desc forces destructive tier."
                ),
            },
            "button": {
                "type": "string",
                "enum": ["left", "right", "double"],
            },
        },
        "required": ["x", "y"],
    },
)
def computer_click(
    x: int = 0,
    y: int = 0,
    target_desc: str | None = None,
    button: str = "left",
    **_kwargs: Any,
) -> str:
    button = (button or "left").lower()
    action_type = (
        "double_click" if button == "double"
        else "right_click" if button == "right"
        else "click"
    )
    return _single_action_path(
        Action(
            type=action_type,
            coords=(int(x), int(y)),
            target_desc=target_desc,
        )
    )


@tool(
    name="computer_type",
    toolset="computer",
    description=(
        "Type the given text into the active focus. Goes through the "
        "permission gate; text payloads containing destructive verbs "
        "(e.g. 'rm -rf /', 'sudo') are classified destructive."
    ),
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "target_desc": {"type": "string"},
        },
        "required": ["text"],
    },
)
def computer_type(
    text: str = "",
    target_desc: str | None = None,
    **_kwargs: Any,
) -> str:
    if not text:
        return json.dumps({"available": False, "reason": "text required"})
    return _single_action_path(
        Action(type="type", text=text, target_desc=target_desc)
    )


@tool(
    name="computer_key",
    toolset="computer",
    description=(
        "Press a single key or chord (e.g. 'Return', 'ctrl+c', "
        "'alt+f4'). Sensitive keys (Alt+F4, Cmd+W, Ctrl+Alt+Delete, "
        "Delete, F5) are classified destructive."
    ),
    parameters={
        "type": "object",
        "properties": {
            "key": {"type": "string"},
            "target_desc": {"type": "string"},
        },
        "required": ["key"],
    },
)
def computer_key(
    key: str = "",
    target_desc: str | None = None,
    **_kwargs: Any,
) -> str:
    if not key:
        return json.dumps({"available": False, "reason": "key required"})
    return _single_action_path(
        Action(type="key", key=key, target_desc=target_desc)
    )


@tool(
    name="computer_scroll",
    toolset="computer",
    description="Scroll the active window. direction is 'up' or 'down'.",
    parameters={
        "type": "object",
        "properties": {
            "direction": {"type": "string", "enum": ["up", "down"]},
            "target_desc": {"type": "string"},
        },
        "required": ["direction"],
    },
)
def computer_scroll(
    direction: str = "down",
    target_desc: str | None = None,
    **_kwargs: Any,
) -> str:
    return _single_action_path(
        Action(type="scroll", text=direction, target_desc=target_desc)
    )

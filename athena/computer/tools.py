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
        "Capture the user's screen and return the image. Observe-tier "
        "action — no confirmation needed, no input performed. Returns a "
        "JSON payload with the image as base64-encoded bytes plus width "
        "and height. Off by default (computer_use_enabled=False)."
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

    return json.dumps(
        {
            "available": True,
            "backend": backend.name,
            "width": shot.width,
            "height": shot.height,
            "scale": shot.scale,
            "format": "image/bmp",  # T6-04.3 ships BMP on Windows
            "image_b64": base64.b64encode(shot.png_bytes).decode("ascii"),
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
    # tool). The tool surfaces the routing decision + a small
    # base64 payload the agent can pass on to the provider.
    from ..media import MediaRegistry

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
                "question": question,
            }
        )

    return json.dumps(
        {
            "available": True,
            "vision_backend": vision_cls.name,
            "screenshot_sha256": _sha(shot),
            "question": question,
            "width": shot.width,
            "height": shot.height,
            "image_b64": base64.b64encode(shot.png_bytes).decode("ascii"),
            "note": (
                "vision backend resolved via the capability broker; "
                "the agent runtime performs the multimodal dispatch"
            ),
        }
    )


def _sha(shot: Screenshot) -> str:
    from .audit import hash_screenshot

    return hash_screenshot(shot)


# ---------------------------------------------------------------------------
# T6-04.5 input tools — every one routes through the gate.
# ---------------------------------------------------------------------------


def _gate_for(cfg: Any):
    """Build a PermissionGate with a default-deny confirm
    callback. The agent runtime overrides ``confirm`` to plug
    in the REPL / ACP confirmation UI; the bare-tool path
    defaults to refusing destructive + input prompts because
    there's no live UI to ask. The user wires a confirm
    callback via /computer mode (T6-04.6 docs)."""
    from .permission import PermissionGate

    def _no_ui_default(action: Action, tier) -> bool:
        logger.info(
            "computer tool: no confirm UI registered; refusing %s tier",
            tier,
        )
        return False

    return PermissionGate(cfg=cfg, confirm=_no_ui_default)


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

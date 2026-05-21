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

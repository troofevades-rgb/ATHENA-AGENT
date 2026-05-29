"""``video_generate`` + ``animate_image`` tools (T6-05.3).

Both tools share the same generation pipeline (T6-05.1's
:func:`run_generation`) and the same broker-resolution (T6-05.2's
:func:`resolve_backend`); only the input shape + ``GenerationRequest.mode``
differ.

The tool surface returns a JSON-formatted text payload that the
agent reads. Identical key shape across both tools so a downstream
consumer doesn't branch on which one fired:

  status         done | declined | error | timeout | cancelled |
                 rejected | not_enabled | not_configured
  path           file path on disk, when ``status == "done"``
  sha256         content hash of the output
  duration_s     requested duration in seconds
  seconds_taken  wall-clock time the generation actually took
  cost_est       backend-reported dollar estimate (may be None)
  backend        the resolved provider name
  estimate       {seconds_est, cost_est}
  frame_check    optional vision summary (T4-01 / future)
  reason         populated on rejected / not_enabled / not_configured
  error          populated on error / timeout

When ``cfg.video_generation_enabled`` is False, neither tool
contacts a backend; both return a structured "not enabled"
payload. Same opt-in invariant T6-04 enforces for computer use.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..tools.registry import tool
from .job import GenerationRequest, resolve_backend, run_generation

logger = logging.getLogger(__name__)


_DEFAULT_DURATION_S = 5.0
_DEFAULT_ASPECT = "16:9"


# ---------------------------------------------------------------------------
# Cfg + helpers
# ---------------------------------------------------------------------------


def _load_cfg():
    """Resolve the active config.

    Prefers the live agent's ``cfg`` when an agent context is set —
    this is what carries session-scoped mutations like
    ``/video set xai_video``. Falls back to a fresh ``load_config()``
    only when no agent is bound (CLI / batch / test contexts).

    Indirection here also lets tests monkeypatch a static cfg.
    """
    try:
        from ..agent.core import get_current_agent

        agent = get_current_agent()
        if agent is not None and getattr(agent, "cfg", None) is not None:
            return agent.cfg
    except Exception:  # noqa: BLE001 — never let cfg resolution crash a tool
        pass
    from ..config import load_config

    return load_config()


def _disabled_payload() -> str:
    return json.dumps(
        {
            "status": "not_enabled",
            "reason": (
                "video_generation_enabled is False — set it in athena "
                "config + ensure a provider declares the video_generation "
                "capability"
            ),
        }
    )


def _no_backend_payload() -> str:
    return json.dumps(
        {
            "status": "not_configured",
            "reason": (
                "no video-generation backend resolved — no provider "
                "declares video_generation OR the declared provider "
                "couldn't be instantiated (missing credentials?)"
            ),
        }
    )


def _rejected(reason: str) -> str:
    return json.dumps({"status": "rejected", "reason": reason})


# ---------------------------------------------------------------------------
# Tool 1: video_generate (text → video)
# ---------------------------------------------------------------------------


@tool(
    name="video_generate",
    toolset="media",
    description=(
        "Generate a video from a text prompt. Slow + may cost money; "
        "long or expensive jobs require user confirmation before "
        "submitting (cost/latency guard). The backend is resolved via "
        "the T5-05 media broker or the operator's /video set selector "
        "(local-preferred). Returns a JSON payload with the local path "
        "on success, or a structured ``status`` field on failure "
        "(``not_enabled`` / ``not_configured`` / ``declined`` / "
        "``error``). When the user asks for a video, CALL THIS TOOL — "
        "don't pre-judge whether config is right. The tool returns a "
        "structured response and you react to that. Refusing to call "
        "on the basis of \"video gen might be disabled\" wastes a turn "
        "and misinforms the operator."
    ),
    parameters={
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Text description of the video to generate.",
            },
            "duration_s": {
                "type": "number",
                "description": f"Clip duration in seconds (default {_DEFAULT_DURATION_S}).",
            },
            "aspect": {
                "type": "string",
                "description": f"Aspect ratio (default '{_DEFAULT_ASPECT}').",
            },
            "seed": {
                "type": "integer",
                "description": "Optional seed for reproducibility.",
            },
        },
        "required": ["prompt"],
    },
)
def video_generate(
    prompt: str = "",
    duration_s: float | None = None,
    aspect: str | None = None,
    seed: int | None = None,
    **_kwargs: Any,
) -> str:
    cfg = _load_cfg()
    vg = getattr(cfg, "video_generation", None)
    if vg is None or not vg.enabled:
        return _disabled_payload()

    if not prompt or not str(prompt).strip():
        return _rejected("prompt required")

    backend = resolve_backend(cfg)
    if backend is None:
        return _no_backend_payload()

    request = GenerationRequest(
        mode="text_to_video",
        prompt=str(prompt),
        duration_s=float(duration_s if duration_s is not None else _DEFAULT_DURATION_S),
        aspect=str(aspect or _DEFAULT_ASPECT),
        seed=int(seed) if seed is not None else None,
    )
    result = run_generation(request, backend=backend, cfg=cfg)
    return json.dumps(result.to_dict())


# ---------------------------------------------------------------------------
# Tool 2: animate_image (image → video)
# ---------------------------------------------------------------------------


@tool(
    name="animate_image",
    toolset="media",
    description=(
        "Animate a still image into a short video. Backend resolved "
        "via the T5-05 media broker or the operator's /video selector "
        "(local-preferred). Returns a JSON payload with the local "
        "path on success, or a structured ``status`` field on failure "
        "(``not_enabled`` / ``not_configured`` / ``declined`` / "
        "``error``). When the user asks to animate an image, CALL "
        "THIS TOOL and react to the structured response — don't "
        "refuse on the basis of guessing at config state."
    ),
    parameters={
        "type": "object",
        "properties": {
            "image_path": {
                "type": "string",
                "description": "Path to the source image file.",
            },
            "motion_prompt": {
                "type": "string",
                "description": "Text description of the motion / animation.",
            },
            "duration_s": {
                "type": "number",
                "description": "Clip duration in seconds (default 4).",
            },
        },
        "required": ["image_path", "motion_prompt"],
    },
)
def animate_image(
    image_path: str = "",
    motion_prompt: str = "",
    duration_s: float | None = None,
    **_kwargs: Any,
) -> str:
    cfg = _load_cfg()
    vg = getattr(cfg, "video_generation", None)
    if vg is None or not vg.enabled:
        return _disabled_payload()

    if not image_path or not str(image_path).strip():
        return _rejected("image_path required")
    src = Path(str(image_path)).expanduser()
    if not src.exists():
        return _rejected(f"image_path does not exist: {src}")
    if not motion_prompt or not str(motion_prompt).strip():
        return _rejected("motion_prompt required")

    backend = resolve_backend(cfg)
    if backend is None:
        return _no_backend_payload()

    request = GenerationRequest(
        mode="image_to_video",
        prompt="",
        image_path=src,
        motion_prompt=str(motion_prompt),
        duration_s=float(duration_s if duration_s is not None else 4.0),
        aspect=_DEFAULT_ASPECT,
    )
    result = run_generation(request, backend=backend, cfg=cfg)
    return json.dumps(result.to_dict())

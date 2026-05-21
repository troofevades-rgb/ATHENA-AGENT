"""Local synthetic video-generation backend (T6-05.2).

Provides a working video_generation provider declaration so:

  - the T5-05 broker has something to resolve when nobody else
    declares the capability
  - the CI / first-run smoke can exercise the full submit →
    poll → fetch → hash-log pipeline without a hosted vendor

The backend writes a tiny placeholder file (a generated MP4
header + the prompt's bytes) so a downstream consumer can
distinguish output between runs without actually rendering
video. **Not** a real generator — the docs spell this out and
``athena providers capabilities`` shows it as local-only.

Real adapters land alongside this module (one per vendor)
with the same Protocol shape; vendor specifics live entirely
in their own file.
"""

from __future__ import annotations

import dataclasses
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from .. import job as job_mod
from ...providers import register_provider
from ...providers.base import Capabilities, Provider, StreamChunk

logger = logging.getLogger(__name__)


# Minimal "video" payload — a recognisable header plus the
# prompt so distinct runs produce distinct bytes. Not a real
# MP4; the docs say so. Real adapters return real files.
_PLACEHOLDER_HEADER = (
    b"ATHENA-STUB-VIDEO-V1\n"
    b"This file is a placeholder produced by the stub_local "
    b"video-generation backend. Replace the configured backend "
    b"to get actual generated video.\n"
)


@register_provider
class StubLocalVideoBackend(Provider):
    """Local synthetic backend.

    Registers as a provider so the manifest declares
    ``video_generation``. Implements both the chat ABC (raises
    NotImplementedError — not a chat backend) AND the
    :class:`VideoGenerationBackend` protocol (the real
    surface)."""

    name: str = "stub_video_local"
    requires_api_key: bool = False

    @classmethod
    def static_capabilities(cls) -> Capabilities:
        return Capabilities(
            video_generation=True,
            is_local=True,
            tool_calls=False,
            streaming=False,
        )

    # ------------------------------------------------------------------
    # Chat ABC plumbing — not a chat backend.
    # ------------------------------------------------------------------

    def stream_chat(self, *, model, messages, tools=None, **kwargs):
        raise NotImplementedError(
            "stub_video_local is capability-only (video_generation); "
            "route via best_provider_for({'video_generation'})"
        )

    def parse_tool_calls(self, content, raw_response):
        return content, []

    # ------------------------------------------------------------------
    # VideoGenerationBackend protocol
    # ------------------------------------------------------------------

    def estimate(self, request: "job_mod.GenerationRequest") -> "job_mod.CostEstimate":
        """Treat the duration as the wall-clock estimate — a
        useful fiction for the cost-guard tests + a sane real
        number for the placeholder generation. Cost None
        (local backend; no billing dimension)."""
        return job_mod.CostEstimate(
            seconds_est=max(0.5, float(request.duration_s)),
            cost_est=None,
        )

    def submit(self, request: "job_mod.GenerationRequest") -> "job_mod.JobHandle":
        return job_mod.JobHandle(
            backend=self.name,
            job_id=f"stub-{uuid.uuid4().hex[:12]}",
            status="pending",
            extra={"request": dataclasses.asdict(request) if dataclasses.is_dataclass(request) else None},
        )

    def poll(self, handle: "job_mod.JobHandle") -> "job_mod.JobHandle":
        """Local stub completes immediately. (A real local
        renderer would advance progress over multiple polls;
        this one is a placeholder.)"""
        handle.status = "done"
        handle.progress = 1.0
        return handle

    def fetch(self, handle: "job_mod.JobHandle", *, out_dir: Path) -> Path:
        """Write a placeholder file to the outputs dir. Bytes
        include the request payload so distinct runs produce
        distinct sha256."""
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / f"{handle.job_id}.mp4"
        payload = _PLACEHOLDER_HEADER
        # Append the request blob for content-distinguishability.
        request_repr = str(handle.extra.get("request", "")).encode("utf-8", errors="replace")
        target.write_bytes(payload + request_repr)
        logger.info(
            "stub_video_local: wrote placeholder %s (%d bytes)",
            target,
            target.stat().st_size,
        )
        return target

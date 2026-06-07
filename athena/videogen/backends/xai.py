"""xAI Grok Imagine video-generation backend.

Public API (announced January 2026):

  Submit   POST https://api.x.ai/v1/videos/generations
           body: {model, prompt, duration, aspect_ratio, resolution}
           → {request_id, ...}

  Poll     GET  https://api.x.ai/v1/videos/{request_id}
           → {status: "pending"|"processing"|"done"|"failed",
              video: {url, ...}, error?, ...}

Asynchronous / deferred. The submit response only carries the
``request_id`` — the actual video URL appears later in the poll
response under ``.video.url`` once status flips to ``done``.

Authentication is a Bearer token from console.x.ai. **Not** the same
credential as the X (Twitter) bearer token used by ``search_x``;
xAI keys are issued separately at the xAI developer console.

The athena T6-05 adapter contract maps directly:

  estimate(request)        → CostEstimate
  submit(request)          → POST /v1/videos/generations → JobHandle
  poll(handle)             → GET /v1/videos/{request_id} → JobHandle
  fetch(handle, out_dir)   → download .video.url → Path
"""

from __future__ import annotations

import dataclasses
import json
import logging
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ...env import get_credential
from ...providers import register_provider
from ...providers.base import Capabilities, Provider, StreamChunk
from .. import job as job_mod

logger = logging.getLogger(__name__)


_API_BASE = "https://api.x.ai/v1"
_DEFAULT_MODEL = "grok-imagine-video"
_DEFAULT_TIMEOUT_S = 60.0


# Heuristics for the cost guard. xAI hasn't published per-second
# pricing publicly at adapter-write time, so the cost_est stays
# None and the seconds_est uses the requested duration as a lower
# bound (real wall-clock is typically 2-5× duration for cloud
# rendering — the orchestrator's confirmation threshold catches
# longer jobs either way).
def _estimate_seconds(duration_s: float) -> float:
    # Floor at 30s — the queue + render pipeline adds latency even
    # for short clips. A 2-second clip rarely returns in 2 seconds.
    return max(30.0, float(duration_s) * 4.0)


# Credential-pool provider names this backend will accept, in lookup
# order. xAI issues ONE account key for chat + video, so the key the
# user added for the xAI *chat* provider (`athena providers
# add-credential xai <key>`) works here too — we check the
# video-specific name first, then fall back to the shared "xai" entry.
_CREDENTIAL_POOL_NAMES: tuple[str, ...] = ("xai_video", "xai")


def _resolve_api_key() -> str | None:
    """Lookup priority:
    1. Secure credential pool (~/.athena/credentials.json) under
       "xai_video", then the shared "xai" entry.
    2. ATHENA_XAI_API_KEY in ~/.athena/.env or os.environ
    3. XAI_API_KEY (xAI's own canonical env var name)
    4. None — caller errors with a clear message.

    The pool is checked first because it's the more secure store
    (user-only perms, redacted display) and the canonical home for
    hosted-provider keys; the dotenv path stays as a fallback for
    older setups.
    """
    try:
        from ...providers.credential_pool import global_pool

        pool = global_pool()
        for pool_name in _CREDENTIAL_POOL_NAMES:
            cred = pool.get(pool_name)
            if cred is not None and cred.key:
                return cred.key
    except Exception:  # noqa: BLE001 — pool is best-effort; fall through to env
        pass
    return get_credential("ATHENA_XAI_API_KEY") or get_credential("XAI_API_KEY")


class XAIAPIError(RuntimeError):
    """Raised when the xAI API returns an error status or unparseable body."""


def _http(
    method: str,
    url: str,
    *,
    api_key: str,
    body: dict[str, Any] | None = None,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """Minimal JSON request → JSON response. No external deps so the
    backend can ship without adding ``httpx`` / ``requests`` to the
    base install."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "athena-xai-video/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
            text = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body_text = ""
        try:
            body_text = e.read().decode("utf-8", errors="replace")[:500]
        except Exception:  # noqa: BLE001
            pass
        raise XAIAPIError(f"xAI {method} {url} → HTTP {e.code}: {body_text or '(no body)'}") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise XAIAPIError(f"xAI {method} {url} → network: {e}") from e
    try:
        return json.loads(text) if text else {}
    except json.JSONDecodeError as e:
        raise XAIAPIError(
            f"xAI {method} {url} → non-JSON response (first 300 chars): {text[:300]}"
        ) from e


# xAI's ``resolution`` field is a quality tier, not pixel dimensions.
# Aspect ratio is carried separately in ``aspect_ratio``. Valid values
# per the API: ``480p``, ``720p``, ``1080p``. Default to 720p — keeps
# cost/time bounded; callers can override via a future ``quality``
# field on GenerationRequest (not yet wired).
_XAI_VALID_RESOLUTIONS: frozenset[str] = frozenset({"480p", "720p", "1080p"})
_XAI_DEFAULT_RESOLUTION: str = "720p"


def _resolution_for_xai(quality_hint: str | None = None) -> str:
    """Return a valid xAI ``resolution`` value.

    Accepts ``480p`` / ``720p`` / ``1080p`` directly; anything else
    (including the legacy ``1280x720`` pixel-dim strings athena used
    internally) falls through to the default 720p.
    """
    if quality_hint and quality_hint in _XAI_VALID_RESOLUTIONS:
        return quality_hint
    return _XAI_DEFAULT_RESOLUTION


def _download(url: str, out_path: Path, *, timeout_s: float = 120.0) -> None:
    """Stream a video URL to disk. No auth header — the URL is
    typically a presigned S3-style link with its own credentials
    baked in."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "athena-xai-video/1.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
        out_path.write_bytes(resp.read())


# ---------------------------------------------------------------------------
# Provider registration
# ---------------------------------------------------------------------------


@register_provider
class XAIVideoBackend(Provider):
    """xAI Grok Imagine video adapter.

    Capability-only — chat methods raise NotImplementedError so the
    capability broker can't accidentally route conversation here.
    Declares ``video_generation=True`` so ``/video set xai_video``
    and the broker resolution both find it.
    """

    name: str = "xai_video"
    requires_api_key: bool = True
    # Credential env-var names this backend will accept, in lookup
    # order. The /video status display reads this to print accurate
    # "auth ok" / "no credential found" messages — name-derivation
    # heuristics (XAI_VIDEO_API_KEY) don't match the actual lookup
    # (XAI_API_KEY).
    credential_env_vars: tuple[str, ...] = (
        "ATHENA_XAI_API_KEY",
        "XAI_API_KEY",
    )
    # Credential-pool provider names (the secure store) this backend
    # accepts, in lookup order. /video status reads this to report
    # pool-stored keys, not just env-var ones.
    credential_pool_names: tuple[str, ...] = _CREDENTIAL_POOL_NAMES

    @classmethod
    def static_capabilities(cls) -> Capabilities:
        return Capabilities(
            video_generation=True,
            is_local=False,
            tool_calls=False,
            streaming=False,
        )

    # ------------------------------------------------------------------
    # Chat ABC — not a chat backend.
    # ------------------------------------------------------------------

    def stream_chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> Iterator[StreamChunk]:
        raise NotImplementedError(
            "xai_video is capability-only (video_generation); "
            "route via best_provider_for({'video_generation'})"
        )

    def parse_tool_calls(
        self, content: str, raw_response: dict[str, Any]
    ) -> tuple[str, list[dict[str, Any]]]:
        return content, []

    # ------------------------------------------------------------------
    # VideoGenerationBackend protocol
    # ------------------------------------------------------------------

    def estimate(self, request: job_mod.GenerationRequest) -> job_mod.CostEstimate:
        return job_mod.CostEstimate(
            seconds_est=_estimate_seconds(request.duration_s),
            cost_est=None,  # xAI per-second pricing not documented yet
        )

    def submit(self, request: job_mod.GenerationRequest) -> job_mod.JobHandle:
        api_key = _resolve_api_key()
        if not api_key:
            raise XAIAPIError(
                "xAI video: no API key. Add it to the secure credential "
                "pool with `athena providers add-credential xai <key>` "
                "(shared with the xAI chat provider), or set "
                "ATHENA_XAI_API_KEY in ~/.athena/.env (key from "
                "console.x.ai). The X bearer token used by search_x is a "
                "different credential and does not work here."
            )

        # text-to-video uses .prompt; image-to-video would need a
        # different endpoint shape — xAI image-to-video isn't in the
        # current API surface, so error clearly.
        if request.mode != "text_to_video":
            raise XAIAPIError(
                f"xAI video adapter only supports text_to_video; got mode={request.mode!r}."
            )

        # xAI's API expects `duration` as a positive integer (seconds).
        # Reject zero/negative; round up fractional seconds so
        # duration_s=5.5 becomes 6, not 5. The orchestrator's
        # GenerationRequest carries float seconds because some
        # backends (local diffusion) support sub-second steps;
        # xAI just doesn't.
        duration_int = max(1, int(round(float(request.duration_s))))
        body: dict[str, Any] = {
            "model": _DEFAULT_MODEL,
            "prompt": request.prompt,
            "duration": duration_int,
            "aspect_ratio": request.aspect,
            "resolution": _resolution_for_xai(),
        }
        if request.seed is not None:
            body["seed"] = int(request.seed)

        resp = _http(
            "POST",
            f"{_API_BASE}/videos/generations",
            api_key=api_key,
            body=body,
        )
        request_id = resp.get("request_id") or resp.get("id")
        if not request_id:
            raise XAIAPIError(f"xAI submit returned no request_id; body: {resp!r}")

        return job_mod.JobHandle(
            backend=self.name,
            job_id=str(request_id),
            status="pending",
            extra={"submit_response": resp},
        )

    def poll(self, handle: job_mod.JobHandle) -> job_mod.JobHandle:
        api_key = _resolve_api_key()
        if not api_key:
            # Can't poll without auth; mark as failed so the loop
            # surfaces the credential error instead of spinning.
            handle.status = "failed"
            handle.error = "xAI video: no API key for poll"
            return handle

        try:
            resp = _http(
                "GET",
                f"{_API_BASE}/videos/{handle.job_id}",
                api_key=api_key,
            )
        except XAIAPIError as e:
            # Transient network/HTTP failure shouldn't be terminal;
            # keep the handle in its current state and surface the
            # error in `extra` so the caller can log + retry the
            # poll. The orchestrator decides whether to keep going.
            handle.extra["last_poll_error"] = str(e)
            return handle

        # Map xAI's status strings onto athena's JobStatus literal.
        # Unknown values → keep as "running" rather than guessing.
        xai_status = str(resp.get("status", "")).lower()
        if xai_status == "done" or xai_status == "completed":
            handle.status = "done"
            handle.progress = 1.0
            handle.extra["poll_response"] = resp
        elif xai_status in ("failed", "error", "cancelled"):
            handle.status = "failed"
            handle.error = str(resp.get("error") or resp)
        elif xai_status in ("processing", "running"):
            handle.status = "running"
            # xAI doesn't typically expose progress; surface a
            # mid-flight value so the operator UI shows movement.
            handle.progress = max(handle.progress, 0.5)
        else:
            # "pending" or anything we don't recognise — keep the
            # current state.
            pass

        return handle

    def fetch(
        self,
        handle: job_mod.JobHandle,
        *,
        out_dir: Path,
    ) -> Path:
        if handle.status != "done":
            raise XAIAPIError(
                f"xAI fetch called with status={handle.status!r}; "
                "only completed jobs can be fetched."
            )
        resp = handle.extra.get("poll_response") or {}
        video = resp.get("video") if isinstance(resp, dict) else None
        url = (video or {}).get("url") if isinstance(video, dict) else None
        if not url:
            raise XAIAPIError(f"xAI fetch: no video.url in poll response; got {resp!r}")

        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / f"{handle.job_id}.mp4"
        _download(str(url), target)
        logger.info(
            "xai_video: fetched %s (%d bytes) for job %s",
            target,
            target.stat().st_size,
            handle.job_id,
        )
        return target

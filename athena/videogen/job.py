"""Async video-generation job — submit → poll → fetch with a cost guard (T6-05.1).

Video generation is slow (minutes) and can be expensive
(per-second cloud costs). The two design points this module
addresses:

  1. The job is modelled as **submit → poll → fetch**, not a
     blocking call. Backends return a :class:`JobHandle` from
     ``submit``; the loop polls ``status(handle)`` until done,
     then ``fetch(handle, out_dir)`` returns the local file
     path. Athena can do other work between polls.

  2. The :class:`CostEstimate` guard confirms with the user
     before any job that exceeds the configured thresholds —
     ``video_confirm_over_seconds`` for wall-clock, and
     ``video_confirm_over_cost`` for vendor-reported dollar
     cost. **Never silently submit an expensive job.**

The actual vendor specifics — endpoints, model names, response
shapes — live in :mod:`athena.videogen.backends`. This module
defines the Protocol every backend implements + the
orchestration around it.

Athena is sync throughout, so the loop here is sync. A backend
implementer who needs concurrent polls can use threads or an
asyncio bridge inside the adapter; the contract this module
exposes is plain function calls.
"""

from __future__ import annotations

import dataclasses
import hashlib
import logging
import time
from pathlib import Path
from typing import Any, Callable, Literal, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request + response types
# ---------------------------------------------------------------------------


GenerationMode = Literal["text_to_video", "image_to_video"]


@dataclasses.dataclass(frozen=True)
class GenerationRequest:
    """One job request. Either ``prompt`` (text→video) or
    ``image_path`` + ``motion_prompt`` (image→video) populated.

    ``aspect`` is the canonical "16:9"-style string; backends
    map to whatever shape they actually accept.
    """

    mode: GenerationMode
    prompt: str = ""
    image_path: Optional[Path] = None
    motion_prompt: str = ""
    duration_s: float = 5.0
    aspect: str = "16:9"
    seed: Optional[int] = None


@dataclasses.dataclass(frozen=True)
class CostEstimate:
    """Backend's best estimate of what this job will take.

    ``seconds_est``     wall-clock seconds; required (backends
                        always know roughly how long)
    ``cost_est``        dollar cost; optional — local backends
                        and a "free tier" cloud backend may
                        not report one
    """

    seconds_est: float
    cost_est: Optional[float] = None

    def needs_confirm(self, cfg: Any) -> bool:
        """Decide whether this estimate trips a confirmation
        threshold. The check is conservative: EITHER threshold
        triggers (a 5-second job costing $50 still confirms; a
        free job that takes 10 minutes also confirms)."""
        vg = getattr(cfg, "video_generation", None)
        sec_threshold = float(vg.confirm_over_seconds if vg is not None else 60.0)
        cost_threshold = float(vg.confirm_over_cost if vg is not None else 1.0)
        if sec_threshold > 0 and self.seconds_est > sec_threshold:
            return True
        if (
            self.cost_est is not None
            and cost_threshold > 0
            and self.cost_est > cost_threshold
        ):
            return True
        return False


JobStatus = Literal["pending", "running", "done", "failed", "cancelled"]


@dataclasses.dataclass
class JobHandle:
    """Backend-opaque identifier for a submitted job + the
    polling state the orchestration uses."""

    backend: str
    job_id: str
    status: JobStatus = "pending"
    progress: float = 0.0  # 0..1
    error: Optional[str] = None
    # Backends can stash their own state here; the orchestrator
    # passes the handle back unchanged.
    extra: dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class GenerationResult:
    """The orchestrator's return shape — what callers (the two
    tools in T6-05.3) surface to the model."""

    status: str  # done | declined | timeout | error | cancelled
    path: Optional[Path] = None
    sha256: Optional[str] = None
    duration_s: Optional[float] = None
    seconds_taken: Optional[float] = None
    cost_est: Optional[float] = None
    estimate: Optional[CostEstimate] = None
    backend: Optional[str] = None
    frame_check: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "status": self.status,
            "backend": self.backend,
        }
        if self.path is not None:
            out["path"] = str(self.path)
        if self.sha256 is not None:
            out["sha256"] = self.sha256
        if self.duration_s is not None:
            out["duration_s"] = self.duration_s
        if self.seconds_taken is not None:
            out["seconds_taken"] = self.seconds_taken
        if self.cost_est is not None:
            out["cost_est"] = self.cost_est
        if self.estimate is not None:
            out["estimate"] = {
                "seconds_est": self.estimate.seconds_est,
                "cost_est": self.estimate.cost_est,
            }
        if self.frame_check is not None:
            out["frame_check"] = self.frame_check
        if self.error is not None:
            out["error"] = self.error
        return out


# ---------------------------------------------------------------------------
# Backend protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class VideoGenerationBackend(Protocol):
    """The shape every video-generation adapter implements.

    Vendor specifics are the adapter's responsibility — model
    names, API URLs, response decoding. The orchestrator only
    sees the four methods below.
    """

    name: str

    def estimate(self, request: GenerationRequest) -> CostEstimate: ...
    def submit(self, request: GenerationRequest) -> JobHandle: ...
    def poll(self, handle: JobHandle) -> JobHandle: ...
    def fetch(self, handle: JobHandle, *, out_dir: Path) -> Path: ...


# ---------------------------------------------------------------------------
# Broker resolution (T6-05.2)
# ---------------------------------------------------------------------------


def resolve_backend(cfg: Any) -> Optional["VideoGenerationBackend"]:
    """Pick a video-generation backend via the T5-05 media
    broker. Returns None when no provider declares the
    ``video_generation`` capability OR when the chosen class
    can't be instantiated (hosted providers without
    credentials fall through to None — callers surface a
    structured "not configured" payload).

    Resolution order:

    1. ``cfg.video_backend`` (explicit pick from ``/video set`` or
       the TOML field). When set to a registered provider name, that
       provider is used unconditionally — no broker capability scan.
    2. Otherwise: capability broker, biased by
       ``cfg.video_backend_prefer`` (default "local") and
       ``cfg.media_backend_prefer``.

    Local-preference is governed by
    ``cfg.media_backend_prefer`` (default "local"); a
    capability-only ``cfg.video_backend_prefer`` override
    nudges the broker if set.
    """
    from ..media import MediaRegistry
    from ..providers import get_provider_class

    # 1. Explicit selector wins. Unknown names log + fall through to
    #    the broker rather than failing — the operator still gets *a*
    #    backend instead of a hard error.
    vg = getattr(cfg, "video_generation", None)
    pinned_name = vg.backend if vg is not None else None
    if pinned_name:
        try:
            pinned_cls = get_provider_class(pinned_name)
        except KeyError:
            logger.warning(
                "videogen: cfg.video_backend=%r is not a registered "
                "provider — falling back to broker resolution. "
                "Available: see /video list.",
                pinned_name,
            )
        else:
            if not pinned_cls.static_capabilities().supports("video_generation"):
                logger.warning(
                    "videogen: cfg.video_backend=%r does not declare "
                    "video_generation capability — falling back to broker.",
                    pinned_name,
                )
            else:
                try:
                    return pinned_cls()  # type: ignore[return-value]
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        "videogen: could not instantiate pinned backend %r: %s. "
                        "Falling back to broker.",
                        pinned_name, e,
                    )

    # video_backend_prefer overrides media_backend_prefer for
    # this specific capability. The broker's preference field
    # is read off `cfg`, so we temporarily override it via a
    # shim Namespace — keeps the original cfg untouched.
    vg_pref = (vg.backend_prefer if vg is not None else None) or None
    prefer = vg_pref or getattr(cfg, "media_backend_prefer", "local")
    cfg_shim = type(
        "VideoBackendCfg",
        (),
        {
            "media_backend_prefer": prefer,
        },
    )()
    registry = MediaRegistry(cfg=cfg_shim)
    backend_cls = registry.backend_for("video_generation")
    if backend_cls is None:
        logger.info("videogen: no provider declares video_generation")
        return None
    try:
        instance = backend_cls()
    except Exception as e:  # noqa: BLE001
        logger.info(
            "videogen: could not instantiate video-generation backend %r: %s",
            backend_cls.name,
            e,
        )
        return None
    # Type-check the instance against our protocol contract.
    # Loose duck-typing — protocols don't enforce isinstance
    # at runtime without runtime_checkable, but we want a
    # clear log when the resolved class doesn't have the
    # methods we need.
    for method in ("estimate", "submit", "poll", "fetch"):
        if not callable(getattr(instance, method, None)):
            logger.warning(
                "videogen: provider %r missing %r; not a VideoGenerationBackend",
                backend_cls.name,
                method,
            )
            return None
    return instance


# ---------------------------------------------------------------------------
# Confirm callback
# ---------------------------------------------------------------------------


ConfirmFn = Callable[[CostEstimate, GenerationRequest], bool]
"""(estimate, request) → True iff the user approved the job.
Default-deny when no callback is plumbed in — preserves the
"never silently spend" invariant."""


def default_deny(estimate: CostEstimate, request: GenerationRequest) -> bool:
    """The safe default when a tool is invoked without a real
    UI to prompt. Always returns False — the job is declined,
    the user gets a structured payload telling them to approve
    explicitly."""
    logger.info(
        "videogen: no confirm callback registered; declining job over "
        "thresholds (%.1fs / $%s)",
        estimate.seconds_est,
        estimate.cost_est,
    )
    return False


# ---------------------------------------------------------------------------
# The orchestrator
# ---------------------------------------------------------------------------


VisionCheckFn = Callable[[Path], Optional[str]]
"""Optional first/last-frame sanity check. Pass through to the
T4-01 vision-analyze surface in production; tests omit."""


_POLL_FALLBACK_S = 5.0
_MAX_POLL_S = 3600.0  # 1 hour wall-clock ceiling per job


def run_generation(
    request: GenerationRequest,
    *,
    backend: VideoGenerationBackend,
    cfg: Any,
    confirm: ConfirmFn | None = None,
    vision_check: VisionCheckFn | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> GenerationResult:
    """Run the full estimate → confirm → submit → poll → fetch
    cycle. Returns a :class:`GenerationResult`. Never raises
    into the agent loop — every failure mode maps to a status
    the caller can surface.

    ``confirm`` defaults to :func:`default_deny` — a job that
    needs confirmation but has no UI plumbed gets declined.
    ``vision_check`` is optional; when set, the result includes
    a ``frame_check`` field with the vision summary.
    ``sleep`` is injectable so tests don't actually pause.
    """
    if confirm is None:
        confirm = default_deny

    # 1. Estimate.
    try:
        estimate = backend.estimate(request)
    except Exception as e:  # noqa: BLE001
        logger.warning("videogen: estimate failed: %s", e)
        return GenerationResult(
            status="error",
            backend=backend.name,
            error=f"estimate failed: {e}",
        )

    # 2. Cost guard. Confirm only when over threshold; never
    # silently submit an expensive job.
    if estimate.needs_confirm(cfg):
        try:
            approved = bool(confirm(estimate, request))
        except Exception as e:  # noqa: BLE001
            # A buggy confirm UI must not open-fail. Treat any
            # exception as denial — same contract as T6-04.
            logger.warning(
                "videogen: confirm callback raised (%s); declining", e
            )
            approved = False
        if not approved:
            return GenerationResult(
                status="declined",
                backend=backend.name,
                estimate=estimate,
            )

    # 3. Submit.
    try:
        handle = backend.submit(request)
    except Exception as e:  # noqa: BLE001
        logger.warning("videogen: submit failed: %s", e)
        return GenerationResult(
            status="error",
            backend=backend.name,
            estimate=estimate,
            error=f"submit failed: {e}",
        )

    # 4. Poll until done or timeout.
    vg_for_poll = getattr(cfg, "video_generation", None)
    poll_interval = max(
        0.1,
        float(
            vg_for_poll.poll_interval_s if vg_for_poll is not None
            else _POLL_FALLBACK_S
        ),
    )
    started_at = time.monotonic()
    while True:
        try:
            handle = backend.poll(handle)
        except Exception as e:  # noqa: BLE001
            logger.warning("videogen: poll failed: %s", e)
            return GenerationResult(
                status="error",
                backend=backend.name,
                estimate=estimate,
                error=f"poll failed: {e}",
            )
        if handle.status == "done":
            break
        if handle.status == "failed":
            return GenerationResult(
                status="error",
                backend=backend.name,
                estimate=estimate,
                error=handle.error or "backend reported failure",
            )
        if handle.status == "cancelled":
            return GenerationResult(
                status="cancelled",
                backend=backend.name,
                estimate=estimate,
            )
        if time.monotonic() - started_at > _MAX_POLL_S:
            return GenerationResult(
                status="timeout",
                backend=backend.name,
                estimate=estimate,
                error=f"poll exceeded {_MAX_POLL_S:.0f}s",
            )
        sleep(poll_interval)

    # 5. Fetch.
    out_dir = _resolve_out_dir(cfg)
    try:
        path = backend.fetch(handle, out_dir=out_dir)
    except Exception as e:  # noqa: BLE001
        logger.warning("videogen: fetch failed: %s", e)
        return GenerationResult(
            status="error",
            backend=backend.name,
            estimate=estimate,
            error=f"fetch failed: {e}",
        )

    # 6. Hash-log the output.
    sha = _hash_file(path)
    seconds_taken = time.monotonic() - started_at
    _log_media(
        cfg=cfg,
        path=path,
        sha=sha,
        request=request,
        backend_name=backend.name,
        estimate=estimate,
        seconds_taken=seconds_taken,
    )

    # 7. Optional frame check.
    frame_check_str: Optional[str] = None
    if vision_check is not None:
        try:
            frame_check_str = vision_check(path)
        except Exception as e:  # noqa: BLE001
            logger.debug("videogen: frame check failed: %s", e)

    return GenerationResult(
        status="done",
        path=path,
        sha256=sha,
        duration_s=request.duration_s,
        seconds_taken=seconds_taken,
        cost_est=estimate.cost_est,
        estimate=estimate,
        backend=backend.name,
        frame_check=frame_check_str,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_out_dir(cfg: Any) -> Path:
    vg = getattr(cfg, "video_generation", None)
    explicit = vg.output_dir if vg is not None else None
    if explicit:
        out = Path(str(explicit)).expanduser()
    else:
        try:
            from ..config import profile_dir as _pd

            profile = getattr(cfg, "profile", None) or "default"
            out = _pd(profile) / "videos"
        except Exception:  # noqa: BLE001
            out = Path("videos")
    out.mkdir(parents=True, exist_ok=True)
    return out


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _log_media(
    *,
    cfg: Any,
    path: Path,
    sha: str,
    request: GenerationRequest,
    backend_name: str,
    estimate: CostEstimate,
    seconds_taken: float,
) -> None:
    """Append a media-log row matching the existing append-only
    JSONL style athena uses for audit / metrics. The log lives
    at ``<video_output_dir>/media_log.jsonl`` so a user
    archiving the outputs dir keeps the provenance alongside.
    """
    import datetime
    import json

    log_path = path.parent / "media_log.jsonl"
    row = {
        "ts": (
            datetime.datetime.now(datetime.timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        ),
        "kind": "video_generation",
        "mode": request.mode,
        "backend": backend_name,
        "path": str(path),
        "sha256": sha,
        "duration_s": request.duration_s,
        "seconds_taken": seconds_taken,
        "cost_est": estimate.cost_est,
        "prompt": request.prompt or request.motion_prompt,
    }
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n")
    except OSError as e:
        logger.debug("videogen: media log write failed: %s", e)

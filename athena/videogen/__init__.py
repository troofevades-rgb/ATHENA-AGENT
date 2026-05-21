"""Native video generation (T6-05).

`video_generate` (text→video) + `animate_image` (image→video)
tools, both backed by the T5-05 media broker so the actual
generation backend is pluggable and capability-resolved
(``video_generation`` capability, local-preferred when a local
model exists).

Generation is slow and can be expensive. The pipeline is
**submit → poll → fetch** so a long job doesn't wedge the agent
loop, and a **cost / latency guard** confirms with the user
before kicking off any job that exceeds the configured
thresholds. Don't silently spend.

Vendor specifics (model names, exact API shapes) live in the
adapter modules under :mod:`athena.videogen.backends` — a
vendor change is a one-file edit.
"""

from .job import (
    CostEstimate,
    GenerationRequest,
    GenerationResult,
    JobHandle,
    JobStatus,
    VideoGenerationBackend,
    resolve_backend,
    run_generation,
)

__all__ = [
    "CostEstimate",
    "GenerationRequest",
    "GenerationResult",
    "JobHandle",
    "JobStatus",
    "VideoGenerationBackend",
    "resolve_backend",
    "run_generation",
]

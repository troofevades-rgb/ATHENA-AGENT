"""vision_analyze — the model-facing entry point (T4-01.5).

One tool, seven modes:

  describe        provider passthrough — caption / answer about
                  the image's content via the active vision-
                  capable provider (e.g. Ollama with a multimodal
                  model); tiles oversized inputs rather than
                  downsampling them.
  exif            local: read EXIF tags (Make / Model / DateTime
                  / Software / Lens / GPS …) — useful for
                  provenance attribution.
  ela             local: Error Level Analysis. Bright regions
                  indicate "this area compressed differently
                  from its neighbours" — a HEURISTIC for
                  detecting splicing / patching in JPEGs.
  crop            local: write a sub-region to disk as a new
                  PNG; useful before a follow-up describe.
  histogram       local: per-channel intensity histogram —
                  exposure / clipping / colour-cast reads.
  phash           local: perceptual hash (pHash by default;
                  dhash/ahash/whash also available). Returns
                  a hex fingerprint robust to mild crops /
                  resizes / re-encodes.
  compare         local: compare TWO images via metadata-strip
                  check + pHash distance — "is this the same
                  asset, re-exported, with EXIF stripped?".

Every call hashes the input file (SHA-256), writes a JSONL
audit row to <profile_dir>/vision_audit.jsonl, and returns a
JSON-encoded result string the model can parse.

Design notes:

  - Sync throughout (athena's runtime; the spec was async).
  - The describe-mode provider dispatch is split into a
    ``_dispatch_describe(provider_factory, ...)`` helper that
    tests inject a stub for. Production callers go through the
    default factory which routes via the T5-05 MediaRegistry.
  - Errors surface as JSON ``{"error": "...", "mode": "..."}``
    rather than raising. Tools that raise into the model loop
    are a poor UX — the model can't reason about a Python
    traceback, but it can reason about a structured error
    string.
  - The tool is gated by ``cfg.vision_enabled`` (default True).
    Operator who wants athena offline-only sets it False; the
    tool reports back ``vision_enabled=False`` and exits.
"""

from __future__ import annotations

import contextlib
import json
import logging
from pathlib import Path
from typing import Any, Callable

from ..config import load_config, profile_dir
from .hashlog import HashLogger, audit_path, sha256_file
from .imageops import (
    crop_region,
    error_level_analysis,
    extract_exif,
    histogram,
    metadata_strip_check,
    perceptual_hash,
    phash_distance,
)
from .passthrough import LONG_EDGE_CAP, Provider as PassthroughProvider, passthrough_blocks

logger = logging.getLogger(__name__)


VALID_MODES = (
    "describe", "exif", "ela", "crop", "histogram", "phash", "compare",
)


# ---------------------------------------------------------------
# Provider dispatch for describe mode
# ---------------------------------------------------------------


# A "provider factory" is a callable that takes the loaded cfg
# and returns *something* exposing a sync `describe(messages)`
# method that returns a string. The production factory walks
# T5-05's MediaRegistry; tests inject their own stub.
ProviderFactory = Callable[[Any], "_VisionProvider"]


class _VisionProvider:
    """Protocol — anything with a ``describe(messages) -> str``
    method qualifies. Doesn't subclass anything; ducktyping is
    enough for the analyzer's needs."""

    def describe(self, messages: list[dict[str, Any]]) -> str:  # pragma: no cover
        raise NotImplementedError


def _default_provider_factory(cfg: Any) -> _VisionProvider | None:
    """Resolve a vision-capable provider via the T5-05 media
    registry. Returns None when no provider on this host
    declares the vision capability."""
    try:
        from ..media.registry import MediaRegistry
    except Exception:
        return None
    # MediaRegistry requires cfg (keyword-only) since T5-01R —
    # without it construction raises TypeError and every
    # downstream vision call returns an unhandled error to the
    # model, which then spam-retries computer_observe expecting
    # different output.
    reg = MediaRegistry(cfg=cfg)
    provider_cls = reg.backend_for("vision")
    if provider_cls is None:
        return None
    # Instantiate. Most providers take api_key + kwargs.
    api_key = getattr(cfg, "api_key", None)
    try:
        instance = provider_cls(api_key=api_key)
    except Exception as e:  # pragma: no cover - covered via stub
        logger.warning("vision provider %r failed to instantiate: %s",
                       provider_cls.__name__, e)
        return None
    # Adapt the provider's stream_chat into the describe protocol.
    return _StreamingDescribeAdapter(instance, cfg=cfg)


class _StreamingDescribeAdapter:
    """Wraps an athena Provider so vision_analyze can call a
    single :meth:`describe` synchronously and get a string back.
    Consumes the stream, concatenates content chunks, returns the
    finished text."""

    def __init__(self, provider, *, cfg):
        self._provider = provider
        self._cfg = cfg

    def describe(self, messages: list[dict[str, Any]]) -> str:
        model = getattr(self._cfg, "model", None) or "default"
        out: list[str] = []
        for chunk in self._provider.stream_chat(
            model=model,
            messages=messages,
            tools=None,
            temperature=0.2,
            max_tokens=1024,
        ):
            kind = getattr(chunk, "kind", None)
            if kind == "content":
                out.append(getattr(chunk, "text", "") or "")
            elif kind == "end":
                break
        return "".join(out).strip()


# ---------------------------------------------------------------
# Provider resolution for passthrough block shape
# ---------------------------------------------------------------


def _passthrough_provider_for(cfg: Any) -> PassthroughProvider:
    """Pick the right block shape from the current provider name.
    The default is ``ollama`` — matches athena's most common
    deployment. Other names map to anthropic/openai when their
    provider class is the active one."""
    prov = (getattr(cfg, "provider", None) or "").lower()
    if "anthropic" in prov or "claude" in prov:
        return "anthropic"
    if "openai" in prov or "gpt" in prov:
        return "openai"
    return "ollama"


# ---------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------


def _resolve_paths(cfg: Any) -> dict[str, Path]:
    """Compute the per-profile dirs the tool writes into."""
    pdir = profile_dir(getattr(cfg, "profile", "default"))
    crop_dir = (
        Path(cfg.vision_crop_dir)
        if getattr(cfg, "vision_crop_dir", None)
        else pdir / "vision" / "crops"
    )
    return {
        "profile": pdir,
        "audit": audit_path(pdir),
        "crops": crop_dir,
    }


# ---------------------------------------------------------------
# Mode handlers
# ---------------------------------------------------------------


def _handle_exif(path: Path, log: HashLogger) -> dict[str, Any]:
    ex = extract_exif(path)
    sha = sha256_file(path)
    log.log(
        mode="exif", path=path, sha256=sha,
        size_bytes=path.stat().st_size,
    )
    return {"mode": "exif", "path": str(path), "sha256": sha, "exif": ex}


def _handle_ela(
    path: Path,
    log: HashLogger,
    *,
    quality: int,
    threshold: int,
) -> dict[str, Any]:
    sha = sha256_file(path)
    out = error_level_analysis(path, quality=quality, threshold=threshold)
    log.log(
        mode="ela", path=path, sha256=sha,
        size_bytes=path.stat().st_size,
        extra={"quality": quality, "threshold": threshold},
    )
    return {"mode": "ela", "path": str(path), "sha256": sha, **out}


def _handle_crop(
    path: Path,
    log: HashLogger,
    *,
    box: list[int] | tuple[int, int, int, int],
    out_dir: Path,
    return_b64: bool,
) -> dict[str, Any]:
    if not (isinstance(box, (list, tuple)) and len(box) == 4):
        raise ValueError("crop requires box=[x0,y0,x1,y1]")
    sha = sha256_file(path)
    out = crop_region(
        path,
        box=tuple(box),  # type: ignore[arg-type]
        out_dir=out_dir,
        return_b64=return_b64,
    )
    log.log(
        mode="crop", path=path, sha256=sha,
        size_bytes=path.stat().st_size,
        extra={"box": list(box), "out_sha256": out["sha256"]},
    )
    return {"mode": "crop", "path": str(path), "sha256": sha, **out}


def _handle_histogram(
    path: Path,
    log: HashLogger,
    *,
    bins: int,
) -> dict[str, Any]:
    sha = sha256_file(path)
    out = histogram(path, bins=bins)
    log.log(
        mode="histogram", path=path, sha256=sha,
        size_bytes=path.stat().st_size,
        extra={"bins": bins},
    )
    return {"mode": "histogram", "path": str(path), "sha256": sha, **out}


def _handle_phash(
    path: Path,
    log: HashLogger,
    *,
    algorithm: str,
    hash_size: int,
) -> dict[str, Any]:
    sha = sha256_file(path)
    out = perceptual_hash(path, algorithm=algorithm, hash_size=hash_size)
    log.log(
        mode="phash", path=path, sha256=sha,
        size_bytes=path.stat().st_size,
        extra={"algorithm": algorithm, "hash_size": hash_size},
    )
    return {"mode": "phash", "path": str(path), "sha256": sha, **out}


def _handle_compare(
    original: Path,
    suspect: Path,
    log: HashLogger,
    *,
    algorithm: str,
    hash_size: int,
) -> dict[str, Any]:
    sha_o = sha256_file(original)
    sha_s = sha256_file(suspect)
    strip = metadata_strip_check(original, suspect)
    h_o = perceptual_hash(original, algorithm=algorithm, hash_size=hash_size)
    h_s = perceptual_hash(suspect, algorithm=algorithm, hash_size=hash_size)
    distance = phash_distance(h_o["hex"], h_s["hex"])
    log.log(
        mode="compare", path=original, sha256=sha_o,
        size_bytes=original.stat().st_size,
        extra={
            "suspect_path": str(suspect),
            "suspect_sha256": sha_s,
            "phash_distance": distance,
            "strip_verdict": strip["verdict"],
        },
    )
    return {
        "mode": "compare",
        "original": {"path": str(original), "sha256": sha_o, "phash": h_o["hex"]},
        "suspect": {"path": str(suspect), "sha256": sha_s, "phash": h_s["hex"]},
        "phash_distance": distance,
        "phash_distance_reading": _phash_reading(distance),
        "metadata_strip_check": strip,
    }


def _phash_reading(d: int) -> str:
    if d == 0:
        return "identical"
    if d <= 8:
        return "strong-match (mild transform)"
    if d <= 16:
        return "similar (larger transform)"
    return "probably-different-scenes"


def _handle_describe(
    path: Path,
    log: HashLogger,
    cfg: Any,
    *,
    prompt: str,
    provider_factory: ProviderFactory,
) -> dict[str, Any]:
    sha = sha256_file(path)
    log.log(
        mode="describe", path=path, sha256=sha,
        size_bytes=path.stat().st_size,
    )
    provider = provider_factory(cfg)
    if provider is None:
        return {
            "mode": "describe",
            "path": str(path),
            "sha256": sha,
            "error": (
                "no vision-capable provider available on this host. "
                "Install a multimodal model (e.g. an Ollama vision "
                "model) or configure an external provider whose "
                "static_capabilities() declares vision=True."
            ),
        }
    pass_provider = _passthrough_provider_for(cfg)
    cap = getattr(cfg, "vision_long_edge_cap", None)
    blocks = passthrough_blocks(
        path, provider=pass_provider, long_edge_cap=cap,
    )

    # Build a single user message with the prompt + image blocks.
    user_content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    user_content.extend(blocks["blocks"])
    messages = [{"role": "user", "content": user_content}]

    try:
        answer = provider.describe(messages)
    except Exception as e:
        logger.exception("vision describe dispatch failed")
        return {
            "mode": "describe",
            "path": str(path),
            "sha256": sha,
            "error": f"describe dispatch failed: {type(e).__name__}: {e}",
        }
    return {
        "mode": "describe",
        "path": str(path),
        "sha256": sha,
        "tiled": blocks["tiled"],
        "tiles": len(blocks["blocks"]),
        "provider_shape": blocks["provider"],
        "answer": answer,
    }


# ---------------------------------------------------------------
# Public entry — registered as @tool below
# ---------------------------------------------------------------


def _run(
    *,
    mode: str,
    path: str | None = None,
    paths: list[str] | None = None,
    prompt: str = "Describe this image in concrete detail.",
    box: list[int] | None = None,
    quality: int | None = None,
    threshold: int | None = None,
    bins: int = 16,
    algorithm: str | None = None,
    hash_size: int | None = None,
    return_b64: bool = False,
    _cfg: Any = None,
    _provider_factory: ProviderFactory | None = None,
) -> str:
    """The body of the vision_analyze tool, factored out so tests
    can call it with stubs without going through the @tool
    decorator. Returns a JSON-encoded string (the tool layer
    above hands strings to the model)."""
    cfg = _cfg if _cfg is not None else load_config()
    if not getattr(cfg, "vision_enabled", True):
        return json.dumps({
            "error": "vision_enabled=False; the operator has disabled vision_analyze",
            "mode": mode,
        })
    if mode not in VALID_MODES:
        return json.dumps({
            "error": f"unknown mode {mode!r}; choose from {list(VALID_MODES)}",
            "mode": mode,
        })

    # Path-input arity check. compare needs two; all others need one.
    if mode == "compare":
        if not paths or len(paths) != 2:
            return json.dumps({
                "error": "mode=compare requires paths=[original, suspect]",
                "mode": mode,
            })
        p_orig, p_sus = Path(paths[0]), Path(paths[1])
        if not p_orig.exists():
            return json.dumps({"error": f"file not found: {paths[0]}", "mode": mode})
        if not p_sus.exists():
            return json.dumps({"error": f"file not found: {paths[1]}", "mode": mode})
    else:
        if not path:
            return json.dumps({
                "error": f"mode={mode} requires path=<file>",
                "mode": mode,
            })
        p = Path(path)
        if not p.exists():
            return json.dumps({"error": f"file not found: {path}", "mode": mode})

    paths_resolved = _resolve_paths(cfg)
    log = HashLogger(paths_resolved["audit"])

    try:
        if mode == "exif":
            return json.dumps(_handle_exif(Path(path), log))  # type: ignore[arg-type]
        if mode == "ela":
            q = quality if quality is not None else getattr(cfg, "vision_ela_quality", 80)
            t = threshold if threshold is not None else getattr(cfg, "vision_ela_threshold", 15)
            return json.dumps(_handle_ela(Path(path), log, quality=q, threshold=t))  # type: ignore[arg-type]
        if mode == "crop":
            if box is None:
                return json.dumps({"error": "crop requires box=[x0,y0,x1,y1]", "mode": mode})
            return json.dumps(_handle_crop(
                Path(path), log, box=box,  # type: ignore[arg-type]
                out_dir=paths_resolved["crops"],
                return_b64=return_b64,
            ))
        if mode == "histogram":
            return json.dumps(_handle_histogram(Path(path), log, bins=bins))  # type: ignore[arg-type]
        if mode == "phash":
            algo = algorithm or getattr(cfg, "vision_phash_algorithm", "phash")
            hs = hash_size if hash_size is not None else getattr(cfg, "vision_phash_size", 8)
            return json.dumps(_handle_phash(
                Path(path), log, algorithm=algo, hash_size=hs,  # type: ignore[arg-type]
            ))
        if mode == "compare":
            algo = algorithm or getattr(cfg, "vision_phash_algorithm", "phash")
            hs = hash_size if hash_size is not None else getattr(cfg, "vision_phash_size", 8)
            return json.dumps(_handle_compare(
                Path(paths[0]), Path(paths[1]), log,  # type: ignore[index]
                algorithm=algo, hash_size=hs,
            ))
        if mode == "describe":
            factory = _provider_factory or _default_provider_factory
            return json.dumps(_handle_describe(
                Path(path), log, cfg,  # type: ignore[arg-type]
                prompt=prompt,
                provider_factory=factory,
            ))
    except ValueError as e:
        return json.dumps({"error": str(e), "mode": mode})
    except Exception as e:
        logger.exception("vision_analyze mode=%s failed", mode)
        return json.dumps({"error": f"{type(e).__name__}: {e}", "mode": mode})

    # Unreachable; mode was validated above.
    return json.dumps({"error": "unhandled mode", "mode": mode})


# ---------------------------------------------------------------
# @tool registration
# ---------------------------------------------------------------


from ..tools.registry import tool  # noqa: E402 — late import to avoid cycles


@tool(
    name="vision_analyze",
    toolset="vision",
    description=(
        "Analyse an image — locally (no network) or via the active "
        "vision-capable provider. One tool with seven modes:\n"
        "  describe   : provider passthrough; caption / answer about\n"
        "               the image (uses the multimodal model). Tiles\n"
        "               oversized inputs rather than downsampling.\n"
        "  exif       : extract camera/date/Make/Model/GPS tags.\n"
        "  ela        : Error Level Analysis — heuristic for spliced\n"
        "               JPEG regions. Bright patches = different\n"
        "               compression from neighbours. NOT a verdict.\n"
        "  crop       : write a sub-region to disk; box=[x0,y0,x1,y1].\n"
        "  histogram  : per-channel intensity histogram; bins divides 256.\n"
        "  phash      : perceptual hash (phash/dhash/ahash/whash); use\n"
        "               compare or call phash twice for similarity.\n"
        "  compare    : two-image compare — metadata-strip + pHash\n"
        "               distance. Pass paths=[original, suspect].\n"
        "Every read is hash-logged to <profile>/vision_audit.jsonl."
    ),
    parameters={
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": list(VALID_MODES),
                "description": "Which analysis to run.",
            },
            "path": {
                "type": "string",
                "description": (
                    "Path to the image file. Required for every "
                    "mode except 'compare' (use paths=[...] instead)."
                ),
            },
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Two-element [original, suspect] — only used "
                    "by mode=compare. Ignored elsewhere."
                ),
            },
            "prompt": {
                "type": "string",
                "description": (
                    "Question / instruction for describe mode. "
                    "Default: 'Describe this image in concrete detail.'"
                ),
            },
            "box": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "crop box [x0,y0,x1,y1]; only used by mode=crop.",
            },
            "quality": {
                "type": "integer",
                "description": "ELA re-encode quality (1..100); only mode=ela. Default 80.",
            },
            "threshold": {
                "type": "integer",
                "description": "ELA patch threshold; only mode=ela. Default 15.",
            },
            "bins": {
                "type": "integer",
                "description": "histogram bin count (must divide 256). Default 16.",
            },
            "algorithm": {
                "type": "string",
                "enum": ["phash", "dhash", "ahash", "whash"],
                "description": "perceptual-hash algorithm; mode=phash or compare. Default phash.",
            },
            "hash_size": {
                "type": "integer",
                "description": "perceptual-hash grid size. Default 8.",
            },
            "return_b64": {
                "type": "boolean",
                "description": "mode=crop: also include image_b64. Default false.",
            },
        },
        "required": ["mode"],
    },
)
def vision_analyze(**kwargs: Any) -> str:
    return _run(**kwargs)

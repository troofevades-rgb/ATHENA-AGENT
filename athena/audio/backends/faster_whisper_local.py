"""Local Whisper-class STT backend via faster-whisper (T4-04.1).

`faster-whisper` is a CTranslate2 reimplementation of OpenAI
Whisper that runs ~4x faster than the reference implementation
on CPU and supports int8 quantization. The "local" pattern of
choice for on-device STT — model files cache under
``~/.cache/huggingface/`` and stay on disk; recordings never
leave the machine.

This adapter is the in-tree default for the audio_transcription
capability. Real cloud adapters land alongside one per file
with the same Protocol shape.

Lazy model load: importing this module costs almost nothing
(the ML library is heavy but loaded on first ``transcribe``).
That keeps athena startup fast for sessions that never use
audio.

Model cache: ``cfg.audio_whisper_model`` picks the model
("tiny" / "base" / "small" / "medium" / "large-v3"); first use
downloads it; subsequent calls reuse. ``audio_whisper_device``
and ``audio_whisper_compute_type`` are passed through to the
WhisperModel constructor for CUDA / int8 tuning.

Diarization: faster-whisper proper doesn't ship a speaker
diarizer (that's pyannote.audio's job — a separate heavy dep).
This backend honors ``diarize=True`` by returning segments
with ``speaker=None`` — the contract says backends without
diarization support do exactly that. A future
``pyannote_diarizer.py`` backend can declare a separate
capability and the tool can compose the two.
"""

from __future__ import annotations

import logging
import os
import threading
import wave
from pathlib import Path
from typing import Any

from ...providers import register_provider
from ...providers.base import Capabilities, Provider, StreamChunk
from ..job import ContentType, Segment, TranscribeResult

logger = logging.getLogger(__name__)


# Lazy-loaded singleton: the WhisperModel is expensive to
# construct (the model file gets loaded into memory + the
# CTranslate2 graph is built). Re-creating per call would be
# slow + wasteful; keeping one process-wide instance with a
# lock is the right trade.
_model_lock = threading.Lock()
_model: Any = None
_model_key: tuple[str, str, str] | None = None
_cuda_dll_dirs_registered = False


def _register_cuda_dll_dirs() -> None:
    """On Windows, add the NVIDIA pip-wheel bin dirs to the DLL search path.

    ``nvidia-cublas-cu12`` / ``nvidia-cudnn-cu12`` ship ``cublas64_12.dll`` /
    ``cudnn_*.dll`` under ``site-packages/nvidia/*/bin``, which is NOT on
    Windows' DLL search path — so CTranslate2 fails to load them at
    inference time with "cublas64_12.dll is not found" *even though the GPU
    is detected*. Registering the dirs via ``os.add_dll_directory`` fixes
    GPU transcription with zero extra setup beyond ``pip install
    nvidia-cublas-cu12 nvidia-cudnn-cu12``. No-op off Windows / when the
    wheels aren't present. Idempotent."""
    global _cuda_dll_dirs_registered
    if _cuda_dll_dirs_registered or os.name != "nt":
        _cuda_dll_dirs_registered = True
        return
    try:
        import sysconfig

        purelib = sysconfig.get_paths()["purelib"]
        for sub in ("cublas", "cudnn"):
            d = os.path.join(purelib, "nvidia", sub, "bin")
            if os.path.isdir(d):
                # add_dll_directory covers LoadLibraryEx(user-dirs); PATH
                # covers plain LoadLibrary, which CTranslate2 uses to pull
                # cuBLAS lazily at *inference* time. Need both.
                os.add_dll_directory(d)
                os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
                logger.debug("faster-whisper: registered CUDA DLL dir %s", d)
    except Exception as e:  # noqa: BLE001 — best-effort; CUDA load may still work
        logger.debug("faster-whisper: could not register CUDA DLL dirs: %s", e)
    _cuda_dll_dirs_registered = True


def _load_model(name: str, device: str, compute_type: str):
    """Load (or reuse) the WhisperModel. Lazy so importing this
    file doesn't pull faster-whisper unless someone actually
    transcribes."""
    global _model, _model_key

    key = (name, device, compute_type)
    with _model_lock:
        if _model is not None and _model_key == key:
            return _model
        if device != "cpu":
            _register_cuda_dll_dirs()  # so cublas/cudnn load on Windows GPU
        from faster_whisper import WhisperModel  # local import — lazy

        logger.info(
            "faster-whisper: loading model=%r device=%r compute_type=%r",
            name,
            device,
            compute_type,
        )
        _model = WhisperModel(
            name,
            device=device,
            compute_type=compute_type,
        )
        _model_key = key
        return _model


@register_provider
class FasterWhisperLocalBackend(Provider):
    """faster-whisper local STT backend.

    Declares ``audio_transcription=True`` + ``is_local=True``
    so the broker prefers it under the default ``local`` media
    preference. Chat methods raise NotImplementedError — this
    is a capability-only provider, same shape as T6-05's
    stub_video_local.
    """

    name: str = "audio_whisper_local"
    requires_api_key: bool = False

    @classmethod
    def static_capabilities(cls) -> Capabilities:
        return Capabilities(
            audio_transcription=True,
            is_local=True,
            tool_calls=False,
            streaming=False,
        )

    def __init__(self, api_key: str | None = None, **kwargs: Any):
        super().__init__(api_key=api_key, **kwargs)
        self._cfg_override = kwargs.get("cfg")

    # ---- chat ABC plumbing — not a chat backend ----

    def stream_chat(self, **kwargs: Any):  # noqa: D401
        raise NotImplementedError(
            "audio_whisper_local is a transcription backend, not a chat "
            "provider; route via MediaRegistry.backend_for('audio_transcription')"
        )

    def parse_tool_calls(self, content: str, raw_response: dict[str, Any]):
        return content, []

    # ---- AudioBackend protocol ----

    def is_available(self) -> bool:
        """True if faster-whisper is importable. The actual
        model load happens lazily on first ``transcribe``."""
        try:
            import faster_whisper  # noqa: F401

            return True
        except Exception:  # noqa: BLE001
            return False

    def transcribe(
        self,
        path: Path | str,
        *,
        language: str | None = None,
        diarize: bool = False,
        chunk_offset_s: float = 0.0,
    ) -> TranscribeResult:
        cfg = self._load_cfg()
        model = _load_model(
            getattr(cfg, "audio_whisper_model", "base"),
            _resolve_device(getattr(cfg, "audio_whisper_device", "auto")),
            _resolve_compute_type(getattr(cfg, "audio_whisper_compute_type", "auto")),
        )

        # faster-whisper's transcribe returns (segments_iter, info).
        # Anti-hallucination guards (whisper otherwise emits phantom phrases
        # like "Thank you for watching" on silence/non-speech): a single
        # greedy pass (temperature=0, no fallback), don't carry context across
        # clips, and keep the no-speech / low-logprob / repetition thresholds
        # explicit so quiet or empty audio is rejected rather than confabulated.
        try:
            segments_iter, info = model.transcribe(
                str(path),
                language=language,
                beam_size=5,
                vad_filter=True,
                temperature=0.0,
                condition_on_previous_text=False,
                no_speech_threshold=0.6,
                log_prob_threshold=-1.0,
                compression_ratio_threshold=2.4,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("faster-whisper transcribe failed for %s: %s", path, e)
            return TranscribeResult(segments=[])

        out: list[Segment] = []
        for s in segments_iter:
            text = (getattr(s, "text", "") or "").strip()
            if not text:
                continue
            out.append(
                Segment(
                    start=float(getattr(s, "start", 0.0)) + chunk_offset_s,
                    end=float(getattr(s, "end", 0.0)) + chunk_offset_s,
                    text=text,
                    speaker=None,  # see module docstring re: diarization
                )
            )

        detected_lang = getattr(info, "language", None)
        duration = getattr(info, "duration", None)
        if duration is None:
            duration = _read_duration(path)

        return TranscribeResult(
            segments=out,
            language=detected_lang,
            duration=float(duration) if duration is not None else None,
        )

    def classify(self, path: Path | str) -> ContentType:
        """No-op classifier — faster-whisper itself doesn't do
        content-type detection. A future audio-content classifier
        would be a separate adapter declaring a different
        capability."""
        # The tool layer falls through to "unknown" gracefully.
        return "unknown"

    # ---- internals ----

    def _load_cfg(self):
        if self._cfg_override is not None:
            return self._cfg_override
        from ...config import load_config

        return load_config()


# ---------------------------------------------------------------
# helpers
# ---------------------------------------------------------------


def _resolve_device(pref: str) -> str:
    """Translate the ``audio_whisper_device`` config preference
    into faster-whisper's expected value. ``"auto"`` keeps the
    library's own auto-detect path; ``"cpu"`` / ``"cuda"`` are
    passed through verbatim."""
    if pref not in ("auto", "cpu", "cuda"):
        return "auto"
    return pref


def _resolve_compute_type(pref: str) -> str:
    """``"auto"`` lets faster-whisper pick (default int8 on CPU,
    float16 on CUDA). Otherwise pass through."""
    if pref == "auto":
        return "default"
    if pref in ("int8", "int16", "float16", "float32"):
        return pref
    return "default"


def _read_duration(path: Path | str) -> float | None:
    """Cheap fallback duration read for WAV inputs; returns
    None for other formats (faster-whisper's info.duration is
    almost always present, so this rarely fires)."""
    try:
        with wave.open(str(path), "rb") as w:
            frames = w.getnframes()
            rate = w.getframerate() or 1
            return frames / rate
    except Exception:  # noqa: BLE001
        return None

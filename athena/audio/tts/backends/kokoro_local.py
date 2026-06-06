"""Local neural TTS via Kokoro (``kokoro-onnx``) — a much more natural voice
than Piper, still fully on-device (no API key, no network), on-brand with the
air-gapped posture.

Kokoro needs two model files (downloaded once, not pip-shipped): the ONNX
weights (``kokoro-v1.0.onnx``) and the packed voice embeddings
(``voices-v1.0.bin``). They default to ``~/.athena/voices/`` and can be moved
via ``cfg.kokoro_model_path`` / ``cfg.kokoro_voices_path``. The voice is a
name (e.g. ``af_heart``, ``af_bella``, ``am_michael``, ``bf_emma``) from
``cfg.kokoro_voice`` — NOT a file path (that's the Piper convention).

Until both files are present + ``kokoro-onnx`` is importable, ``is_available``
reports False and the resolver falls through — synthesis is "unavailable",
never a crash. Lazy + cached: importing this module costs nothing and the
model loads on first :meth:`synthesize`. Kokoro renders at 24 kHz; the result
reports that and the playback path resamples to Discord's 48 kHz.
"""

from __future__ import annotations

import os
import tempfile
import threading
import wave
from pathlib import Path
from typing import Any

from ....providers import register_provider
from ....providers.base import Capabilities, Provider
from ..base import DISCORD_SAMPLE_RATE, SynthResult

_DEFAULT_DIR = Path.home() / ".athena" / "voices"
_DEFAULT_MODEL = _DEFAULT_DIR / "kokoro-v1.0.onnx"
_DEFAULT_VOICES = _DEFAULT_DIR / "voices-v1.0.bin"
_DEFAULT_VOICE = "af_heart"

_lock = threading.Lock()
_kokoro: Any = None
_kokoro_key: tuple[str, str] | None = None


def _load_kokoro(model_path: str, voices_path: str) -> Any:
    """Load (or reuse) the Kokoro engine. Lazy + cached so repeated turns
    don't reload the ~310MB ONNX graph."""
    global _kokoro, _kokoro_key
    with _lock:
        key = (model_path, voices_path)
        if _kokoro is not None and _kokoro_key == key:
            return _kokoro
        from kokoro_onnx import Kokoro  # heavy + optional

        _kokoro = Kokoro(model_path, voices_path)
        _kokoro_key = key
        return _kokoro


@register_provider
class KokoroLocalBackend(Provider):
    """Kokoro local TTS backend.

    Declares ``text_to_speech=True`` + ``is_local=True`` so the resolver
    prefers it under the default local preference. Chat methods raise —
    capability-only provider, same shape as the Piper backend.
    """

    name: str = "tts_kokoro_local"
    requires_api_key: bool = False

    @classmethod
    def static_capabilities(cls) -> Capabilities:
        return Capabilities(
            text_to_speech=True,
            is_local=True,
            tool_calls=False,
            streaming=False,
        )

    def __init__(self, api_key: str | None = None, **kwargs: Any) -> None:
        super().__init__(api_key=api_key, **kwargs)
        self._cfg_override = kwargs.get("cfg")

    # ---- chat ABC plumbing — not a chat backend ----

    def stream_chat(self, **kwargs: Any) -> Any:  # noqa: D401
        raise NotImplementedError(
            "tts_kokoro_local is a speech-synthesis backend, not a chat "
            "provider; route via athena.audio.tts.resolve.resolve_tts_backend"
        )

    def parse_tool_calls(self, content: str, raw_response: dict[str, Any]) -> tuple[str, list[Any]]:
        return content, []

    # ---- helpers ----

    def _load_cfg(self) -> Any:
        if self._cfg_override is not None:
            return self._cfg_override
        try:
            from ....config import load_config

            return load_config()
        except Exception:  # noqa: BLE001 — cfg is best-effort here
            return None

    def _paths(self) -> tuple[Path, Path]:
        cfg = self._load_cfg()
        model = (getattr(cfg, "kokoro_model_path", None) or str(_DEFAULT_MODEL)).strip()
        voices = (getattr(cfg, "kokoro_voices_path", None) or str(_DEFAULT_VOICES)).strip()
        return Path(model).expanduser(), Path(voices).expanduser()

    def _voice_name(self, voice: str | None) -> str:
        v = (voice or "").strip()
        if v:
            return v
        cfg = self._load_cfg()
        return (getattr(cfg, "kokoro_voice", "") or "").strip() or _DEFAULT_VOICE

    # ---- SpeechSynthBackend protocol ----

    def is_available(self) -> bool:
        """True only when kokoro-onnx is importable AND both model files are
        present. Reporting True without them would be a lie the resolver acts
        on (the model load happens lazily on first synthesize)."""
        try:
            import kokoro_onnx  # noqa: F401
        except Exception:  # noqa: BLE001
            return False
        model, voices = self._paths()
        return model.is_file() and voices.is_file()

    def synthesize(
        self,
        text: str,
        *,
        out_path: Path | str | None = None,
        voice: str | None = None,
        sample_rate: int = DISCORD_SAMPLE_RATE,
    ) -> SynthResult:
        import numpy as np

        model, voices = self._paths()
        if not (model.is_file() and voices.is_file()):
            raise RuntimeError(
                "kokoro: model/voices files missing (download kokoro-v1.0.onnx "
                "+ voices-v1.0.bin) — is_available() should have gated this"
            )
        kokoro = _load_kokoro(str(model), str(voices))
        # create() -> (float32 samples in [-1, 1], sample_rate) at 24 kHz mono.
        samples, rate = kokoro.create(text, voice=self._voice_name(voice), speed=1.0, lang="en-us")
        pcm = (
            (np.asarray(samples, dtype=np.float32).clip(-1.0, 1.0) * 32767.0)
            .astype("<i2")
            .tobytes()
        )

        if out_path is not None:
            path = Path(out_path)
            path.parent.mkdir(parents=True, exist_ok=True)
        else:
            fd, tmp = tempfile.mkstemp(suffix=".wav", prefix="athena_tts_")
            os.close(fd)
            path = Path(tmp)

        rate = int(rate) or 24_000
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(rate)
            wf.writeframes(pcm)
        duration_s = (len(pcm) / 2 / rate) if rate else 0.0
        return SynthResult(
            path=path, sample_rate=rate, duration_s=float(duration_s), backend=self.name
        )

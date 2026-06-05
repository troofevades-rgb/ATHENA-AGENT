"""Local neural TTS via Piper (the in-tree default once a voice is set).

`piper-tts` runs ONNX voice models fully on-device — no API key, no
network, on-brand with the air-gapped posture. A voice is a ``.onnx``
model file (plus its ``.onnx.json`` sidecar); the path comes from
``cfg.tts_voice``. Until a voice is configured, :meth:`is_available`
reports False and the resolver falls through — synthesis is "unavailable",
never a crash (the design's graceful-degrade contract).

Lazy everywhere: importing this module costs nothing, and the voice model
loads on first :meth:`synthesize` (cached). Piper voices set their own
sample rate (commonly 22.05 kHz); the result reports the real rate and the
caller resamples to Discord's 48 kHz if it must.
"""

from __future__ import annotations

import logging
import os
import tempfile
import threading
import wave
from pathlib import Path
from typing import Any

from ....providers import register_provider
from ....providers.base import Capabilities, Provider
from ..base import DISCORD_SAMPLE_RATE, SynthResult

logger = logging.getLogger(__name__)

_voice_lock = threading.Lock()
_voice: Any = None
_voice_key: str | None = None


def _load_voice(model_path: str) -> Any:
    """Load (or reuse) the PiperVoice for ``model_path``. Lazy + cached so
    repeated turns don't reload the ONNX model."""
    global _voice, _voice_key
    with _voice_lock:
        if _voice is not None and _voice_key == model_path:
            return _voice
        from piper import PiperVoice  # local import — heavy + optional

        _voice = PiperVoice.load(model_path)
        _voice_key = model_path
        return _voice


@register_provider
class PiperLocalBackend(Provider):
    """Piper local TTS backend.

    Declares ``text_to_speech=True`` + ``is_local=True`` so the resolver
    prefers it under the default local preference. Chat methods raise —
    capability-only provider, same shape as the STT backend.
    """

    name: str = "tts_piper_local"
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

    def stream_chat(self, **kwargs: Any):  # noqa: D401
        raise NotImplementedError(
            "tts_piper_local is a speech-synthesis backend, not a chat "
            "provider; route via athena.audio.tts.resolve.resolve_tts_backend"
        )

    def parse_tool_calls(self, content: str, raw_response: dict[str, Any]):
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

    def _voice_model_path(self, voice: str | None) -> str | None:
        """Resolve the ``.onnx`` voice model path: explicit ``voice`` arg
        wins, else ``cfg.tts_voice``. Returns None when none is set or the
        file is missing."""
        candidate = (voice or "").strip()
        if not candidate:
            cfg = self._load_cfg()
            candidate = (getattr(cfg, "tts_voice", "") or "").strip()
        if not candidate:
            return None
        path = Path(candidate).expanduser()
        return str(path) if path.is_file() else None

    # ---- SpeechSynthBackend protocol ----

    def is_available(self) -> bool:
        """True only when piper is importable AND a voice model is
        configured + present. Both are required to actually synthesize, so
        reporting True without them would be a lie the resolver acts on."""
        try:
            import piper  # noqa: F401
        except Exception:  # noqa: BLE001
            return False
        return self._voice_model_path(None) is not None

    def synthesize(
        self,
        text: str,
        *,
        out_path: Path | str | None = None,
        voice: str | None = None,
        sample_rate: int = DISCORD_SAMPLE_RATE,
    ) -> SynthResult:
        model_path = self._voice_model_path(voice)
        if model_path is None:
            raise RuntimeError(
                "piper: no voice model configured (set cfg.tts_voice to a "
                ".onnx path) — is_available() should have gated this"
            )
        piper_voice = _load_voice(model_path)

        if out_path is not None:
            path = Path(out_path)
            path.parent.mkdir(parents=True, exist_ok=True)
        else:
            fd, tmp = tempfile.mkstemp(suffix=".wav", prefix="athena_tts_")
            os.close(fd)
            path = Path(tmp)

        with wave.open(str(path), "wb") as wf:
            # PiperVoice.synthesize writes PCM frames into the wave writer
            # and sets channels / sampwidth / framerate from the model.
            piper_voice.synthesize(text, wf)
            rate = wf.getframerate() or DISCORD_SAMPLE_RATE
            n_frames = wf.getnframes()

        duration_s = (n_frames / rate) if rate else 0.0
        return SynthResult(
            path=path, sample_rate=int(rate), duration_s=float(duration_s), backend=self.name
        )

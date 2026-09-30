"""ASR and TTS factories (config-selected) plus fakes for tests.

ASRService: pipecat STTService, audio frames in -> TranscriptionFrame out.
TTSService: pipecat TTSService, text in -> audio frames out.

Do not import pipecat.services.whisper.stt. faster-whisper is used directly.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

import numpy as np
from pipecat.frames.frames import Frame, TranscriptionFrame, TTSAudioRawFrame
from pipecat.services.stt_service import SegmentedSTTService
from pipecat.services.tts_service import TTSService
from pipecat.utils.time import time_now_iso8601

from app.config import Settings

_whisper_models: dict[str, object] = {}


def get_whisper_model(settings: Settings):
    """Load faster-whisper once. local_files_only so runtime stays offline."""
    key = settings.whisper_model
    cached = _whisper_models.get(key)
    if cached is None:
        from faster_whisper import WhisperModel

        cached = WhisperModel(key, device="cpu", compute_type="int8", local_files_only=True)
        _whisper_models[key] = cached
    return cached


def build_asr(settings: Settings):
    if settings.asr_backend == "whisper":
        return FasterWhisperASR(get_whisper_model(settings))
    if settings.asr_backend == "parakeet":
        raise RuntimeError(
            "ASR_BACKEND=parakeet is not bundled. Use ASR_BACKEND=whisper."
        )
    if settings.asr_backend == "fake":
        return FakeASR()
    raise RuntimeError(f"unknown ASR_BACKEND {settings.asr_backend}")


def build_tts(settings: Settings):
    if settings.tts_backend == "kokoro":
        from pipecat.services.kokoro.tts import KokoroTTSService

        kokoro_dir = settings.models_dir / "kokoro"
        model = kokoro_dir / "kokoro-v1.0.onnx"
        voices = kokoro_dir / "voices-v1.0.bin"
        if not model.exists() or not voices.exists():
            raise RuntimeError(f"Kokoro model files missing in {kokoro_dir}. Run scripts/download_models.sh")
        return KokoroTTSService(
            settings=KokoroTTSService.Settings(voice=settings.kokoro_voice),
            model_path=str(model),
            voices_path=str(voices),
        )
    if settings.tts_backend == "fake":
        return FakeTTS()
    raise RuntimeError(f"unknown TTS_BACKEND {settings.tts_backend}")


class FasterWhisperASR(SegmentedSTTService):
    """Consumes VAD segments as 16-bit PCM and emits one TranscriptionFrame per utterance.

    Pipecat's WhisperSTTService is not used. This class calls faster-whisper directly.
    """

    def __init__(self, model, **kwargs):
        super().__init__(**kwargs)
        self._model = model

    @property
    def wants_wav_segments(self) -> bool:
        return False

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame, None]:
        if not audio:
            return
        samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _info = await asyncio.to_thread(
            self._model.transcribe,
            samples,
            language="en",
            vad_filter=False,
        )
        text = " ".join(
            segment.text.strip()
            for segment in segments
            if segment.text.strip() and segment.no_speech_prob < 0.6
        ).strip()
        if text:
            yield TranscriptionFrame(text, "", time_now_iso8601())


class FakeASR(SegmentedSTTService):
    """Emits a fixed transcript for every VAD segment. For tests only."""

    def __init__(self, transcript: str = "hello", **kwargs):
        super().__init__(**kwargs)
        self.transcript = transcript
        self.segments = 0

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame, None]:
        self.segments += 1
        yield TranscriptionFrame(self.transcript, "", time_now_iso8601())


class FakeTTS(TTSService):
    """Emits 100 ms of silence per utterance. For tests only."""

    def __init__(self, **kwargs):
        super().__init__(sample_rate=24000, **kwargs)
        self.spoken: list[str] = []

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
        self.spoken.append(text)
        yield TTSAudioRawFrame(audio=b"\x00\x00" * 2400, sample_rate=24000, num_channels=1, context_id=context_id)

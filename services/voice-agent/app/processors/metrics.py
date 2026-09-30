"""Per-turn latency tracking and pass-through metric taps."""

from __future__ import annotations

import time
from typing import Callable

from pipecat.frames.frames import Frame, TTSAudioRawFrame, VADUserStoppedSpeakingFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


class LatencyTracker:
    """Marks: speech_end -> asr_final -> router -> llm_first_token -> first_text_out -> first_audio."""

    def __init__(self, emit: Callable[[dict], None]):
        self._emit = emit
        self._marks: dict[str, float] = {}
        self._router_ms = 0.0
        self._llm_ttft_ms = 0.0
        self._emitted = True
        self.turns: list[dict] = []

    def speech_end(self) -> None:
        self._marks = {"start": time.perf_counter()}
        self._router_ms = self._llm_ttft_ms = 0.0
        self._emitted = False

    def asr_final(self) -> None:
        if "start" in self._marks and "asr" not in self._marks:
            self._marks["asr"] = time.perf_counter()

    def text_turn_start(self) -> None:
        now = time.perf_counter()
        self._marks = {"start": now, "asr": now}
        self._router_ms = self._llm_ttft_ms = 0.0
        self._emitted = False

    def router(self, ms: float) -> None:
        self._router_ms = ms

    def llm_ttft(self, ms: float) -> None:
        if not self._llm_ttft_ms:
            self._llm_ttft_ms = ms

    def text_out(self, voice: bool) -> None:
        if "text_out" not in self._marks:
            self._marks["text_out"] = time.perf_counter()
        if not voice:
            self._finish(time.perf_counter(), tts_ms=0.0)

    def first_audio(self) -> None:
        if self._emitted or "text_out" not in self._marks:
            return
        now = time.perf_counter()
        self._finish(now, tts_ms=(now - self._marks["text_out"]) * 1000)

    def _finish(self, end: float, tts_ms: float) -> None:
        if self._emitted or "start" not in self._marks:
            return
        self._emitted = True
        start = self._marks["start"]
        sample = {
            "asr_ms": round((self._marks.get("asr", start) - start) * 1000, 1),
            "router_ms": round(self._router_ms, 1),
            "llm_ttft_ms": round(self._llm_ttft_ms, 1),
            "tts_ttfb_ms": round(tts_ms, 1),
            "e2e_ms": round((end - start) * 1000, 1),
        }
        self.turns.append(sample)
        self._emit(sample)

    def summary(self) -> dict:
        if not self.turns:
            return {"turns": 0}
        keys = self.turns[0].keys()
        return {"turns": len(self.turns),
                **{f"avg_{k}": round(sum(t[k] for t in self.turns) / len(self.turns), 1) for k in keys}}


class SpeechEndTap(FrameProcessor):
    """Pass-through. Consumes nothing; marks speech end on VADUserStoppedSpeakingFrame."""

    def __init__(self, tracker: LatencyTracker, **kwargs):
        super().__init__(**kwargs)
        self._tracker = tracker

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, VADUserStoppedSpeakingFrame) and direction is FrameDirection.DOWNSTREAM:
            self._tracker.speech_end()
        await self.push_frame(frame, direction)


class FirstAudioTap(FrameProcessor):
    """Pass-through after TTS. Marks the first TTSAudioRawFrame of each turn."""

    def __init__(self, tracker: LatencyTracker, **kwargs):
        super().__init__(**kwargs)
        self._tracker = tracker

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, TTSAudioRawFrame):
            self._tracker.first_audio()
        await self.push_frame(frame, direction)

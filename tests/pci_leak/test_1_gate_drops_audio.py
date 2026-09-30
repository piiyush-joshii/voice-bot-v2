"""PCI leak test 1: the gate drops user audio in SECURE_CAPTURE, so nothing reaches ASR, router, or LLM."""

import asyncio

from pipecat.frames.frames import (
    Frame,
    InputAudioRawFrame,
    TranscriptionFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineParams
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.tests.utils import run_test
from va_conftest import make_conversation

from app.gate.processor import PaymentGate
from app.gate.state import GateState
from app.pipeline import BrainProcessor
from app.services.speech import FakeASR


class Spy(FrameProcessor):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.audio = 0
        self.transcripts: list[str] = []

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, InputAudioRawFrame):
            self.audio += 1
        if isinstance(frame, TranscriptionFrame):
            self.transcripts.append(frame.text)
        await self.push_frame(frame, direction)


def audio(n=5):
    # A real 16 kHz mono PCM chunk (20 ms of a non-silent pattern).
    chunk = (b"\x10\x27\xf0\xd8" * 160)
    return [InputAudioRawFrame(audio=chunk, sample_rate=16000, num_channels=1) for _ in range(n)]


def utterance():
    return [VADUserStartedSpeakingFrame(), *audio(10), VADUserStoppedSpeakingFrame()]


class CountingRouter:
    def __init__(self):
        self.calls = 0

    def route(self, text, authenticated):
        self.calls += 1
        from app.processors.router import RouteDecision
        return RouteDecision("other", 0.1, "llm", None, 0.1)


async def _run_voice_path(conv, transcript: str):
    """Real frames through gate -> ASR -> brain (router + LLM). State changes happen outside the
    pipeline, exactly as they do in production (tool results, webhook, timer)."""
    spy_in, spy_out = Spy(), Spy()
    asr = FakeASR(transcript=transcript)
    pipeline = Pipeline([PaymentGate(conv.gate), spy_in, asr, spy_out, BrainProcessor(conv)])
    await run_test(pipeline, frames_to_send=[*utterance(), *utterance()],
                   pipeline_params=PipelineParams(audio_in_sample_rate=16000))
    await asyncio.sleep(0.05)
    return spy_in, asr, spy_out


async def test_gate_drops_audio_in_secure_capture_and_resumes_after():
    router = CountingRouter()
    conv = make_conversation(router=router, mode="voice")
    conv.gate.account_id = "ACC1001"
    conv.gate.state = GateState.SECURE_CAPTURE

    spy_in, asr, spy_out = await _run_voice_path(conv, "four one one one one one one one one one one one one one one one")
    assert spy_in.audio == 0, "user audio reached ASR during SECURE_CAPTURE"
    assert asr.segments == 0
    assert spy_out.transcripts == []
    assert router.calls == 0
    assert conv.llm.requests == []
    assert conv.gate.frames_dropped_secure == 24
    assert conv.transcript == []

    conv.gate.state = GateState.PAYMENT_RESULT
    spy_in, asr, spy_out = await _run_voice_path(conv, "what do I owe")
    assert spy_in.audio == 20
    assert asr.segments == 2
    assert spy_out.transcripts == ["what do I owe", "what do I owe"]
    assert router.calls >= 1
    assert conv.gate.frames_dropped_secure == 24


async def test_gate_closed_during_handoff():
    conv = make_conversation(mode="voice")
    conv.gate.state = GateState.HANDOFF
    spy_in, asr, _ = await _run_voice_path(conv, "hello")
    assert spy_in.audio == 0 and asr.segments == 0

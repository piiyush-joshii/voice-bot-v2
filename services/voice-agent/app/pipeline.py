"""Builds the Pipecat voice pipeline:

transport.input -> SileroVAD -> SpeechEndTap -> PaymentGate -> ASR -> TranscriptScrubber
  -> BrainProcessor (router + LLM + tools via Conversation) -> TTS -> FirstAudioTap -> transport.output
"""

from __future__ import annotations

import asyncio

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    InterimTranscriptionFrame,
    InterruptionFrame,
    StartFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
    VADUserStartedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.audio.vad_processor import VADProcessor
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.transports.base_transport import TransportParams
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport

from app.brain.conversation import Conversation
from app.config import Settings
from app.gate.processor import PaymentGate
from app.gate.state import GateState
from app.processors.metrics import FirstAudioTap, SpeechEndTap
from app.processors.scrubber import TranscriptScrubber
from app.services.speech import build_asr, build_tts


class BrainProcessor(FrameProcessor):
    """Consumes final TranscriptionFrames (already scrubbed) and runs a Conversation turn in a task.
    Emits TTSSpeakFrame per sentence of the assistant response. Drops InterimTranscriptionFrames.
    Barge-in: a VADUserStartedSpeakingFrame (>= VAD start_secs of speech) while the bot is speaking
    broadcasts an InterruptionFrame, which clears TTS and the output queue, and cancels the turn."""

    def __init__(self, conversation: Conversation, **kwargs):
        super().__init__(**kwargs)
        self._conv = conversation
        self._bot_speaking = False
        self._turn: asyncio.Task | None = None
        conversation.output = self._on_output

    async def _on_output(self, text: str, final: bool, streamed: bool) -> None:
        if final and streamed:
            return
        await self.push_frame(TTSSpeakFrame(text, append_to_context=False))

    async def _run_turn(self, text: str) -> None:
        try:
            await self._conv.handle_user_text(text, already_scrubbed=True)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            from app.logging_utils import log_event
            log_event("turn_failed", session_id=self._conv.session_id)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, StartFrame) and direction is FrameDirection.DOWNSTREAM:
            self.create_task(self._conv.greet())

        if isinstance(frame, BotStartedSpeakingFrame):
            self._bot_speaking = True
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self._bot_speaking = False

        if isinstance(frame, VADUserStartedSpeakingFrame) and direction is FrameDirection.DOWNSTREAM:
            if self._bot_speaking and self._conv.gate.audio_to_model_open:
                await self.broadcast_interruption()
                self._bot_speaking = False

        if isinstance(frame, InterimTranscriptionFrame):
            return
        if isinstance(frame, TranscriptionFrame):
            if self._conv.gate.state in (GateState.SECURE_CAPTURE,):
                return
            text = frame.text.strip()
            if text:
                if self._turn and not self._turn.done():
                    self._turn.cancel()
                self._turn = asyncio.create_task(self._run_turn(text))
            return

        if isinstance(frame, InterruptionFrame) and self._turn and not self._turn.done():
            self._turn.cancel()

        await self.push_frame(frame, direction)


def build_voice_task(connection: SmallWebRTCConnection, conversation: Conversation, settings: Settings,
                     asr=None, tts=None) -> PipelineTask:
    transport = SmallWebRTCTransport(
        webrtc_connection=connection,
        params=TransportParams(audio_in_enabled=True, audio_out_enabled=True, audio_in_sample_rate=16000),
    )
    vad = VADProcessor(vad_analyzer=SileroVADAnalyzer(params=VADParams(start_secs=0.25, stop_secs=0.6)))

    async def on_drop():
        if conversation.gate.frames_dropped_secure % 50 == 1:
            conversation.emit_gate_status()
            conversation.bus.emit("leak_counters", scrubber_hits=conversation.scrubber_hits,
                                  frames_dropped_secure=conversation.gate.frames_dropped_secure)

    gate = PaymentGate(conversation.gate, on_drop=on_drop)
    scrubber = TranscriptScrubber(on_hit=conversation.note_scrubber_hits)
    brain = BrainProcessor(conversation)
    pipeline = Pipeline([
        transport.input(),
        vad,
        SpeechEndTap(conversation.latency),
        gate,
        asr or build_asr(settings),
        scrubber,
        brain,
        tts or build_tts(settings),
        FirstAudioTap(conversation.latency),
        transport.output(),
    ])
    return PipelineTask(
        pipeline,
        params=PipelineParams(audio_in_sample_rate=16000, audio_out_sample_rate=24000),
        enable_rtvi=False,
        idle_timeout_secs=None,
    )

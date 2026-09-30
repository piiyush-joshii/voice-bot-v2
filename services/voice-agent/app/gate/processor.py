"""PaymentGate Pipecat processor."""

from __future__ import annotations

from pipecat.frames.frames import (
    Frame,
    InputAudioRawFrame,
    InterimTranscriptionFrame,
    TranscriptionFrame,
    UserSpeakingFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from app.gate.state import PaymentGateMachine

USER_SPEECH_FRAMES = (
    InputAudioRawFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    UserSpeakingFrame,
    TranscriptionFrame,
    InterimTranscriptionFrame,
)


class PaymentGate(FrameProcessor):
    """Sits between VAD and ASR.

    Consumes: every frame. While the gate is closed (SECURE_CAPTURE or HANDOFF) it drops user audio
    (InputAudioRawFrame), VAD/user speaking frames, and any transcription frames, counting them in
    `machine.frames_dropped_secure`.
    Emits: all other frames unchanged. If the gate closes mid-utterance it emits one synthetic
    VADUserStoppedSpeakingFrame so the ASR discards its buffered segment state cleanly.
    """

    def __init__(self, machine: PaymentGateMachine, on_drop=None, **kwargs):
        super().__init__(**kwargs)
        self._machine = machine
        self._on_drop = on_drop
        self._user_speaking = False
        self.frames_passed = 0

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if direction is FrameDirection.DOWNSTREAM and isinstance(frame, USER_SPEECH_FRAMES):
            if not self._machine.audio_to_model_open:
                self._machine.frames_dropped_secure += 1
                if self._user_speaking:
                    self._user_speaking = False
                    await self.push_frame(VADUserStoppedSpeakingFrame(), direction)
                if self._on_drop:
                    await self._on_drop()
                return
            if isinstance(frame, VADUserStartedSpeakingFrame):
                self._user_speaking = True
            elif isinstance(frame, VADUserStoppedSpeakingFrame):
                self._user_speaking = False
            self.frames_passed += 1

        await self.push_frame(frame, direction)

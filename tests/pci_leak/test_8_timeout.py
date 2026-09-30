"""PCI leak test 8: no webhook before the capture timeout returns the state to PAYMENT_PENDING and reopens the gate."""

import asyncio

from va_conftest import drive_to_secure_capture, make_conversation

from app.gate.state import GateState


async def test_capture_timeout_reopens_gate():
    conv = make_conversation(capture_timeout_seconds=0.2, capture_timeout_grace_seconds=0.05)
    await drive_to_secure_capture(conv)
    assert conv.gate.state is GateState.SECURE_CAPTURE
    assert not conv.gate.audio_to_model_open

    await asyncio.sleep(0.5)
    assert conv.gate.state is GateState.PAYMENT_PENDING
    assert conv.gate.audio_to_model_open
    assert conv.gate.recording_active
    assert not conv.gate.amount_confirmed
    assert "timed out" in conv.outputs[-1]
    assert any(e["type"] == "payment_result" and e["status"] == "expired" for e in conv.bus.history)

    # The caller can retry with a fresh confirmation.
    await conv.handle_user_text("yes")
    assert conv.gate.state is GateState.SECURE_CAPTURE
    await conv.close()

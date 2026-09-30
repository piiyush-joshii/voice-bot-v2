"""PCI leak test 5: after a full payment dialogue in which the caller also tries to read out the
test card, no PAN, expiry, or CVV appears in logs, debug events, or stored transcripts."""

import json
import re

from va_conftest import make_conversation
from va_fakes import webhook_payload

from app.gate.state import GateState
from app.gate.webhook import PaymentEvent
from app.logging_utils import memory_handler

PAN = "4111111111111111"
PAN_SPACED = "4111 1111 1111 1111"
EXPIRY = "11/29"
CVV = "9731"


def _leaks(blob: str) -> list[str]:
    found = []
    digits_only = re.sub(r"[ -]", "", blob)
    if PAN in digits_only or PAN_SPACED in blob:
        found.append("pan")
    if EXPIRY in blob:
        found.append("expiry")
    if re.search(rf"(?<![\d.]){CVV}(?![\d.])", blob):
        found.append("cvv")
    if re.search(r"four one one one one one", blob):
        found.append("spoken_pan")
    return found


async def run_dialogue(conv):
    await conv.handle_user_text("hi")
    await conv.handle_user_text("My account is ACC1001 and my verifier is 4321")
    await conv.handle_user_text(f"my card is {PAN_SPACED} expiry {EXPIRY} cvv {CVV}")
    await conv.handle_user_text("four one one one one one one one one one one one one one one one")
    await conv.handle_user_text("what's my bill")
    await conv.handle_user_text("I want to pay my bill")
    await conv.handle_user_text("yes")
    assert conv.gate.state is GateState.SECURE_CAPTURE
    # Caller keeps talking while the secure form is open; it must be rejected, not stored.
    assert (await conv.handle_user_text(f"it's {PAN_SPACED}")).rejected
    ok = await conv.handle_payment_event(PaymentEvent(**webhook_payload(conv)))
    assert ok
    await conv.handle_user_text("email me a receipt please")


async def test_no_card_data_in_logs_events_transcripts():
    memory_handler.records.clear()
    conv = make_conversation()
    await run_dialogue(conv)

    assert conv.scrubber_hits >= 2
    blobs = {
        "logs": "\n".join(memory_handler.records),
        "debug_events": json.dumps(list(conv.bus.history)),
        "transcripts": json.dumps(conv.transcript),
        "assistant_output": json.dumps(conv.outputs),
        "llm_history": json.dumps(conv.history),
        "notifications": json.dumps(conv.backend.notifications),
    }
    for name, blob in blobs.items():
        assert _leaks(blob) == [], f"card data found in {name}"
    assert conv.backend.notifications and conv.backend.notifications[0]["payload"]["last4"] == "1111"
    assert set(conv.backend.notifications[0]["payload"]) == {"payment_ref", "amount", "last4", "date"}
    assert "tok_" not in blobs["debug_events"] and "tok_" not in blobs["llm_history"]

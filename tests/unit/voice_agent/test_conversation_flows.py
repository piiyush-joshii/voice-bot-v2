"""Conversation paths with the scripted LLM: OTP, decline/retry, cancel, handoff, fast path, spoken card."""

from pathlib import Path

from va_conftest import drive_to_secure_capture, make_conversation
from va_fakes import webhook_payload

from app.brain import templates as tpl
from app.services.llm import Decision
from app.gate.state import GateState
from app.gate.webhook import PaymentEvent
from app.processors.router import IntentRouter
from app.services.embedder import HashingEmbedder

DATA = Path(__file__).resolve().parents[3] / "services" / "voice-agent" / "data"


def hashing_router():
    return IntentRouter(HashingEmbedder(), DATA / "intents.yaml", DATA / "faq.yaml", high=0.8, faq_threshold=0.6)


async def test_happy_path_and_receipt():
    conv = make_conversation()
    await drive_to_secure_capture(conv)
    assert any(e["type"] == "secure_capture" for e in conv.bus.history)
    assert conv.outputs[-1] == tpl.SECURE_CAPTURE_PROMPT
    await conv.handle_payment_event(PaymentEvent(**webhook_payload(conv)))
    assert conv.gate.state is GateState.PAYMENT_RESULT
    assert conv.backend.payments[0]["token"] == "tok_test"
    assert conv.backend.accounts["ACC1001"]["bill"]["status"] == "paid"
    await conv.handle_user_text("by email please")
    assert conv.backend.notifications[0]["channel"] == "email"
    assert conv.gate.state is GateState.AUTHENTICATED


async def test_otp_fallback():
    conv = make_conversation()
    await conv.handle_user_text("account ACC1001, verifier 9999")
    assert conv.gate.state is GateState.UNAUTHENTICATED
    assert "one-time code" in conv.outputs[-1]
    await conv.handle_user_text("send it by text")
    await conv.handle_user_text("the code is 123456")
    assert conv.gate.state is GateState.AUTHENTICATED


async def test_invented_identity_is_not_grounded():
    conv = make_conversation()
    outcome = await conv.executor.run("verify_identity", {"account_id": "ACC1001", "verifier": "4321"})
    assert outcome.result == {"error": "not_grounded"}
    assert conv.gate.state is GateState.UNAUTHENTICATED


async def test_decline_then_retry():
    conv = make_conversation()
    await drive_to_secure_capture(conv)
    await conv.handle_payment_event(PaymentEvent(**webhook_payload(conv, "failed", "declined", "0002")))
    assert conv.gate.state is GateState.PAYMENT_RESULT
    assert "declined" in conv.outputs[-1]
    await conv.handle_user_text("yes, let me try another card")
    assert conv.gate.state is GateState.PAYMENT_PENDING
    await conv.handle_user_text("yes")
    assert conv.gate.state is GateState.SECURE_CAPTURE


async def test_insufficient_funds_message():
    conv = make_conversation()
    await drive_to_secure_capture(conv)
    await conv.handle_payment_event(PaymentEvent(**webhook_payload(conv, "failed", "insufficient_funds", "9995")))
    assert "insufficient funds" in conv.outputs[-1]


async def test_cancel_in_iframe_returns_to_pending():
    conv = make_conversation()
    await drive_to_secure_capture(conv)
    await conv.handle_payment_event(PaymentEvent(**webhook_payload(conv, "cancelled")))
    assert conv.gate.state is GateState.PAYMENT_PENDING
    assert conv.outputs[-1] == tpl.CAPTURE_CANCELLED
    await conv.handle_user_text("no thanks")
    assert conv.gate.state is GateState.AUTHENTICATED


async def test_spoken_card_is_interrupted_not_sent_to_llm():
    conv = make_conversation()
    await conv.handle_user_text("My account is ACC1001 and my verifier is 4321")
    calls = len(conv.llm.requests)
    await conv.handle_user_text("my card number is 4111 1111 1111 1111")
    assert conv.outputs[-1] == tpl.CARD_DETAILS_INTERRUPT
    assert len(conv.llm.requests) == calls
    assert conv.scrubber_hits == 1


async def test_none_is_not_spoken():
    class PlaceholderLLM:
        async def decide(self, messages, tools, on_reply_delta=None):
            if on_reply_delta:
                await on_reply_delta("none")
            return Decision("reply", reply="none")

    conv = make_conversation(llm=PlaceholderLLM())
    await conv.handle_user_text("My account number is ACC1001")
    assert "I heard account" in conv.outputs[-1]
    assert "A C C 1 0 0 1" in conv.outputs[-1]
    assert all(line.strip().lower() != "none" for line in conv.outputs)

    conv = make_conversation(llm=PlaceholderLLM())
    await conv.handle_user_text("hello there")
    assert conv.outputs[-1] == tpl.FALLBACK


async def test_account_is_read_back_before_verifier():
    conv = make_conversation()
    await conv.handle_user_text("My account number is ACC1001")
    assert conv.gate.state is GateState.UNAUTHENTICATED
    assert conv.outputs[-1] == tpl.heard_account("ACC1001")
    await conv.handle_user_text("yes")
    assert conv.outputs[-1] == tpl.ASK_LAST_FOUR
    await conv.handle_user_text("4321")
    assert conv.gate.state is GateState.AUTHENTICATED
    assert "You're verified" in conv.outputs[-1]

    conv = make_conversation()
    await conv.handle_user_text("ACC 10001")
    assert conv.gate.state is GateState.UNAUTHENTICATED
    assert conv.outputs[-1] == tpl.UNKNOWN_ACCOUNT

    conv = make_conversation()
    await conv.handle_user_text("account ACC1001")
    await conv.handle_user_text("no")
    assert conv.outputs[-1] == tpl.REPEAT_ACCOUNT
    assert conv.pending_account is None


async def test_verified_caller_is_offered_payment():
    conv = make_conversation()
    await conv.handle_user_text("My account is ACC1001 and my verifier is 4321")
    spoken = conv.outputs[-1]
    assert "You're verified" in spoken
    assert "ACC1001" in spoken
    assert "84.50" in spoken
    assert "How would you like to proceed?" in spoken
    await conv.handle_user_text("yes")
    assert conv.gate.state is GateState.PAYMENT_PENDING


async def test_router_fast_path_and_handoff():
    conv = make_conversation(router=hashing_router())
    await conv.handle_user_text("hello")
    assert conv.outputs[-1] == tpl.GREETING
    assert conv.llm.requests == []
    await conv.handle_user_text("My account is ACC1001 and my verifier is 4321")
    await conv.handle_user_text("when is my bill due")
    assert "October 15" in conv.outputs[-1]
    await conv.handle_user_text("I want to talk to a person")
    assert conv.gate.state is GateState.HANDOFF
    assert any(e["type"] == "handoff" for e in conv.bus.history)


async def test_pay_bill_never_fast_pathed():
    conv = make_conversation(router=hashing_router())
    await conv.handle_user_text("My account is ACC1001 and my verifier is 4321")
    before = len(conv.llm.requests)
    await conv.handle_user_text("I want to pay my bill")
    assert len(conv.llm.requests) == before + 1
    assert conv.gate.state is GateState.PAYMENT_PENDING


async def test_nothing_due_account():
    conv = make_conversation()
    await conv.handle_user_text("My account is ACC1002 and my verifier is 1234")
    await conv.handle_user_text("I want to pay my bill")
    assert conv.gate.state is GateState.AUTHENTICATED
    assert "nothing due" in conv.outputs[-1]


async def test_tools_blocked_before_auth():
    conv = make_conversation()
    for tool in ("get_bill", "prepare_payment", "initiate_payment", "send_receipt"):
        assert (await conv.executor.run(tool, {})).result == {"error": "not_available"}

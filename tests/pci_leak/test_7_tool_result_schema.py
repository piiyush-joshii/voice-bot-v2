"""PCI leak test 7: payment tool results contain only allowlisted keys, even if a backend returns extra data."""

from va_conftest import make_conversation

from app.brain.tools import TOOL_RESULTS
from app.gate.state import GateState, PaymentOutcome

PAYMENT_TOOL_KEYS = {
    "prepare_payment": {"bill_id", "amount", "currency", "confirmation_required"},
    "initiate_payment": {"payment_session_id", "status"},
    "get_payment_status": {"status", "payment_ref", "last4"},
    "send_receipt": {"sent"},
}


def test_result_models_are_allowlisted():
    for name, keys in PAYMENT_TOOL_KEYS.items():
        assert set(TOOL_RESULTS[name].model_fields) == keys
        assert TOOL_RESULTS[name].model_config.get("extra") == "forbid"


async def test_payment_tool_results_have_only_allowed_keys():
    conv = make_conversation()
    await conv.handle_user_text("My account is ACC1001 and my verifier is 4321")

    original = conv.executor.payments.create_session

    async def leaky_create_session(*a, **kw):
        session = await original(*a, **kw)
        return {**session, "pan": "4111111111111111", "cvv": "123"}

    conv.executor.payments.create_session = leaky_create_session
    prepared = await conv.executor.run("prepare_payment", {})
    assert set(prepared.result) == PAYMENT_TOOL_KEYS["prepare_payment"]
    conv.gate.confirm_amount()
    initiated = await conv.executor.run("initiate_payment", {})
    assert set(initiated.result) == PAYMENT_TOOL_KEYS["initiate_payment"]
    assert conv.gate.state is GateState.SECURE_CAPTURE

    await conv.gate.payment_completed(PaymentOutcome("succeeded", "PAY-1", "1111", None, 84.5))
    status = await conv.executor.run("get_payment_status", {})
    assert set(status.result) == PAYMENT_TOOL_KEYS["get_payment_status"]


async def test_unexpected_backend_fields_are_rejected():
    conv = make_conversation()
    await conv.handle_user_text("My account is ACC1001 and my verifier is 4321")

    async def leaky_bill(account_id):
        return {"bill_id": "B", "amount_due": 1.0, "currency": "USD", "due_date": "2026-10-15",
                "status": "due", "card_on_file": "4111111111111111"}

    conv.executor.backend.get_bill = leaky_bill
    outcome = await conv.executor.run("get_bill", {})
    assert outcome.result == {"error": "service_unavailable"}

"""PCI leak test 3: bad signature, stale timestamp, unknown session, and replays are rejected."""

import time

import pytest
from fastapi.testclient import TestClient
from va_conftest import drive_to_secure_capture
from va_fakes import SECRET, FakeBackend, FakePayments, ScriptedLLM, signed_webhook, webhook_payload

from app.gate.state import GateState
from app.gate.webhook import WebhookError, WebhookVerifier


def test_verifier_rules():
    v = WebhookVerifier(SECRET)
    payload = {"payment_session_id": "ps_1", "status": "succeeded", "account_id": "ACC1001",
               "bill_id": "B", "amount": 1.0}
    body, h = signed_webhook(payload)
    with pytest.raises(WebhookError) as e:
        v.verify(body, "00" * 32, h["X-Timestamp"])
    assert e.value.status_code == 401
    with pytest.raises(WebhookError):
        v.verify(body, h["X-Signature"], str(int(time.time()) - 301))
    bad_body, bad_h = signed_webhook(payload, secret=b"wrong")
    with pytest.raises(WebhookError):
        v.verify(bad_body, bad_h["X-Signature"], bad_h["X-Timestamp"])
    v.verify(body, h["X-Signature"], h["X-Timestamp"])
    with pytest.raises(WebhookError) as e:
        v.verify(body, h["X-Signature"], h["X-Timestamp"])
    assert e.value.status_code == 409


@pytest.fixture
def client_and_session():
    from app.main import create_app
    from app.sessions import Runtime, SessionRegistry
    from app.config import Settings

    app = create_app()
    app.state.registry = SessionRegistry(Runtime(Settings(), FakeBackend(), FakePayments(), ScriptedLLM(), None))
    app.state.webhook_verifier = WebhookVerifier(SECRET)
    app.state.voice_available = False
    app.state.voice_error = "disabled in tests"
    session = app.state.registry.create("text")
    yield TestClient(app), session


async def _to_capture(session):
    await drive_to_secure_capture(session.conversation)
    assert session.conversation.gate.state is GateState.SECURE_CAPTURE


def test_webhook_endpoint_rejections(client_and_session):
    import asyncio

    client, session = client_and_session
    conv = session.conversation
    asyncio.run(_to_capture(session))
    payload = webhook_payload(conv)

    body, h = signed_webhook(payload, secret=b"not-the-secret")
    assert client.post("/internal/payment-events", content=body, headers=h).status_code == 401
    assert conv.gate.state is GateState.SECURE_CAPTURE

    body, h = signed_webhook(payload, ts=int(time.time()) - 600)
    assert client.post("/internal/payment-events", content=body, headers=h).status_code == 401
    assert conv.gate.state is GateState.SECURE_CAPTURE

    unknown = {**payload, "payment_session_id": "ps_unknown"}
    body, h = signed_webhook(unknown)
    assert client.post("/internal/payment-events", content=body, headers=h).status_code == 409
    assert conv.gate.state is GateState.SECURE_CAPTURE

    body, h = signed_webhook(payload)
    r = client.post("/internal/payment-events", content=body, headers=h)
    assert r.status_code == 200, r.text
    assert conv.gate.state is GateState.PAYMENT_RESULT

    r = client.post("/internal/payment-events", content=body, headers=h)
    assert r.status_code == 409
    assert conv.gate.state is GateState.PAYMENT_RESULT

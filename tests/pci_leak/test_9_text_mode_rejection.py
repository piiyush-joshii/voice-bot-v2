"""PCI leak test 9: text messages sent during SECURE_CAPTURE are rejected server-side (over the real WebSocket)."""

from fastapi.testclient import TestClient
from va_fakes import SECRET, FakeBackend, FakePayments, ScriptedLLM

from app.config import Settings
from app.gate.state import GateState
from app.gate.webhook import WebhookVerifier
from app.main import create_app
from app.sessions import Runtime, SessionRegistry


def _app():
    app = create_app()
    app.state.registry = SessionRegistry(Runtime(Settings(), FakeBackend(), FakePayments(), ScriptedLLM(), None))
    app.state.webhook_verifier = WebhookVerifier(SECRET)
    app.state.voice_available = False
    app.state.voice_error = "disabled in tests"
    return app


def _until_final(ws):
    msgs = []
    while True:
        m = ws.receive_json()
        msgs.append(m)
        if m.get("final") or m["type"] == "rejected":
            return msgs


def test_text_rejected_during_secure_capture():
    app = _app()
    client = TestClient(app)
    sid = client.post("/sessions", json={"mode": "text"}).json()["session_id"]
    conv = app.state.registry.get(sid).conversation
    with client.websocket_connect(f"/ws/text/{sid}") as ws:
        _until_final(ws)  # opening line from the payment voice bot
        for text in ("My account is ACC1001 and my verifier is 4321", "I want to pay my bill"):
            ws.send_json({"type": "user_text", "text": text})
            _until_final(ws)
        ws.send_json({"type": "user_text", "text": "yes"})
        _until_final(ws)
        assert conv.gate.state is GateState.SECURE_CAPTURE
        stored = len(conv.transcript)
        llm_calls = len(conv.llm.requests)

        ws.send_json({"type": "user_text", "text": "my card is 4111 1111 1111 1111"})
        assert ws.receive_json() == {"type": "rejected", "reason": "secure_capture_active"}
        assert len(conv.transcript) == stored
        assert len(conv.llm.requests) == llm_calls
        assert conv.gate.state is GateState.SECURE_CAPTURE

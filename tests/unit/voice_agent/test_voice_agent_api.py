"""voice-agent contract tests (docs/API_SPEC.md section 3)."""

import pytest
from fastapi.testclient import TestClient
from va_fakes import SECRET, FakeBackend, FakePayments, ScriptedLLM

from app.config import Settings
from app.gate.webhook import WebhookVerifier
from app.main import create_app
from app.sessions import Runtime, SessionRegistry


@pytest.fixture
def client():
    app = create_app()
    app.state.registry = SessionRegistry(Runtime(Settings(), FakeBackend(), FakePayments(), ScriptedLLM(), None))
    app.state.webhook_verifier = WebhookVerifier(SECRET)
    app.state.voice_available = False
    app.state.voice_error = "voice disabled in tests"
    return TestClient(app)


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_create_text_session_and_get(client):
    body = client.post("/sessions", json={"mode": "text"}).json()
    assert set(body) == {"session_id", "ws_debug_url", "ws_text_url"}
    assert body["ws_text_url"].startswith("ws://localhost:7860/ws/text/")
    info = client.get(f"/sessions/{body['session_id']}").json()
    assert info["state"] == "UNAUTHENTICATED" and "metrics_summary" in info and "created_at" in info


def test_voice_session_unavailable_is_503(client):
    assert client.post("/sessions", json={"mode": "voice"}).status_code == 503


def test_unknown_session(client):
    assert client.get("/sessions/nope").status_code == 404


def test_manual_handoff(client):
    sid = client.post("/sessions", json={"mode": "text"}).json()["session_id"]
    body = client.post(f"/sessions/{sid}/handoff").json()
    assert body["handoff_id"].startswith("HO-") and "Account" in body["summary"]
    assert client.get(f"/sessions/{sid}").json()["state"] == "HANDOFF"


def test_debug_ws_streams_events(client):
    sid = client.post("/sessions", json={"mode": "text"}).json()["session_id"]
    with client.websocket_connect(f"/ws/debug/{sid}") as dbg, client.websocket_connect(f"/ws/text/{sid}") as ws:
        first = dbg.receive_json()
        assert first["type"] == "state_changed" and first["to"] == "UNAUTHENTICATED"
        assert dbg.receive_json()["type"] == "gate_status"
        ws.send_json({"type": "user_text", "text": "My account is ACC1001 and my verifier is 4321"})
        seen = set()
        while "state_changed" not in seen or "tool_result" not in seen:
            seen.add(dbg.receive_json()["type"])
        assert {"transcript", "tool_call", "tool_result", "state_changed"} <= seen


def test_cors_allows_only_console(client):
    ok = client.options("/sessions", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    bad = client.options("/sessions", headers={"Origin": "http://evil.test", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in bad.headers

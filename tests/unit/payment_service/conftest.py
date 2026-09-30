import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services" / "payment-service"))
os.environ["WEBHOOK_HMAC_SECRET"] = "test-secret"


@pytest.fixture
def app_and_hooks(monkeypatch):
    from fastapi.testclient import TestClient

    from app import webhook
    from app.main import app
    from app.sessions import store

    store.clear()
    delivered = []

    async def fake_deliver(session, attempts=3):
        if session.webhook_sent:
            return True
        session.webhook_sent = True
        body, headers = webhook.build_request(session)
        delivered.append((body, headers))
        return True

    monkeypatch.setattr(webhook, "deliver", fake_deliver)
    return TestClient(app), delivered

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services" / "backend-api"))


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTBOX_PATH", str(tmp_path / "outbox.jsonl"))
    from fastapi.testclient import TestClient

    from app import mock_data
    from app.main import app

    mock_data.reset_store()
    return TestClient(app)

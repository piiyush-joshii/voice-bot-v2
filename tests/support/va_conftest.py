"""Shared pytest setup for voice-agent test packages (imported by their conftest.py)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "voice-agent"))
sys.path.insert(0, str(Path(__file__).parent))

os.environ["WEBHOOK_HMAC_SECRET"] = "test-secret"
os.environ["CAPTURE_TIMEOUT_SECONDS"] = "120"
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import pytest  # noqa: E402

from app.brain.conversation import Conversation  # noqa: E402
from app.config import Settings  # noqa: E402
from app.logging_utils import configure_logging  # noqa: E402

configure_logging()


def make_conversation(llm=None, router=None, mode="text", **settings_overrides):
    from va_fakes import FakeBackend, FakePayments, ScriptedLLM

    settings = Settings()
    for k, v in settings_overrides.items():
        setattr(settings, k, v)
    conv = Conversation(session_id="s_test", mode=mode, settings=settings, backend=FakeBackend(),
                        payments=FakePayments(), llm=llm or ScriptedLLM(), router=router)
    outputs: list[str] = []

    async def sink(text, final, streamed):
        if not (final and streamed):
            outputs.append(text)

    conv.output = sink
    conv.outputs = outputs  # type: ignore[attr-defined]
    return conv


async def drive_to_secure_capture(conv):
    await conv.handle_user_text("My account is ACC1001 and my verifier is 4321")
    await conv.handle_user_text("I want to pay my bill")
    await conv.handle_user_text("yes please")


@pytest.fixture
def conversation():
    return make_conversation()

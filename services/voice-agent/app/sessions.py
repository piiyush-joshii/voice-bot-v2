"""Session registry and the shared runtime (clients, LLM, router) used to build conversations."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from app.brain.conversation import Conversation
from app.clients import BackendClient, PaymentClient
from app.config import Settings
from app.processors.router import IntentRouter
from app.services.llm import LLMService


@dataclass
class Runtime:
    settings: Settings
    backend: BackendClient
    payments: PaymentClient
    llm: LLMService
    router: IntentRouter | None
    asr_factory: Callable[[], Any] | None = None
    tts_factory: Callable[[], Any] | None = None


@dataclass
class Session:
    session_id: str
    mode: str
    conversation: Conversation
    created_at: float = field(default_factory=time.time)
    voice_task: Any = None
    pc_id: str | None = None


class SessionRegistry:
    def __init__(self, runtime: Runtime):
        self.runtime = runtime
        self._sessions: dict[str, Session] = {}

    def create(self, mode: str) -> Session:
        sid = "s_" + secrets.token_urlsafe(10)
        rt = self.runtime
        conv = Conversation(session_id=sid, mode=mode, settings=rt.settings, backend=rt.backend,
                            payments=rt.payments, llm=rt.llm, router=rt.router)
        session = Session(sid, mode, conv)
        self._sessions[sid] = session
        return session

    def get(self, sid: str) -> Session | None:
        return self._sessions.get(sid)

    def by_payment_session(self, payment_session_id: str) -> Session | None:
        for s in self._sessions.values():
            cap = s.conversation.gate.capture
            if cap and cap.payment_session_id == payment_session_id:
                return s
        return None

    def all(self) -> list[Session]:
        return list(self._sessions.values())

"""In-memory payment sessions. Sessions hold only outcome data (ref, token, last4), never card fields."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

TERMINAL = {"succeeded", "failed", "cancelled", "expired"}


@dataclass
class PaymentSession:
    payment_session_id: str
    account_id: str
    bill_id: str
    amount: float
    currency: str
    callback_url: str
    allowed_frame_origin: str
    created_at: float
    expires_at: float
    status: str = "created"
    attempts: int = 0
    payment_ref: str | None = None
    token: str | None = None
    last4: str | None = None
    failure_code: str | None = None
    webhook_sent: bool = False

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL

    def status_view(self) -> dict:
        return {
            "status": self.status,
            "payment_ref": self.payment_ref,
            "token": self.token,
            "last4": self.last4,
            "failure_code": self.failure_code,
        }

    def webhook_payload(self) -> dict:
        return {
            "payment_session_id": self.payment_session_id,
            "status": self.status,
            "payment_ref": self.payment_ref,
            "token": self.token,
            "last4": self.last4,
            "failure_code": self.failure_code,
            "account_id": self.account_id,
            "bill_id": self.bill_id,
            "amount": self.amount,
        }


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, PaymentSession] = {}

    def create(self, *, ttl: float, **fields) -> PaymentSession:
        now = time.time()
        sid = "ps_" + secrets.token_urlsafe(16)
        session = PaymentSession(payment_session_id=sid, created_at=now, expires_at=now + ttl, **fields)
        self._sessions[sid] = session
        return session

    def get(self, sid: str) -> PaymentSession | None:
        return self._sessions.get(sid)

    def due_for_expiry(self, now: float | None = None) -> list[PaymentSession]:
        now = now or time.time()
        return [s for s in self._sessions.values() if not s.terminal and now >= s.expires_at]

    def clear(self) -> None:
        self._sessions.clear()


store = SessionStore()

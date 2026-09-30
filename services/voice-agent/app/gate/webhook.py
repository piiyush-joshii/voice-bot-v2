"""Verification for signed payment-service webhooks: HMAC-SHA256, timestamp window, replay set."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError


class PaymentEvent(BaseModel):
    payment_session_id: str
    status: str
    payment_ref: str | None = None
    token: str | None = None
    last4: str | None = None
    failure_code: str | None = None
    account_id: str
    bill_id: str
    amount: float


@dataclass
class WebhookError(Exception):
    status_code: int
    reason: str


class WebhookVerifier:
    TERMINAL = {"succeeded", "failed", "cancelled", "expired"}

    def __init__(self, secret: bytes, max_age_seconds: int = 300):
        self._secret = secret
        self._max_age = max_age_seconds
        self._seen: set[tuple[str, str]] = set()

    def sign(self, raw_body: bytes) -> str:
        return hmac.new(self._secret, raw_body, hashlib.sha256).hexdigest()

    def verify(self, raw_body: bytes, signature: str | None, timestamp: str | None,
               now: float | None = None) -> PaymentEvent:
        if not signature or not hmac.compare_digest(self.sign(raw_body), signature.strip().lower()):
            raise WebhookError(401, "bad_signature")
        try:
            ts = int(timestamp or "")
        except ValueError:
            raise WebhookError(401, "bad_timestamp") from None
        now = now if now is not None else time.time()
        if abs(now - ts) > self._max_age:
            raise WebhookError(401, "stale_timestamp")
        try:
            event = PaymentEvent.model_validate(json.loads(raw_body))
        except (ValueError, ValidationError):
            raise WebhookError(401, "bad_payload") from None
        if event.status not in self.TERMINAL:
            raise WebhookError(409, "non_terminal_status")
        key = (event.payment_session_id, event.status)
        if key in self._seen:
            raise WebhookError(409, "replayed")
        self._seen.add(key)
        return event

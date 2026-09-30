"""Signed webhook delivery to the callback URL registered with the session."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time

import httpx

from app.config import settings
from app.sessions import PaymentSession

log = logging.getLogger("payment.webhook")


def sign(secret: bytes, raw_body: bytes) -> str:
    return hmac.new(secret, raw_body, hashlib.sha256).hexdigest()


def build_request(session: PaymentSession) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(session.webhook_payload(), separators=(",", ":"), sort_keys=True).encode()
    headers = {
        "Content-Type": "application/json",
        "X-Signature": sign(settings.webhook_secret, body),
        "X-Timestamp": str(int(time.time())),
    }
    return body, headers


async def deliver(session: PaymentSession, attempts: int = 3) -> bool:
    if session.webhook_sent:
        return True
    session.webhook_sent = True
    body, headers = build_request(session)
    async with httpx.AsyncClient(timeout=5.0) as client:
        for attempt in range(1, attempts + 1):
            try:
                resp = await client.post(session.callback_url, content=body, headers=headers)
                log.info(
                    "webhook_delivered",
                    extra={"payment_session_id": session.payment_session_id, "status": session.status,
                           "http_status": resp.status_code},
                )
                if resp.status_code < 500:
                    return resp.status_code < 300
            except httpx.HTTPError:
                log.warning("webhook_failed", extra={"payment_session_id": session.payment_session_id,
                                                     "attempt": attempt})
            await asyncio.sleep(0.5 * attempt)
    return False

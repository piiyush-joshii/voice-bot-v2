"""HTTP clients for backend-api and payment-service. Tests swap these for in-memory fakes."""

from __future__ import annotations

from typing import Protocol

import httpx


class ClientError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class BackendClient(Protocol):
    async def verify(self, account_id: str, verifier: str) -> dict: ...
    async def send_otp(self, account_id: str, channel: str) -> dict: ...
    async def verify_otp(self, account_id: str, code: str) -> dict: ...
    async def get_bill(self, account_id: str) -> dict: ...
    async def get_history(self, account_id: str, limit: int) -> list[dict]: ...
    async def record_payment(self, record: dict) -> dict: ...
    async def send_notification(self, account_id: str, channel: str, template: str, payload: dict) -> dict: ...


class PaymentClient(Protocol):
    async def create_session(self, account_id: str, bill_id: str, amount: float, currency: str,
                             callback_url: str, allowed_frame_origin: str) -> dict: ...
    async def get_status(self, payment_session_id: str) -> dict: ...


async def _json(resp: httpx.Response):
    if resp.status_code == 404:
        raise ClientError("not_found")
    if resp.status_code >= 400:
        try:
            raise ClientError(resp.json()["error"]["code"])
        except (ValueError, KeyError, TypeError):
            raise ClientError(f"http_{resp.status_code}") from None
    return resp.json()


class HttpBackendClient:
    def __init__(self, base_url: str):
        self._client = httpx.AsyncClient(base_url=base_url, timeout=5.0)

    async def verify(self, account_id: str, verifier: str) -> dict:
        return await _json(await self._client.post("/auth/verify", json={"account_id": account_id, "verifier": verifier}))

    async def send_otp(self, account_id: str, channel: str) -> dict:
        return await _json(await self._client.post("/auth/otp/send", json={"account_id": account_id, "channel": channel}))

    async def verify_otp(self, account_id: str, code: str) -> dict:
        return await _json(await self._client.post("/auth/otp/verify", json={"account_id": account_id, "code": code}))

    async def get_bill(self, account_id: str) -> dict:
        return await _json(await self._client.get(f"/bills/{account_id}"))

    async def get_history(self, account_id: str, limit: int) -> list[dict]:
        return await _json(await self._client.get(f"/bills/{account_id}/history", params={"limit": limit}))

    async def record_payment(self, record: dict) -> dict:
        return await _json(await self._client.post("/payments/record", json=record))

    async def send_notification(self, account_id: str, channel: str, template: str, payload: dict) -> dict:
        body = {"account_id": account_id, "channel": channel, "template": template, "payload": payload}
        return await _json(await self._client.post("/notifications/send", json=body))


class HttpPaymentClient:
    def __init__(self, base_url: str):
        self._client = httpx.AsyncClient(base_url=base_url, timeout=5.0)

    async def create_session(self, account_id: str, bill_id: str, amount: float, currency: str,
                             callback_url: str, allowed_frame_origin: str) -> dict:
        body = {"account_id": account_id, "bill_id": bill_id, "amount": amount, "currency": currency,
                "callback_url": callback_url, "allowed_frame_origin": allowed_frame_origin}
        return await _json(await self._client.post("/payment-sessions", json=body))

    async def get_status(self, payment_session_id: str) -> dict:
        return await _json(await self._client.get(f"/payment-sessions/{payment_session_id}/status"))

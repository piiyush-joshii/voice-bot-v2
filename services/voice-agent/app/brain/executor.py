"""Tool executor.

Enforces the per-state allowlist (a tool not allowed in the current state returns
{"error": "not_available"} and never runs), validates arguments, checks that identity values were
actually spoken by the caller (not invented by the model), binds tools to the verified account,
and validates every result against its fixed schema before it can enter the LLM context.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import date
from typing import Awaitable, Callable

from pydantic import ValidationError

from app.brain import tools as T
from app.clients import BackendClient, ClientError, PaymentClient
from app.gate.state import CaptureInfo, GateState, PaymentGateMachine, PreparedPayment
from app.logging_utils import log_event


@dataclass
class ToolOutcome:
    name: str
    args: dict
    result: dict

    @property
    def ok(self) -> bool:
        return "error" not in self.result


class ToolExecutor:
    def __init__(
        self,
        *,
        session_id: str,
        gate: PaymentGateMachine,
        backend: BackendClient,
        payments: PaymentClient,
        callback_url: str,
        frame_origin: str,
        recent_user_texts: Callable[[], list[str]],
        on_secure_capture: Callable[[CaptureInfo], Awaitable[None]],
        on_handoff: Callable[[str, str], Awaitable[None]],
    ):
        self.session_id = session_id
        self.gate = gate
        self.backend = backend
        self.payments = payments
        self.callback_url = callback_url
        self.frame_origin = frame_origin
        self._recent_user_texts = recent_user_texts
        self._on_secure_capture = on_secure_capture
        self._on_handoff = on_handoff
        self.claimed_account: str | None = None
        self.calls: list[ToolOutcome] = []

    async def run(self, name: str, raw_args: dict | None) -> ToolOutcome:
        raw_args = raw_args if isinstance(raw_args, dict) else {}
        if name not in self.gate.allowed_tools() or name not in T.TOOL_ARGS:
            return self._finish(name, raw_args, {"error": "not_available"})
        try:
            args = T.TOOL_ARGS[name].model_validate(raw_args)
        except ValidationError:
            return self._finish(name, raw_args, {"error": "invalid_args"})
        handler = getattr(self, f"_tool_{name}")
        try:
            result = await handler(args)
        except ClientError as e:
            result = {"error": "not_found" if e.code in ("not_found", "account_not_found") else "service_unavailable"}
        except Exception:  # noqa: BLE001 - backend outages must not crash the turn
            result = {"error": "service_unavailable"}
        return self._finish(name, args.model_dump(), result)

    def _finish(self, name: str, args: dict, result: dict) -> ToolOutcome:
        model = T.ErrorResult if "error" in result else T.TOOL_RESULTS[name]
        try:
            clean = model.model_validate(result).model_dump()
        except ValidationError:
            clean = {"error": "service_unavailable"}
        outcome = ToolOutcome(name, args, clean)
        self.calls.append(outcome)
        log_event("tool_executed", session_id=self.session_id, tool_name=name,
                  status="ok" if outcome.ok else clean["error"], state=self.gate.state.value)
        return outcome

    def _spoken_digits(self) -> str:
        return " ".join(T.normalize_digits(t) or "" for t in self._recent_user_texts())

    def _grounded(self, *values: str) -> bool:
        spoken = self._spoken_digits()
        return all(v and T.normalize_digits(v) and T.normalize_digits(v) in spoken for v in values)

    def _bound_account(self, requested: str | None) -> str | dict:
        account = self.gate.account_id
        if account is None:
            return {"error": "not_available"}
        if requested and requested != account:
            return {"error": "account_mismatch"}
        return account

    async def _tool_verify_identity(self, a: T.VerifyIdentityArgs) -> dict:
        if not self._grounded(a.account_id[3:], a.verifier):
            return {"error": "not_grounded"}
        self.claimed_account = a.account_id
        res = await self.backend.verify(a.account_id, a.verifier)
        if res.get("verified"):
            await self.gate.authenticated(a.account_id)
        return {"verified": bool(res.get("verified")), "needs_otp": bool(res.get("needs_otp"))}

    async def _tool_send_otp(self, a: T.SendOtpArgs) -> dict:
        if not self._grounded(a.account_id[3:]) and a.account_id != self.claimed_account:
            return {"error": "not_grounded"}
        self.claimed_account = a.account_id
        res = await self.backend.send_otp(a.account_id, a.channel)
        return {"sent": bool(res.get("sent"))}

    async def _tool_verify_otp(self, a: T.VerifyOtpArgs) -> dict:
        if not self._grounded(a.code):
            return {"error": "not_grounded"}
        if self.claimed_account and a.account_id != self.claimed_account:
            return {"error": "account_mismatch"}
        res = await self.backend.verify_otp(a.account_id, a.code)
        if res.get("verified"):
            await self.gate.authenticated(a.account_id)
        return {"verified": bool(res.get("verified"))}

    async def _tool_get_bill(self, a: T.AccountArgs) -> dict:
        account = self._bound_account(a.account_id)
        if isinstance(account, dict):
            return account
        return await self.backend.get_bill(account)

    async def _tool_get_bill_history(self, a: T.HistoryArgs) -> dict:
        account = self._bound_account(a.account_id)
        if isinstance(account, dict):
            return account
        return {"items": await self.backend.get_history(account, a.limit)}

    async def _tool_prepare_payment(self, a: T.PreparePaymentArgs) -> dict:
        account = self._bound_account(a.account_id)
        if isinstance(account, dict):
            return account
        bill = await self.backend.get_bill(account)
        due = float(bill["amount_due"])
        if due <= 0:
            return {"error": "nothing_due"}
        amount = round(a.amount if a.amount is not None else due, 2)
        if amount > due:
            return {"error": "amount_exceeds_balance"}
        await self.gate.payment_prepared(PreparedPayment(account, bill["bill_id"], amount, bill["currency"]))
        return {"bill_id": bill["bill_id"], "amount": amount, "currency": bill["currency"],
                "confirmation_required": True}

    async def _tool_initiate_payment(self, a: T.InitiatePaymentArgs) -> dict:
        prepared = self.gate.prepared
        if prepared is None:
            return {"error": "not_confirmed"}
        if not self.gate.amount_confirmed:
            return {"error": "not_confirmed"}
        if (a.account_id and a.account_id != prepared.account_id) or \
           (a.amount is not None and abs(a.amount - prepared.amount) > 0.005):
            return {"error": "amount_mismatch"}
        session = await self.payments.create_session(
            prepared.account_id, prepared.bill_id, prepared.amount, prepared.currency,
            self.callback_url, self.frame_origin,
        )
        capture = CaptureInfo(session["payment_session_id"], session["capture_url"], session["expires_at"])
        await self.gate.enter_secure_capture(capture)
        await self._on_secure_capture(capture)
        return {"payment_session_id": capture.payment_session_id, "status": "secure_capture_started"}

    async def _tool_get_payment_status(self, a: T.PaymentStatusArgs) -> dict:
        outcome = self.gate.last_outcome
        if outcome is None:
            return {"error": "no_payment"}
        return {"status": outcome.status, "payment_ref": outcome.payment_ref, "last4": outcome.last4}

    async def _tool_send_receipt(self, a: T.SendReceiptArgs) -> dict:
        account = self._bound_account(a.account_id)
        if isinstance(account, dict):
            return account
        outcome = self.gate.last_outcome
        if outcome is None or outcome.status != "succeeded":
            return {"error": "no_payment"}
        payload = {"payment_ref": outcome.payment_ref, "amount": outcome.amount, "last4": outcome.last4,
                   "date": date.today().isoformat()}
        res = await self.backend.send_notification(account, a.channel, "receipt", payload)
        return {"sent": bool(res.get("sent"))}

    async def _tool_request_agent_handoff(self, a: T.HandoffArgs) -> dict:
        handoff_id = "HO-" + secrets.token_hex(3).upper()
        await self._on_handoff(handoff_id, a.reason)
        return {"handoff_id": handoff_id}

    def state_is(self, *states: GateState) -> bool:
        return self.gate.state in states

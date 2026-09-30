"""LLM-facing tool definitions: argument schemas, fixed result schemas, and descriptions.

Result models use extra="forbid" and contain only IDs, amounts, dates, and status, so nothing
free-form from an external system can reach the prompt.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.processors.scrubber import words_to_digits


def normalize_account_id(value: str | None) -> str | None:
    if value is None:
        return None
    raw = words_to_digits(str(value)).upper()
    compact = re.sub(r"[^A-Z0-9]", "", raw)
    compact = re.sub(r"^(HCC|AHC|ACH)", "ACC", compact)
    if re.fullmatch(r"\d{4}", compact):
        compact = "ACC" + compact
    m = re.fullmatch(r"(?:ACC|ACCOUNT|AC|ACCT)?(\d{4})", compact)
    return f"ACC{m.group(1)}" if m else compact


def normalize_digits(value: str | None) -> str | None:
    if value is None:
        return None
    return re.sub(r"\D", "", words_to_digits(str(value)))


class Args(BaseModel):
    model_config = ConfigDict(extra="ignore")


class AccountArgs(Args):
    account_id: str | None = None

    @field_validator("account_id", mode="before")
    @classmethod
    def _acct(cls, v):
        return normalize_account_id(v) if v not in (None, "") else None


class VerifyIdentityArgs(Args):
    account_id: str = Field(pattern=r"^ACC\d{4}$")
    verifier: str = Field(pattern=r"^\d{4}$")

    @field_validator("account_id", mode="before")
    @classmethod
    def _acct(cls, v):
        return normalize_account_id(v)
    @field_validator("verifier", mode="before")
    @classmethod
    def _ver(cls, v):
        return normalize_digits(v)


class SendOtpArgs(Args):
    account_id: str = Field(pattern=r"^ACC\d{4}$")
    channel: Literal["sms", "email"] = "sms"

    @field_validator("account_id", mode="before")
    @classmethod
    def _acct(cls, v):
        return normalize_account_id(v)

    @field_validator("channel", mode="before")
    @classmethod
    def _chan(cls, v):
        v = str(v or "sms").lower()
        return "sms" if v in ("text", "phone", "sms") else ("email" if "mail" in v else v)


class VerifyOtpArgs(Args):
    account_id: str = Field(pattern=r"^ACC\d{4}$")
    code: str = Field(pattern=r"^\d{6}$")

    @field_validator("account_id", mode="before")
    @classmethod
    def _acct(cls, v):
        return normalize_account_id(v)
    @field_validator("code", mode="before")
    @classmethod
    def _code(cls, v):
        return normalize_digits(v)


class HistoryArgs(AccountArgs):
    limit: int = Field(default=3, ge=1, le=12)

    @field_validator("limit", mode="before")
    @classmethod
    def _limit(cls, v):
        try:
            return max(1, min(12, int(v)))
        except (TypeError, ValueError):
            return 3


class PreparePaymentArgs(AccountArgs):
    bill_id: str | None = None
    amount: float | None = Field(default=None, gt=0)

    @field_validator("amount", mode="before")
    @classmethod
    def _amount(cls, v):
        if v in (None, "", 0, "0"):
            return None
        try:
            return round(float(str(v).replace("$", "").replace(",", "")), 2)
        except ValueError:
            return None


class InitiatePaymentArgs(PreparePaymentArgs):
    pass


class PaymentStatusArgs(Args):
    payment_ref: str | None = None


class SendReceiptArgs(AccountArgs):
    payment_ref: str | None = None
    channel: Literal["sms", "email"] = "email"

    @field_validator("channel", mode="before")
    @classmethod
    def _chan(cls, v):
        v = str(v or "email").lower()
        return "sms" if v in ("text", "phone", "sms") else "email"


class HandoffArgs(Args):
    reason: str = Field(default="caller_request", max_length=200)


class Result(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorResult(Result):
    error: Literal[
        "not_available", "invalid_args", "not_grounded", "account_mismatch", "not_found",
        "nothing_due", "amount_exceeds_balance", "amount_mismatch", "not_confirmed",
        "service_unavailable", "no_payment",
    ]


class VerifyResult(Result):
    verified: bool
    needs_otp: bool


class OtpSentResult(Result):
    sent: bool


class OtpVerifyResult(Result):
    verified: bool


class BillResult(Result):
    bill_id: str
    amount_due: float
    currency: str
    due_date: str
    status: str


class HistoryItem(Result):
    bill_id: str
    period: str
    amount: float
    paid: bool


class HistoryResult(Result):
    items: list[HistoryItem]


class PreparePaymentResult(Result):
    bill_id: str
    amount: float
    currency: str
    confirmation_required: bool = True


class InitiatePaymentResult(Result):
    payment_session_id: str
    status: Literal["secure_capture_started"]


class PaymentStatusResult(Result):
    status: str
    payment_ref: str | None
    last4: str | None


class ReceiptResult(Result):
    sent: bool


class HandoffResult(Result):
    handoff_id: str


TOOL_ARGS: dict[str, type[Args]] = {
    "verify_identity": VerifyIdentityArgs,
    "send_otp": SendOtpArgs,
    "verify_otp": VerifyOtpArgs,
    "get_bill": AccountArgs,
    "get_bill_history": HistoryArgs,
    "prepare_payment": PreparePaymentArgs,
    "initiate_payment": InitiatePaymentArgs,
    "get_payment_status": PaymentStatusArgs,
    "send_receipt": SendReceiptArgs,
    "request_agent_handoff": HandoffArgs,
}

TOOL_RESULTS: dict[str, type[Result]] = {
    "verify_identity": VerifyResult,
    "send_otp": OtpSentResult,
    "verify_otp": OtpVerifyResult,
    "get_bill": BillResult,
    "get_bill_history": HistoryResult,
    "prepare_payment": PreparePaymentResult,
    "initiate_payment": InitiatePaymentResult,
    "get_payment_status": PaymentStatusResult,
    "send_receipt": ReceiptResult,
    "request_agent_handoff": HandoffResult,
}

TOOL_DESCRIPTIONS: dict[str, str] = {
    "verify_identity": "verify_identity(account_id, verifier): verify the caller. Both values must come from the caller. verifier is the last 4 digits of their registered phone.",
    "send_otp": "send_otp(account_id, channel): send a one-time code by 'sms' or 'email' when the verifier failed.",
    "verify_otp": "verify_otp(account_id, code): check the 6-digit one-time code the caller read out.",
    "get_bill": "get_bill(account_id): current bill amount, due date, status.",
    "get_bill_history": "get_bill_history(account_id, limit): recent past bills.",
    "prepare_payment": "prepare_payment(account_id, bill_id, amount): when the caller wants to pay. amount is optional (defaults to the full amount due). Asks the caller to confirm.",
    "initiate_payment": "initiate_payment(account_id, bill_id, amount): only after the caller confirmed the amount. Opens the secure card form.",
    "get_payment_status": "get_payment_status(payment_ref): status of the latest payment.",
    "send_receipt": "send_receipt(account_id, payment_ref, channel): send a payment receipt by 'email' or 'sms'.",
    "request_agent_handoff": "request_agent_handoff(reason): transfer the caller to a human agent.",
}

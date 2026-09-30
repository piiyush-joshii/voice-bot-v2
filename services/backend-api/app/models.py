from typing import Literal

from pydantic import BaseModel, Field


class VerifyRequest(BaseModel):
    account_id: str
    verifier: str


class VerifyResponse(BaseModel):
    verified: bool
    needs_otp: bool


class OtpSendRequest(BaseModel):
    account_id: str
    channel: Literal["sms", "email"]


class OtpSendResponse(BaseModel):
    sent: bool


class OtpVerifyRequest(BaseModel):
    account_id: str
    code: str


class OtpVerifyResponse(BaseModel):
    verified: bool


class Bill(BaseModel):
    bill_id: str
    amount_due: float
    currency: str
    due_date: str
    status: Literal["due", "overdue", "paid"]


class HistoryItem(BaseModel):
    bill_id: str
    period: str
    amount: float
    paid: bool


class PaymentRecordRequest(BaseModel):
    account_id: str
    bill_id: str
    amount: float = Field(ge=0)
    payment_ref: str
    token: str
    last4: str = Field(pattern=r"^\d{4}$")
    status: Literal["succeeded", "failed", "cancelled", "expired"]


class PaymentRecordResponse(BaseModel):
    recorded: bool


class NotificationRequest(BaseModel):
    account_id: str
    channel: Literal["sms", "email"]
    template: Literal["receipt", "payment_failed", "generic"]
    payload: dict


class NotificationResponse(BaseModel):
    sent: bool


class OutboxItem(BaseModel):
    account_id: str
    channel: str
    template: str
    payload: dict
    sent_at: str


class Health(BaseModel):
    status: str

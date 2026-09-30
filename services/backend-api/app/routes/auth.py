import logging

from fastapi import APIRouter

from app import mock_data
from app.errors import ApiError
from app.models import (
    OtpSendRequest,
    OtpSendResponse,
    OtpVerifyRequest,
    OtpVerifyResponse,
    VerifyRequest,
    VerifyResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger("backend.auth")


def _account(account_id: str) -> dict:
    account = mock_data.store.accounts.get(account_id.strip().upper())
    if account is None:
        raise ApiError(404, "account_not_found", "Unknown account")
    return account


@router.post("/verify", response_model=VerifyResponse)
def verify(req: VerifyRequest) -> VerifyResponse:
    """Correct verifier authenticates directly. A wrong verifier offers the OTP fallback."""
    account = mock_data.store.accounts.get(req.account_id.strip().upper())
    if account is None:
        return VerifyResponse(verified=False, needs_otp=False)
    if req.verifier.strip() == account["verifier"]:
        return VerifyResponse(verified=True, needs_otp=False)
    return VerifyResponse(verified=False, needs_otp=True)


@router.post("/otp/send", response_model=OtpSendResponse)
def otp_send(req: OtpSendRequest) -> OtpSendResponse:
    _account(req.account_id)
    mock_data.store.otp_sent.add(req.account_id.strip().upper())
    print(f"[mock OTP] account={req.account_id} channel={req.channel} code={mock_data.MOCK_OTP}", flush=True)
    return OtpSendResponse(sent=True)


@router.post("/otp/verify", response_model=OtpVerifyResponse)
def otp_verify(req: OtpVerifyRequest) -> OtpVerifyResponse:
    account_id = req.account_id.strip().upper()
    if account_id not in mock_data.store.accounts:
        return OtpVerifyResponse(verified=False)
    ok = account_id in mock_data.store.otp_sent and req.code.strip() == mock_data.MOCK_OTP
    if ok:
        mock_data.store.otp_sent.discard(account_id)
    return OtpVerifyResponse(verified=ok)

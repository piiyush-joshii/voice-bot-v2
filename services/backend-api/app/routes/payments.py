import logging

from fastapi import APIRouter

from app import mock_data
from app.errors import ApiError
from app.models import PaymentRecordRequest, PaymentRecordResponse

router = APIRouter(prefix="/payments", tags=["payments"])
log = logging.getLogger("backend.payments")


@router.post("/record", response_model=PaymentRecordResponse)
def record_payment(req: PaymentRecordRequest) -> PaymentRecordResponse:
    """Stores a payment outcome. Only tokens and last4 are accepted, never card data."""
    account = mock_data.store.accounts.get(req.account_id.strip().upper())
    if account is None:
        raise ApiError(404, "account_not_found", "Unknown account")
    with mock_data.store.lock:
        if any(p["payment_ref"] == req.payment_ref for p in mock_data.store.payments):
            return PaymentRecordResponse(recorded=True)
        mock_data.store.payments.append(req.model_dump())
        bill = account["bill"]
        if req.status == "succeeded" and bill["bill_id"] == req.bill_id:
            bill["amount_due"] = round(max(0.0, bill["amount_due"] - req.amount), 2)
            if bill["amount_due"] == 0:
                bill["status"] = "paid"
            for h in account["history"]:
                if h["bill_id"] == req.bill_id and bill["amount_due"] == 0:
                    h["paid"] = True
    log.info("payment_recorded", extra={"event": "payment_recorded", "status": req.status})
    return PaymentRecordResponse(recorded=True)

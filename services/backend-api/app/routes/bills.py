from fastapi import APIRouter, Query

from app import mock_data
from app.errors import ApiError
from app.models import Bill, HistoryItem

router = APIRouter(prefix="/bills", tags=["bills"])


def _account(account_id: str) -> dict:
    account = mock_data.store.accounts.get(account_id.strip().upper())
    if account is None:
        raise ApiError(404, "account_not_found", "Unknown account")
    return account


@router.get("/{account_id}", response_model=Bill)
def get_bill(account_id: str) -> Bill:
    return Bill(**_account(account_id)["bill"])


@router.get("/{account_id}/history", response_model=list[HistoryItem])
def get_history(account_id: str, limit: int = Query(6, ge=1, le=24)) -> list[HistoryItem]:
    return [HistoryItem(**h) for h in _account(account_id)["history"][:limit]]

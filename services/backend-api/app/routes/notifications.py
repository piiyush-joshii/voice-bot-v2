import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Query

from app.errors import ApiError
from app.models import NotificationRequest, NotificationResponse, OutboxItem

router = APIRouter(prefix="/notifications", tags=["notifications"])

RECEIPT_KEYS = {"payment_ref", "amount", "last4", "date"}
_LONG_DIGITS = re.compile(r"(?:\d[ -]?){13,19}")
_lock = threading.Lock()


def outbox_path() -> Path:
    return Path(os.environ.get("OUTBOX_PATH", Path(__file__).resolve().parents[2] / "outbox.jsonl"))


def _contains_long_digit_run(value: object) -> bool:
    return bool(_LONG_DIGITS.search(json.dumps(value)))


@router.post("/send", response_model=NotificationResponse)
def send(req: NotificationRequest) -> NotificationResponse:
    if req.template == "receipt" and set(req.payload) - RECEIPT_KEYS:
        raise ApiError(422, "invalid_payload", "Receipt payload may only contain payment_ref, amount, last4, date")
    if _contains_long_digit_run(req.payload):
        raise ApiError(422, "invalid_payload", "Payload contains a card-like number")
    item = OutboxItem(
        account_id=req.account_id.strip().upper(),
        channel=req.channel,
        template=req.template,
        payload=req.payload,
        sent_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    path = outbox_path()
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(item.model_dump_json() + "\n")
    return NotificationResponse(sent=True)


@router.get("/outbox", response_model=list[OutboxItem])
def outbox(account_id: str | None = Query(None)) -> list[OutboxItem]:
    path = outbox_path()
    if not path.exists():
        return []
    items = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                items.append(OutboxItem.model_validate_json(line))
    if account_id:
        items = [i for i in items if i.account_id == account_id.strip().upper()]
    return list(reversed(items))

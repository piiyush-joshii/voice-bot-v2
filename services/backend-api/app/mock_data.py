"""In-memory seed data for the mock billing system.

Accounts:
  ACC1001  verifier 4321, bill due 84.50 USD
  ACC1002  verifier 1234, nothing due
  ACC1003  verifier 5678, overdue 210.00 USD

The OTP is always 123456 and is printed to the console when "sent".
"""

from __future__ import annotations

import copy
import threading
from dataclasses import dataclass, field

MOCK_OTP = "123456"

_SEED_ACCOUNTS: dict[str, dict] = {
    "ACC1001": {
        "verifier": "4321",
        "name": "Alex Rivera",
        "bill": {
            "bill_id": "BILL-1001-2609",
            "amount_due": 84.50,
            "currency": "USD",
            "due_date": "2026-10-15",
            "status": "due",
        },
        "history": [
            {"bill_id": "BILL-1001-2608", "period": "2026-08", "amount": 79.20, "paid": True},
            {"bill_id": "BILL-1001-2607", "period": "2026-07", "amount": 91.05, "paid": True},
            {"bill_id": "BILL-1001-2606", "period": "2026-06", "amount": 88.40, "paid": True},
            {"bill_id": "BILL-1001-2605", "period": "2026-05", "amount": 72.10, "paid": True},
            {"bill_id": "BILL-1001-2604", "period": "2026-04", "amount": 69.95, "paid": True},
            {"bill_id": "BILL-1001-2603", "period": "2026-03", "amount": 95.30, "paid": True},
        ],
    },
    "ACC1002": {
        "verifier": "1234",
        "name": "Sam Chen",
        "bill": {
            "bill_id": "BILL-1002-2609",
            "amount_due": 0.00,
            "currency": "USD",
            "due_date": "2026-10-20",
            "status": "paid",
        },
        "history": [
            {"bill_id": "BILL-1002-2609", "period": "2026-09", "amount": 55.00, "paid": True},
            {"bill_id": "BILL-1002-2608", "period": "2026-08", "amount": 52.75, "paid": True},
            {"bill_id": "BILL-1002-2607", "period": "2026-07", "amount": 58.10, "paid": True},
        ],
    },
    "ACC1003": {
        "verifier": "5678",
        "name": "Jordan Patel",
        "bill": {
            "bill_id": "BILL-1003-2608",
            "amount_due": 210.00,
            "currency": "USD",
            "due_date": "2026-09-10",
            "status": "overdue",
        },
        "history": [
            {"bill_id": "BILL-1003-2608", "period": "2026-08", "amount": 210.00, "paid": False},
            {"bill_id": "BILL-1003-2607", "period": "2026-07", "amount": 104.50, "paid": True},
            {"bill_id": "BILL-1003-2606", "period": "2026-06", "amount": 99.80, "paid": True},
        ],
    },
}


@dataclass
class Store:
    accounts: dict[str, dict] = field(default_factory=lambda: copy.deepcopy(_SEED_ACCOUNTS))
    payments: list[dict] = field(default_factory=list)
    otp_sent: set[str] = field(default_factory=set)
    lock: threading.Lock = field(default_factory=threading.Lock)


store = Store()


def reset_store() -> None:
    """Restore seed data (used by tests and the /admin/reset endpoint)."""
    global store
    store.accounts = copy.deepcopy(_SEED_ACCOUNTS)
    store.payments = []
    store.otp_sent = set()

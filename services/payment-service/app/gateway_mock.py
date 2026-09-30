"""Mock payment gateway. Test cards only (see docs/PAYMENT_GATE_AND_PCI.md)."""

from __future__ import annotations

import secrets
from dataclasses import dataclass

DECLINED = "4000000000000002"
INSUFFICIENT_FUNDS = "4000000000009995"


@dataclass(frozen=True)
class ChargeResult:
    approved: bool
    failure_code: str | None
    payment_ref: str
    token: str | None
    last4: str


def charge(pan: str, amount: float) -> ChargeResult:
    """`pan` must already be Luhn-validated and normalized. It is not retained."""
    last4 = pan[-4:]
    payment_ref = "PAY-" + secrets.token_hex(4).upper()
    if pan == DECLINED:
        return ChargeResult(False, "declined", payment_ref, None, last4)
    if pan == INSUFFICIENT_FUNDS:
        return ChargeResult(False, "insufficient_funds", payment_ref, None, last4)
    return ChargeResult(True, None, payment_ref, "tok_" + secrets.token_hex(12), last4)

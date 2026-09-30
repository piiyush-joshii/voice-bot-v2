"""Card field validation. Values passed in here are never logged or stored."""

from __future__ import annotations

import re
from datetime import date

_NON_DIGITS = re.compile(r"[\s-]")


def normalize_pan(pan: str) -> str:
    return _NON_DIGITS.sub("", pan or "")


def luhn_valid(number: str) -> bool:
    if not number.isdigit() or not 13 <= len(number) <= 19:
        return False
    total = 0
    for i, ch in enumerate(reversed(number)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def expiry_valid(expiry: str, today: date | None = None) -> bool:
    """Accepts MM/YY or MM/YYYY. The card is valid through the end of the expiry month."""
    m = re.fullmatch(r"\s*(\d{1,2})\s*/\s*(\d{2}|\d{4})\s*", expiry or "")
    if not m:
        return False
    month, year = int(m.group(1)), int(m.group(2))
    if not 1 <= month <= 12:
        return False
    if year < 100:
        year += 2000
    today = today or date.today()
    return (year, month) >= (today.year, today.month)


def cvv_valid(cvv: str) -> bool:
    return bool(re.fullmatch(r"\d{3,4}", (cvv or "").strip()))

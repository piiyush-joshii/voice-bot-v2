"""PCI leak test 4: table-driven scrubber cases, including numbers that must NOT be redacted."""

import pytest

from app.processors.scrubber import contains_pan_like, redact_for_logs, scrub_text

REDACT = [
    ("my card is 4111111111111111", "[REDACTED_PAN]"),
    ("4111 1111 1111 1111", "[REDACTED_PAN]"),
    ("4111-1111-1111-1111 please", "[REDACTED_PAN]"),
    ("it's 4000 0000 0000 0002", "[REDACTED_PAN]"),
    ("amex 3782 822463 10005", "[REDACTED_PAN]"),
    ("four one one one one one one one one one one one one one one one", "[REDACTED_PAN]"),
    ("four one one one, one one one one, one one one one, one one one one", "[REDACTED_PAN]"),
    ("four double one one one one one one one one one one one one one", "[REDACTED_PAN]"),
    ("my card number is 4111 1111", "[REDACTED_PAN]"),
    ("the cvv is 123", "[REDACTED_CVV]"),
    ("security code seven three seven", "[REDACTED_CVV]"),
    ("CVC: 9731", "[REDACTED_CVV]"),
    ("it expires 12/30", "[REDACTED_EXP]"),
    ("expiry date is december twenty thirty", "[REDACTED_EXP]"),
]

KEEP = [
    "my account is ACC1001",
    "the verifier is 4321",
    "my one-time code is 123456",
    "I want to pay 84.50",
    "pay two hundred and ten dollars",
    "bill BILL-1001-2609",
    "call me at 555-123-4567",
    "the reference is PAY-1A2B3C4D",
    "one two three four",
    "it was due on 2026-10-15",
]


@pytest.mark.parametrize("text,token", REDACT)
def test_redacts(text, token):
    result = scrub_text(text)
    assert token in result.text
    assert result.hits >= 1
    assert not contains_pan_like(result.text)
    for secret in ("4111", "9731", "737", "12/30", "0002", "10005"):
        if secret in text:
            assert secret not in result.text


@pytest.mark.parametrize("text", KEEP)
def test_keeps_non_card_numbers(text):
    result = scrub_text(text)
    assert result.text == text
    assert result.hits == 0


def test_log_redaction():
    assert redact_for_logs("pan=4111 1111 1111 1111 end") == "pan=[REDACTED_PAN] end"
    assert redact_for_logs("ts=1790745097.123") == "ts=1790745097.123"

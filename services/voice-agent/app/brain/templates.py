"""Deterministic spoken responses. Facts (amounts, dates, references) are only ever spoken from
validated tool results through these templates, never from free-form model text."""

from __future__ import annotations

import re
from datetime import date

SECURE_CAPTURE_PROMPT = (
    "Please enter your card details in the secure form on your screen. "
    "I won't be able to hear you until you're done."
)
CARD_DETAILS_INTERRUPT = (
    "For your security, please don't say card details out loud. "
    "You'll enter them in the secure form on your screen when we get to payment."
)
GREETING = "Hi, I'm the payment voice bot. I can take a bill payment. What's your account number?"
GREETING_AUTHENTICATED = "You're verified on this account. How would you like to proceed? I can take the payment now."
PAYMENT_ONLY = "I can only take a payment on this line. How would you like to proceed?"
GOODBYE = "Thanks for calling. Goodbye!"
HANDOFF = "Sure, I'm connecting you with an agent now. Please hold."
IN_HANDOFF = "You're being connected to an agent. Please hold."
NEED_AUTH = "I'll need to verify your identity first. What's your account number?"
ASK_LAST_FOUR = "What are the last four digits of the phone on that account?"
UNKNOWN_ACCOUNT = "I didn't recognize that account. Could you repeat the account number?"
REPEAT_ACCOUNT = "Okay. What's your account number?"
FALLBACK = "Sorry, I didn't catch that. Could you try again?"
SERVICE_ERROR = "Sorry, I'm having trouble reaching our billing system. Please try again in a moment."
PAYMENT_CANCELLED_BY_CALLER = "No problem, I won't take a payment. Is there anything else I can help with?"
CAPTURE_TIMEOUT = "The secure form timed out before a payment was made. Would you like to try again?"
CAPTURE_CANCELLED = "The payment was cancelled in the secure form. Would you like to try again?"


_PLACEHOLDER = re.compile(r"^(none|null|n/?a|undefined|nil)$", re.I)


def clean_reply(text: str) -> str:
    """Drop JSON placeholders such as 'none' so they are never spoken."""
    cleaned = " ".join((text or "").strip().strip('"').split())
    if not cleaned or _PLACEHOLDER.match(cleaned):
        return ""
    return cleaned


def money(amount: float, currency: str = "USD") -> str:
    symbol = "$" if currency == "USD" else f"{currency} "
    return f"{symbol}{amount:,.2f}"


def spoken_date(iso: str) -> str:
    try:
        d = date.fromisoformat(iso)
    except ValueError:
        return iso
    return f"{d.strftime('%B')} {d.day}"


def _history_line(item: dict) -> str:
    try:
        month = date.fromisoformat(item["period"] + "-01").strftime("%B")
    except ValueError:
        month = item["period"]
    return f"{month} was {money(item['amount'])}{'' if item['paid'] else ', unpaid'}"


def tool_result_text(name: str, result: dict, *, then_ask: bool = True) -> str | None:
    """Spoken text for a tool result, or None if the model should phrase it."""
    err = result.get("error")
    if err:
        return {
            "not_grounded": None,
            "invalid_args": None,
            "not_available": None,
            "account_mismatch": "I can only help with the account you verified.",
            "not_found": "I couldn't find that account. Could you repeat the account number?",
            "nothing_due": "Good news, there's nothing due on your account right now.",
            "amount_exceeds_balance": "That's more than the amount due. You can pay up to the full balance.",
            "amount_mismatch": "That doesn't match the amount you confirmed. Let's set the payment up again.",
            "not_confirmed": "Before I open the secure form, please confirm the amount.",
            "no_payment": "I don't see a completed payment in this call yet.",
            "service_unavailable": SERVICE_ERROR,
        }.get(err)

    if name == "verify_identity":
        if result["verified"]:
            return None
        if result["needs_otp"]:
            return "That didn't match our records. I can send a one-time code by text or email instead. Which would you prefer?"
        return "I couldn't find that account. Could you repeat the account number?"
    if name == "send_otp":
        return "I've sent a 6-digit code. Please read it out when you have it."
    if name == "verify_otp":
        return None if result["verified"] else "That code didn't match. Please check it and try again."
    if name == "get_bill":
        if result["amount_due"] <= 0:
            return "You don't have anything due right now. Your account is fully paid."
        overdue = " It's overdue." if result["status"] == "overdue" else ""
        ask = " Would you like to pay it now?" if then_ask else ""
        return (f"Your current bill is {money(result['amount_due'], result['currency'])}, "
                f"due {spoken_date(result['due_date'])}.{overdue}{ask}")
    if name == "get_bill_history":
        items = result["items"][:3]
        if not items:
            return "I don't see any past bills."
        return "Your recent bills: " + "; ".join(_history_line(i) for i in items) + "."
    if name == "prepare_payment":
        return (f"Just to confirm: you'd like to pay {money(result['amount'], result['currency'])} "
                f"toward bill {result['bill_id']}. Shall I open the secure payment form?")
    if name == "initiate_payment":
        return SECURE_CAPTURE_PROMPT
    if name == "get_payment_status":
        if result["status"] == "succeeded":
            return f"Your last payment went through. The reference is {spell_ref(result['payment_ref'])}."
        return "Your last payment did not go through."
    if name == "send_receipt":
        return "Done, I've sent your receipt. Anything else?" if result["sent"] else SERVICE_ERROR
    if name == "request_agent_handoff":
        return HANDOFF
    return None


def heard_account(account_id: str) -> str:
    """Read the account back one character at a time so the caller can confirm it."""
    return f"I heard account {' '.join(account_id)}. Is that correct?"


def verified_ready(account_id: str, bill: dict) -> str:
    """Spoken once identity is confirmed. This line is payment-only."""
    if bill.get("error") or "amount_due" not in bill:
        return f"You're verified. This is account {account_id}. I couldn't read the amount due just now."
    if bill["amount_due"] <= 0:
        return (f"You're verified. This is account {account_id}. "
                "There's nothing due right now, so I can't take a payment.")
    overdue = " It's overdue." if bill.get("status") == "overdue" else ""
    return (f"You're verified. This is account {account_id}. "
            f"The amount due is {money(bill['amount_due'], bill.get('currency', 'USD'))}, "
            f"due {spoken_date(bill['due_date'])}.{overdue} "
            "How would you like to proceed?")


def spell_ref(ref: str | None) -> str:
    return ref or "unavailable"


def payment_result_text(status: str, amount: float | None, payment_ref: str | None, last4: str | None,
                        failure_code: str | None) -> str:
    if status == "succeeded":
        amt = f" of {money(amount)}" if amount else ""
        return (f"Your payment{amt} was successful, using the card ending in {last4}. "
                f"Your reference is {spell_ref(payment_ref)}. Would you like a receipt by email or text?")
    reason = {
        "declined": "the card was declined",
        "insufficient_funds": "the card has insufficient funds",
        "invalid_card": "the card details couldn't be validated",
    }.get(failure_code or "", "it couldn't be completed")
    return f"I'm sorry, the payment didn't go through because {reason}. Would you like to try another card?"

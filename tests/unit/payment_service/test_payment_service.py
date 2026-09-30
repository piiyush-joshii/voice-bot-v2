"""payment-service tests: contracts, validation, mock gateway, signed webhooks, strict headers,
and that responses and logs never contain PAN, expiry, or CVV."""

import hashlib
import hmac
import json
import logging

import pytest

PAN = "4111 1111 1111 1111"
EXPIRY = "11/29"
CVV = "9731"
LEAK_PAN = "5555 5555 5555 4444"  # not shown in the TEST MODE banner


def create(client, amount=84.5):
    r = client.post("/payment-sessions", json={
        "account_id": "ACC1001", "bill_id": "BILL-1001-2609", "amount": amount, "currency": "USD",
        "callback_url": "http://localhost:7860/internal/payment-events",
        "allowed_frame_origin": "http://localhost:5173"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"payment_session_id", "capture_url", "expires_at"}
    return body


def test_luhn_and_fields():
    from app import luhn

    assert luhn.luhn_valid("4111111111111111")
    assert not luhn.luhn_valid("4111111111111112")
    assert luhn.expiry_valid("11/29") and not luhn.expiry_valid("01/20") and not luhn.expiry_valid("13/30")
    assert luhn.cvv_valid("123") and luhn.cvv_valid("1234") and not luhn.cvv_valid("12")


def test_health(app_and_hooks):
    client, _ = app_and_hooks
    assert client.get("/health").json() == {"status": "ok"}


def test_session_rejects_foreign_callback_and_origin(app_and_hooks):
    client, _ = app_and_hooks
    base = {"account_id": "ACC1001", "bill_id": "B", "amount": 1, "currency": "USD",
            "callback_url": "http://localhost:7860/x", "allowed_frame_origin": "http://localhost:5173"}
    assert client.post("/payment-sessions", json={**base, "callback_url": "http://evil.test/x"}).status_code == 422
    assert client.post("/payment-sessions", json={**base, "allowed_frame_origin": "http://evil.test"}).status_code == 422


def test_capture_page_headers(app_and_hooks):
    client, _ = app_and_hooks
    s = create(client)
    r = client.get(f"/capture/{s['payment_session_id']}")
    assert r.status_code == 200
    csp = r.headers["content-security-policy"]
    assert "default-src 'self'" in csp and "frame-ancestors http://localhost:5173" in csp
    assert r.headers["cache-control"] == "no-store"
    assert 'autocomplete="off"' in r.text and "TEST MODE" in r.text
    assert "<script>" not in r.text  # no inline script; CSP forbids it


@pytest.mark.parametrize("pan,status,failure", [
    ("4111 1111 1111 1111", "succeeded", None),
    ("4000 0000 0000 0002", "failed", "declined"),
    ("4000 0000 0000 9995", "failed", "insufficient_funds"),
    ("5555 5555 5555 4444", "succeeded", None),
])
def test_gateway_rules_and_signed_webhook(app_and_hooks, pan, status, failure):
    client, delivered = app_and_hooks
    s = create(client)
    sid = s["payment_session_id"]
    r = client.post(f"/capture/{sid}/submit", json={"pan": pan, "expiry": EXPIRY, "cvv": CVV})
    assert r.json()["status"] == status
    st = client.get(f"/payment-sessions/{sid}/status").json()
    assert st["status"] == status and st["failure_code"] == failure and st["last4"] == pan[-4:]
    assert (st["token"] or "").startswith("tok_") == (status == "succeeded")

    body, headers = delivered[-1]
    expected = hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()
    assert headers["X-Signature"] == expected and headers["X-Timestamp"].isdigit()
    payload = json.loads(body)
    assert set(payload) == {"payment_session_id", "status", "payment_ref", "token", "last4", "failure_code",
                            "account_id", "bill_id", "amount"}


def test_invalid_input_keeps_session_until_three_attempts(app_and_hooks):
    client, delivered = app_and_hooks
    sid = create(client)["payment_session_id"]
    r = client.post(f"/capture/{sid}/submit", json={"pan": "4111 1111 1111 1112", "expiry": EXPIRY, "cvv": CVV}).json()
    assert r == {"status": "capturing", "error": "invalid_card", "attempts_left": 2}
    r = client.post(f"/capture/{sid}/submit", json={"pan": PAN, "expiry": "01/20", "cvv": CVV}).json()
    assert r["error"] == "invalid_expiry"
    r = client.post(f"/capture/{sid}/submit", json={"pan": PAN, "expiry": EXPIRY, "cvv": "1"}).json()
    assert r["status"] == "failed" and r["attempts_left"] == 0
    assert json.loads(delivered[-1][0])["failure_code"] == "invalid_card"


def test_cancel(app_and_hooks):
    client, delivered = app_and_hooks
    sid = create(client)["payment_session_id"]
    assert client.post(f"/capture/{sid}/cancel").json()["status"] == "cancelled"
    assert json.loads(delivered[-1][0])["status"] == "cancelled"


def test_no_card_data_in_responses_or_logs(app_and_hooks, caplog):
    client, delivered = app_and_hooks
    caplog.set_level(logging.DEBUG)
    responses = []
    sid = create(client)["payment_session_id"]
    responses.append(client.get(f"/capture/{sid}").text)
    responses.append(client.post(f"/capture/{sid}/submit", json={"pan": "5555 5555 5555 4445", "expiry": EXPIRY, "cvv": CVV}).text)
    responses.append(client.post(f"/capture/{sid}/submit", json={"pan": LEAK_PAN, "expiry": EXPIRY, "cvv": CVV}).text)
    responses.append(client.get(f"/payment-sessions/{sid}/status").text)
    responses.append(client.get(f"/capture/{sid}/state").text)
    # Validation errors must not echo input values either.
    responses.append(client.post(f"/capture/{sid}/submit", json={"pan": LEAK_PAN, "expiry": EXPIRY, "cvv": "123456789"}).text)

    blob = "\n".join(responses) + "\n".join(b.decode() for b, _ in delivered) + "\n".join(
        r.getMessage() + " " + json.dumps({k: str(v) for k, v in r.__dict__.items()}) for r in caplog.records)
    compact = blob.replace(" ", "")
    assert "5555555555554444" not in compact and "5555555555554445" not in compact
    assert EXPIRY not in blob
    assert CVV not in blob

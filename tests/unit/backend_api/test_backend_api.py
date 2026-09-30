"""backend-api contract tests (docs/API_SPEC.md section 1)."""


def test_health_and_request_id(client):
    r = client.get("/health", headers={"X-Request-Id": "abc"})
    assert r.json() == {"status": "ok"}
    assert r.headers["X-Request-Id"] == "abc"


def test_auth_flow(client):
    assert client.post("/auth/verify", json={"account_id": "ACC1001", "verifier": "4321"}).json() == \
        {"verified": True, "needs_otp": False}
    assert client.post("/auth/verify", json={"account_id": "ACC1001", "verifier": "0000"}).json() == \
        {"verified": False, "needs_otp": True}
    assert client.post("/auth/otp/verify", json={"account_id": "ACC1001", "code": "123456"}).json() == {"verified": False}
    assert client.post("/auth/otp/send", json={"account_id": "ACC1001", "channel": "sms"}).json() == {"sent": True}
    assert client.post("/auth/otp/verify", json={"account_id": "ACC1001", "code": "123456"}).json() == {"verified": True}


def test_bills(client):
    bill = client.get("/bills/ACC1001").json()
    assert set(bill) == {"bill_id", "amount_due", "currency", "due_date", "status"}
    assert bill["amount_due"] == 84.5
    assert client.get("/bills/ACC1002").json()["amount_due"] == 0
    assert client.get("/bills/ACC1003").json()["status"] == "overdue"
    history = client.get("/bills/ACC1001/history", params={"limit": 2}).json()
    assert len(history) == 2 and set(history[0]) == {"bill_id", "period", "amount", "paid"}
    r = client.get("/bills/NOPE")
    assert r.status_code == 404 and r.json()["error"]["code"] == "account_not_found"


def test_payment_record_marks_bill_paid(client):
    record = {"account_id": "ACC1001", "bill_id": "BILL-1001-2609", "amount": 84.5, "payment_ref": "PAY-1",
              "token": "tok_abc", "last4": "1111", "status": "succeeded"}
    assert client.post("/payments/record", json=record).json() == {"recorded": True}
    bill = client.get("/bills/ACC1001").json()
    assert bill["amount_due"] == 0 and bill["status"] == "paid"
    bad = {**record, "last4": "4111111111111111"}
    assert client.post("/payments/record", json=bad).status_code == 422


def test_receipt_outbox(client):
    payload = {"payment_ref": "PAY-1", "amount": 84.5, "last4": "1111", "date": "2026-09-30"}
    r = client.post("/notifications/send", json={"account_id": "ACC1001", "channel": "email",
                                                 "template": "receipt", "payload": payload})
    assert r.json() == {"sent": True}
    outbox = client.get("/notifications/outbox", params={"account_id": "ACC1001"}).json()
    assert outbox[0]["payload"] == payload
    extra = client.post("/notifications/send", json={"account_id": "ACC1001", "channel": "email",
                                                     "template": "receipt", "payload": {**payload, "pan": "x"}})
    assert extra.status_code == 422
    card = client.post("/notifications/send", json={"account_id": "ACC1001", "channel": "email",
                                                    "template": "generic", "payload": {"note": "4111 1111 1111 1111"}})
    assert card.status_code == 422


def test_cors_only_web_console(client):
    ok = client.options("/health", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    bad = client.options("/health", headers={"Origin": "http://evil.test", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in bad.headers

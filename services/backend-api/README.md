# backend-api

Mock billing system for the EBPP voice POC. It stores accounts, bills, a one-time code, payment outcomes, and notification receipts in memory. It does not run a model and it never sees a card number.

The voice agent calls this service after the caller is verified. Card capture lives in `payment-service` (port 8002).

Listens on **http://127.0.0.1:8001**. OpenAPI is at [http://127.0.0.1:8001/docs](http://127.0.0.1:8001/docs).

## Run

From this directory, with [uv](https://docs.astral.sh/uv/) and Python 3.11 or 3.12:

```bash
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8001
```

From the repo root, `./scripts/dev.sh` starts this service with the others. Logs go to `logs/backend-api.log`.

```bash
curl -s http://127.0.0.1:8001/health
```

## Seed accounts

Data is in `app/mock_data.py` and resets when the process restarts.

| Account | Verifier (last 4 of phone) | Bill |
|---|---|---|
| ACC1001 | 4321 | $84.50 due, due date 2026-10-15 (`BILL-1001-2609`) |
| ACC1002 | 1234 | $0.00, already paid |
| ACC1003 | 5678 | $210.00 overdue, due date 2026-09-10 |

The one-time code is always `123456`. `POST /auth/otp/send` prints it to the server log. It is not texted or emailed.

`POST /admin/reset` restores the seed accounts, clears recorded payments, and deletes the notification outbox. It is hidden from the OpenAPI schema.

## Endpoints

`GET /health` returns `{"status":"ok"}`.

Errors are `{"error":{"code":"...","message":"..."}}`. An `X-Request-Id` request header is echoed on the response. CORS allows `http://localhost:5173`.

### Auth

`POST /auth/verify`

```json
{ "account_id": "ACC1001", "verifier": "4321" }
```

```json
{ "verified": true, "needs_otp": false }
```

A wrong verifier on a known account returns `verified: false, needs_otp: true`. An unknown account returns `verified: false, needs_otp: false` (HTTP 200, not 404).

`POST /auth/otp/send` body: `{ "account_id", "channel": "sms" | "email" }`. Unknown accounts return 404 `account_not_found`.

`POST /auth/otp/verify` body: `{ "account_id", "code" }`. Succeeds only after a send, and only for code `123456`. A successful check consumes the code.

### Bills

`GET /bills/{account_id}`

```json
{
  "bill_id": "BILL-1001-2609",
  "amount_due": 84.5,
  "currency": "USD",
  "due_date": "2026-10-15",
  "status": "due"
}
```

`status` is `due`, `overdue`, or `paid`. Unknown accounts return 404 `account_not_found`.

`GET /bills/{account_id}/history?limit=6` returns `[{ "bill_id", "period", "amount", "paid" }]`. `limit` is 1–24 and defaults to 6.

### Payments

`POST /payments/record`

```json
{
  "account_id": "ACC1001",
  "bill_id": "BILL-1001-2609",
  "amount": 84.5,
  "payment_ref": "PAY-1234",
  "token": "tok_abc",
  "last4": "1111",
  "status": "succeeded"
}
```

`status` is `succeeded`, `failed`, `cancelled`, or `expired`. `last4` must be four digits. There is no field for a full card number, expiry, or CVV.

A `succeeded` record for the current bill reduces `amount_due`. At zero the bill status becomes `paid`. Sending the same `payment_ref` again returns `{"recorded": true}` and does not apply the amount twice.

### Notifications

`POST /notifications/send`

```json
{
  "account_id": "ACC1001",
  "channel": "email",
  "template": "receipt",
  "payload": { "payment_ref": "PAY-1234", "amount": 84.5, "last4": "1111", "date": "2026-09-30" }
}
```

`channel` is `sms` or `email`. `template` is `receipt`, `payment_failed`, or `generic`.

A receipt payload may only contain `payment_ref`, `amount`, `last4`, and `date`. Any payload with a 13–19 digit run is rejected with 422 `invalid_payload`.

Each send is appended to `outbox.jsonl` in this directory (`OUTBOX_PATH` overrides the path). Nothing is delivered.

`GET /notifications/outbox?account_id=ACC1001` returns those rows, newest first.

## Tests

```bash
uv run pytest -q ../../tests/unit/backend_api
```

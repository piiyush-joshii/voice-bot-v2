# Models, tools, and API endpoints

Local reference for the EBPP voice POC. Every service is localhost only. OpenAPI for the HTTP services is at `/docs` on that service's port.

Card numbers, expiry, and CVV exist only inside `payment-service` and its capture page. Tools and model context receive IDs, amounts, status, a payment token, and last four digits.

## Models

Configured in the repo-root `.env`. Weights live under `models/`. After the first download the process runs with `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`.

| Role | Model | Where it runs | Default |
|---|---|---|---|
| Speech to text | faster-whisper `small.en` | voice-agent, CPU, int8 | `ASR_BACKEND=whisper`, `WHISPER_MODEL=small.en` |
| Voice activity | Silero VAD | voice-agent, inside the Pipecat pipeline | end of speech and barge-in |
| Intent router | `sentence-transformers/all-MiniLM-L6-v2` | voice-agent, local embeddings | `EMBED_MODEL`, `ROUTER_HIGH=0.80`, `ROUTER_FAQ=0.60` |
| Language model | `phi4-mini` | Ollama on port 11434 | `LLM_MODEL=phi4-mini`, `LLM_TOOL_MODE=json` |
| Text to speech | Kokoro-82M v1.0 | voice-agent, ONNX (`models/kokoro/kokoro-v1.0.onnx`, `voices-v1.0.bin`) | `TTS_BACKEND=kokoro`, `KOKORO_VOICE=af_heart` |

`backend-api` and `payment-service` do not load a model.

The language model is called at `POST http://localhost:11434/v1/chat/completions`. Tool calls are constrained JSON (`LLM_TOOL_MODE=json`), not native Ollama `tool_calls`. `pay_bill` is never answered by the router alone; it always goes through the conversation brain. A score at or above `0.80` can skip the language model only for a small allowlist (`request_agent`, `greeting`, `goodbye`, and a few bill questions once the caller is verified).

Audio path inside voice-agent:

```
mic → Silero VAD → payment gate → faster-whisper → scrubber → MiniLM router → phi4-mini → Kokoro → speaker
```

While the gate is `SECURE_CAPTURE` or `HANDOFF`, audio is dropped before speech recognition.

## Tools

The voice agent exposes these tools to the language model. A tool that is not allowed in the current gate state returns `{"error":"not_available"}` and does not call another service. Arguments that were not spoken by the caller return `{"error":"not_grounded"}`.

| Tool | Arguments | Calls | Allowed in |
|---|---|---|---|
| `verify_identity` | `account_id` (`ACC` + 4 digits), `verifier` (4 digits) | `POST /auth/verify` | `UNAUTHENTICATED` |
| `send_otp` | `account_id`, `channel` (`sms` or `email`) | `POST /auth/otp/send` | `UNAUTHENTICATED` |
| `verify_otp` | `account_id`, `code` (6 digits) | `POST /auth/otp/verify` | `UNAUTHENTICATED` |
| `get_bill` | `account_id` | `GET /bills/{account_id}` | `AUTHENTICATED`, `PAYMENT_PENDING` |
| `get_bill_history` | `account_id`, `limit` (1–12, default 3) | `GET /bills/{account_id}/history` | `AUTHENTICATED`, `PAYMENT_PENDING` |
| `prepare_payment` | `account_id`, optional `bill_id`, optional `amount` | `GET /bills/{account_id}`, then holds the amount for confirmation | `AUTHENTICATED`, `PAYMENT_PENDING` |
| `initiate_payment` | same shape as `prepare_payment` | `POST /payment-sessions` | `PAYMENT_PENDING`, and only after the caller confirmed the amount |
| `get_payment_status` | optional `payment_ref` | none; reads the last webhook outcome on the session | `PAYMENT_RESULT` |
| `send_receipt` | `account_id`, optional `payment_ref`, `channel` | `POST /notifications/send` with template `receipt` | `AUTHENTICATED`, `PAYMENT_PENDING`, `PAYMENT_RESULT` |
| `request_agent_handoff` | `reason` | none; moves the gate to `HANDOFF` and returns `handoff_id` | every state except `SECURE_CAPTURE` and `HANDOFF` |

`SECURE_CAPTURE` and `HANDOFF` expose no tools.

`initiate_payment` returns only `{payment_session_id, status: "secure_capture_started"}`. The capture URL is sent to the web console on the debug socket, not to the language model.

`send_receipt` sends `{payment_ref, amount, last4, date}`. It runs only after a succeeded payment.

## API endpoints

### voice-agent — port 7860

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | `{"status":"ok"}` |
| POST | `/sessions` | Body `{mode: "voice" \| "text"}`. Returns `session_id`, `ws_debug_url`, `ws_text_url`, and `webrtc_offer_url` for voice |
| GET | `/sessions/{session_id}` | `{state, created_at, mode, metrics_summary}` |
| POST | `/sessions/{session_id}/handoff` | `{handoff_id, summary}` |
| POST | `/api/offer` | WebRTC offer for a voice session |
| WS | `/ws/text/{session_id}` | Client sends `{type:"user_text", text}`. Server sends `{type:"assistant_text"}` or `{type:"rejected", reason:"secure_capture_active"}` |
| WS | `/ws/debug/{session_id}` | Read-only events: state, transcript, router, tool_call, tool_result, secure_capture, payment_result, latency |
| POST | `/internal/payment-events` | HMAC-signed webhook from payment-service. Body is status, `payment_ref`, `token`, `last4`, `failure_code`, account, bill, amount |

### backend-api — port 8001

No model. In-memory accounts. Full write-up: `services/backend-api/README.md`.

| Method | Path | Body or query | Response |
|---|---|---|---|
| GET | `/health` | | `{status:"ok"}` |
| POST | `/auth/verify` | `{account_id, verifier}` | `{verified, needs_otp}` |
| POST | `/auth/otp/send` | `{account_id, channel}` | `{sent: true}` |
| POST | `/auth/otp/verify` | `{account_id, code}` | `{verified}` |
| GET | `/bills/{account_id}` | | `{bill_id, amount_due, currency, due_date, status}` |
| GET | `/bills/{account_id}/history` | `?limit=6` (1–24) | `[{bill_id, period, amount, paid}]` |
| POST | `/payments/record` | `{account_id, bill_id, amount, payment_ref, token, last4, status}` | `{recorded: true}` |
| POST | `/notifications/send` | `{account_id, channel, template, payload}` | `{sent: true}` |
| GET | `/notifications/outbox` | `?account_id=` | newest notification rows first |
| POST | `/admin/reset` | | restores seed data; omitted from OpenAPI |

Seed accounts: `ACC1001` verifier `4321`, $84.50 due; `ACC1002` verifier `1234`, nothing due; `ACC1003` verifier `5678`, $210.00 overdue. OTP is always `123456`.

### payment-service — port 8002

Simulated card zone. The submit body is the only place a test card is accepted, and the response is status only.

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/health` | | `{status:"ok"}` |
| POST | `/payment-sessions` | `{account_id, bill_id, amount, currency, callback_url, allowed_frame_origin}` | `{payment_session_id, capture_url, expires_at}` |
| GET | `/capture/{payment_session_id}` | | HTML card form |
| GET | `/capture/{payment_session_id}/state` | | `{status, seconds_left, attempts_left}` |
| POST | `/capture/{payment_session_id}/submit` | `{pan, expiry, cvv}` from the form only | `{status}` |
| POST | `/capture/{payment_session_id}/cancel` | | `{status:"cancelled"}` |
| GET | `/payment-sessions/{payment_session_id}/status` | | `{status, payment_ref, token, last4, failure_code}` |

On a terminal status the service `POST`s the signed event to `callback_url`, which is `http://localhost:7860/internal/payment-events`. Headers are `X-Signature` (hex HMAC-SHA256 of the raw body) and `X-Timestamp`.

Test cards: `4111 1111 1111 1111` approves, `4000 0000 0000 0002` declines, `4000 0000 0000 9995` is insufficient funds.

### Ollama — port 11434

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/tags` | health check used by `scripts/dev.sh` |
| POST | `/v1/chat/completions` | `phi4-mini` chat and JSON tool calls |

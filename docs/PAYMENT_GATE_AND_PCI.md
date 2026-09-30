# Payment Gate and PCI Scope Reduction

The goal: **prove that no cardholder data (PAN, CVV, expiry) can reach the ASR, LLM, transcripts, logs, or recordings.**

## Test data only

| Card | Behavior |
|---|---|
| `4111 1111 1111 1111` | Approved |
| `4000 0000 0000 0002` | Declined |
| `4000 0000 0000 9995` | Insufficient funds |
| Any other Luhn-valid number | Approved |
| Non-Luhn number | Rejected at validation |

Never use real cards. Add a banner in the payment page: "TEST MODE".

## State machine

| State | Audio to ASR/LLM | Recording and content logging | Tools exposed to LLM |
|---|---|---|---|
| `UNAUTHENTICATED` | Open | Normal | `verify_identity`, `send_otp`, `verify_otp`, `request_agent_handoff` |
| `AUTHENTICATED` | Open | Normal | `get_bill`, `get_bill_history`, `send_receipt`, `request_agent_handoff` |
| `PAYMENT_PENDING` | Open | Normal | above + `initiate_payment` (only after amount confirmed) |
| `SECURE_CAPTURE` | **Closed (dropped at gate)** | **Paused** | none |
| `PAYMENT_RESULT` | Open | Resumes | `get_payment_status`, `send_receipt`, `request_agent_handoff` |
| `HANDOFF` | Closed to the model | Policy-defined | none |

### Transitions

```
UNAUTHENTICATED ──verify ok──▶ AUTHENTICATED
AUTHENTICATED ──user wants to pay + amount confirmed──▶ PAYMENT_PENDING
PAYMENT_PENDING ──initiate_payment tool result ok──▶ SECURE_CAPTURE
SECURE_CAPTURE ──signed webhook (success|failed)──▶ PAYMENT_RESULT
SECURE_CAPTURE ──timeout (120 s) or user cancel in iframe──▶ PAYMENT_PENDING (with error)
PAYMENT_RESULT ──anything──▶ AUTHENTICATED
any ──agent handoff──▶ HANDOFF
```

### Rules

1. Transitions into and out of `SECURE_CAPTURE` are triggered **only by orchestrator code** (the `initiate_payment` result and the verified webhook). Never by LLM text, never by user speech.
2. The LLM never receives a tool that can open the gate or read capture data.
3. The webhook must carry a valid HMAC-SHA256 signature (`X-Signature`) and a known `payment_session_id`. Reject otherwise.
4. On entering `SECURE_CAPTURE`:
   - `PaymentGate` drops `InputAudioRawFrame` and related user-speech frames (VAD start/stop, transcription frames).
   - Recording and transcript persistence are paused.
   - TTS speaks a fixed template: "Please enter your card details in the secure form on your screen. I won't be able to hear you until you're done."
   - The LLM context receives a synthetic system note: "Payment capture in progress. Wait."
5. On leaving: resume audio, and inject only a synthetic message such as `Payment succeeded. ref=PAY-1234, last4=1111` or `Payment failed. reason=declined`.
6. Text-mode sessions follow the same gate: chat input is disabled in the UI and rejected by the server while in `SECURE_CAPTURE`.

## Defense in depth (backstops, not the primary control)

- **`TranscriptScrubber` processor** placed right after ASR: detect 13-19 digit sequences (allowing spaces and dashes, including spelled-out digits like "four one one one") passing a Luhn check, and replace with `[REDACTED_PAN]`. Also redact CVV-like phrases following "cvv", "security code". Emit a metric `scrubber_hits`. In normal operation this should be 0.
- **Log filter:** a `logging.Filter` that applies the same PAN regex to every log record and replaces matches. Log only allowlisted structured fields: `session_id`, `state`, `event`, `tool_name`, `latency_ms`, `status`.
- **No audio persistence:** raw audio is never written to disk by default. If a debug flag `RECORD_AUDIO=1` exists, it must be off by default and automatically paused during `SECURE_CAPTURE`.
- **LLM context hygiene:** tool results are whitelisted to fixed schemas (IDs, amounts, dates, status). No free-text passthrough from external systems into the prompt.
- **Prompt injection:** treat user speech and tool output as untrusted data. The state machine ignores any request in them to change state.

## Payment service isolation (simulated PCI zone)

- Separate process, port, and origin. Own `.env`. No shared imports with voice-agent.
- Holds PAN/CVV/expiry only in request memory during processing. Never writes them to disk or logs. Logs contain `payment_session_id`, `status`, `last4` only.
- Returns to callers: `payment_ref`, `token` (`tok_` + random), `last4`, `status`, `failure_code`.
- Capture page sets strict headers: `Content-Security-Policy: default-src 'self'`, `X-Frame-Options` allowing only the web console origin, `Cache-Control: no-store`, and `autocomplete="off"` on card fields.
- Parent page communicates with the iframe via `postMessage` restricted to exact origins, and receives `{type: "payment_status", status}` only.

## Required tests (`tests/pci_leak/`)

All must pass in CI.

1. **Gate drops audio:** feed synthetic audio frames while state is `SECURE_CAPTURE`. Assert zero frames reach ASR, the router, and the LLM. Assert they reach them again after `PAYMENT_RESULT`.
2. **No state change from model or speech:** simulate LLM output and user text saying "resume" or "gate open". Assert the state does not change.
3. **Webhook auth:** bad signature, unknown session, or replayed event is rejected and state is unchanged.
4. **Scrubber:** table-driven cases for digit strings, spaced, dashed, spoken digits, and CVV phrases. Includes non-card numbers (account ids, amounts) that must **not** be redacted.
5. **Log leak scan:** run a full scripted payment dialogue with the test card, then grep all logs, debug events, and stored transcripts for the PAN, expiry, and CVV. Assert zero matches.
6. **LLM context scan:** capture every message sent to the LLM during the dialogue. Assert none contain any PAN-like Luhn-valid sequence.
7. **Tool result schema:** payment tool results contain only allowlisted keys.
8. **Timeout:** no webhook for 120 s returns the state to `PAYMENT_PENDING` and reopens the gate.
9. **Text mode:** messages sent during `SECURE_CAPTURE` are rejected server-side.

## Out of scope for the POC

Real DTMF/telephony masking, real gateway integration, agent-assisted payment flows, and formal PCI evidence. Note these in `docs/DECISIONS.md` as future work.

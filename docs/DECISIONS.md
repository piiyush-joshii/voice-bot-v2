# Decisions and deviations

Recorded while building the POC against `docs/TASKS.md`. Spec text remains the source of intent; this file is what we actually shipped.

## Phase 0 — environment

- Each Python service has its own `uv` project and `.venv` (Python 3.12). Do not share a single venv: `voice-agent` and `backend-api` both expose an `app` package.
- `uv sync --all-groups` in each of `services/backend-api`, `services/payment-service`, and `services/voice-agent` is the install path. The web console uses `npm install` in `web/`.
- Offline env vars (`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`) are set in `.env` and pinned again when `app.config` loads. Hugging Face cache is forced to `models/hf`.

## LLM tool calling

- Native OpenAI-style `tool_calls` from `phi4-mini` via Ollama was unreliable in smoke tests (inconsistent `tool_calls` entries, extra prose around JSON).
- Default is `LLM_TOOL_MODE=json`: a schema-constrained prompt plus a parser (`OllamaJsonLLM`). The same `ToolExecutor` is used for both modes. Set `LLM_TOOL_MODE=native` to try native tool calls.
- Temperature 0.2. Spoken replies stay 1–3 sentences via the system prompt and deterministic templates.

## ASR: whisper, not Parakeet

- NVIDIA Parakeet realtime EOU 120M is not Apache/MIT, and NeMo is CUDA-oriented. It is not installed.
- Default `ASR_BACKEND=whisper` (`faster-whisper` `small.en`, int8, CPU) with Silero VAD endpointing. The `ASRService` factory still accepts `parakeet` and raises a clear error pointing here.
- Pipecat 1.12 `WhisperSTTService` is not used. Importing `pipecat.services.whisper.stt` on Apple Silicon also imports `mlx_whisper`, which is not installed, and that crashed every voice session before ASR started. `FasterWhisperASR` calls `faster_whisper.WhisperModel` directly.
- If a future Apache/MIT Parakeet export appears, swap it behind the same factory.

## TTS

- Kokoro-82M v1.0 via `kokoro-onnx` / Pipecat `KokoroTTSService`. Weights live in `models/kokoro/` (`kokoro-v1.0.onnx`, `voices-v1.0.bin`). Default voice `af_heart`. Sentence-level streaming is done in `Conversation` (split on `.!?`) before TTS.

## Payment-only voice bot

- The assistant introduces itself as a payment voice bot (`templates.GREETING`), spoken once when the call or text session starts.
- After a successful verify, it always reads the account and the amount due and asks how to proceed. It does not offer a general menu. A clear yes in `AUTHENTICATED` starts `prepare_payment`.

## Payment gate (spec gaps)

- **`PAYMENT_PENDING` entry:** the spec never named a tool that leaves `AUTHENTICATED`. We added `prepare_payment(account_id?, bill_id?, amount?)`. It looks up the bill, optionally accepts a partial amount, moves the gate to `PAYMENT_PENDING`, and speaks a confirmation. `initiate_payment` is only allowed after the orchestrator sees a clear yes (`yes`, `go ahead`, …) in that state. LLM text cannot open the gate.
- **Timeout race:** `payment-service` expires sessions at 120 s and sends a signed `expired` webhook. `voice-agent` has a local timer of 120 s + 5 s grace. Whichever arrives first wins; later events for the same session are ignored (`409` / no-op).
- **`X-Frame-Options`:** `ALLOW-FROM` is obsolete. The capture page uses `Content-Security-Policy: frame-ancestors http://localhost:5173` (and `default-src 'self'`). Capture JS/CSS are same-origin static files, not inline, so CSP does not block the keypad.

## Capture page

- Parent ↔ iframe: `postMessage({type:"payment_status", status}, allowed_frame_origin)` only. Card fields never leave the 8002 origin.
- Invalid Luhn / expiry / CVV stays in `capturing` for up to 3 attempts; the session does not end on a single bad submit.

## Voice transport

- Server: Pipecat 1.12 `SmallWebRTCTransport` + `SmallWebRTCRequestHandler`. `POST /api/offer` accepts `{sdp, type, pc_id?, restart_pc?, session_id}` and returns the SDP answer.
- Browser: a small custom WebRTC client (`getUserMedia` + `RTCPeerConnection`) rather than `@pipecat-ai/client-js`. Pipecat JS client versions move independently of the Python 1.12 server; a 40-line client against the documented offer shape is less brittle. ICE is host-only (no STUN) because everything is localhost.
- Mic is muted client-side in `SECURE_CAPTURE` in addition to the server `PaymentGate` dropping audio frames.

## Logging and PCI

- Structured logs allowlist: `session_id`, `state`, `event`, `tool_name`, `latency_ms`, `status`, plus a few non-sensitive codes (`reason`, `intent`, `path`). A logging filter redacts PAN-like digit runs.
- Debug WebSocket fields are allowlisted in `app/events.py`. Auth secrets in tool args (`verifier`, `code`) are masked. `capture_url` is only sent on `secure_capture`, never in LLM tool results.
- Raw audio is never written. `RECORD_AUDIO=1` is off by default.

## Tests

- Each service's pytest is run from that service directory so `app` resolves correctly (`scripts/test.sh`).
- PCI leak tests 1–9 live in `tests/pci_leak/` and use fake frames / a stub LLM except where noted.
- Scripted dialogues: `tests/e2e/dialogues/*.yaml` (30+). Runner: `tests/e2e/run_dialogues.py` (needs the live stack + Ollama). The runner submits test cards directly to `payment-service`, the same origin the iframe uses.

## Future work (out of scope)

- Real DTMF / telephony audio masking (this POC is browser WebRTC + a hosted form).
- Real card gateway and formal PCI evidence. The payment-service is a simulation.
- Agent-assisted payments (warm transfer of a payment session).
- LoRA / fine-tune of the tool schema on Phi-4-mini.
- Side-by-side eval of SmolLM3-3B vs Phi-4-mini on `tests/e2e/dialogues`.
- Apache/MIT streaming ASR with a native end-of-utterance head, if one appears.

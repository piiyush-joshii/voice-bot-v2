# Build Plan

Work phase by phase. Do not start a phase until the previous phase's acceptance criteria pass. Tick boxes as you go, and record deviations in `docs/DECISIONS.md`.

## Phase 0: Scaffold and environment

- [x] Create the repo layout from `docs/ARCHITECTURE.md`. Use `uv` with `pyproject.toml` for each Python service, pinned versions.
- [x] `.env.example`, `scripts/dev.sh`, `scripts/download_models.sh` (pulls Silero VAD, MiniLM, Kokoro, and faster-whisper weights into `models/`, then instructs to set offline env vars).
- [x] Smoke test: `ollama run phi4-mini` responds, and a tool-calling call via `http://localhost:11434/v1` returns a `tool_calls` entry. Record the result in `DECISIONS.md`.
- [x] `docs/DECISIONS.md` created.

**Accept:** all `/health` endpoints respond, and the LLM tool-calling smoke test passes (or the JSON fallback is chosen and documented).

## Phase 1: Backend mocks

- [x] `backend-api` per `docs/API_SPEC.md` with seed data and an outbox.
- [x] `payment-service` with session creation, capture page, Luhn/expiry/CVV validation, mock gateway, tokens, signed webhook, strict headers.
- [x] Unit tests for both, including "no card data in logs or responses".

**Accept:** with `curl`, complete a payment session using the hosted page in a browser and receive a signed webhook at a local test receiver.

## Phase 2: State machine, gate, and tools (text only, no models)

- [x] `gate/` state machine and `PaymentGate` processor with all transitions from `docs/PAYMENT_GATE_AND_PCI.md`.
- [x] Tool executor with per-state allowlist and schema-validated results.
- [x] `/internal/payment-events` with HMAC, timestamp, and replay protection.
- [x] `TranscriptScrubber` and the logging filter.
- [x] PCI leak tests 1, 2, 3, 4, 7, 8 passing using fake frames and a stub LLM.

**Accept:** `pytest tests/pci_leak` passes for the listed tests.

## Phase 3: Brain in text mode

- [x] `LLM` service against Ollama, system prompt, tool schemas.
- [x] MiniLM `IntentRouter` with `data/intents.yaml` and the router eval script.
- [x] Text WebSocket, `/sessions`, debug WebSocket events.
- [x] Scripted dialogues in `tests/e2e/dialogues/` (start with 10, grow to 30+).
- [x] PCI leak tests 5, 6, 9 passing (log scan, LLM context scan, text-mode rejection).

**Accept:** a full text-mode payment dialogue passes end to end via WebSocket. Tool-call accuracy on the dialogue set is reported in a markdown table under `docs/EVAL.md`.

## Phase 4: Web console (text mode)

- [x] Scaffold the Vite app and implement all panels from `docs/FRONTEND.md` that do not need audio.
- [x] Secure payment iframe with `postMessage` handling.
- [x] Scenario runner with the scripted dialogues.

**Accept:** the frontend definition of done for Text mode is met, and the browser makes requests only to `localhost` hosts.

## Phase 5: Voice

- [x] Silero VAD integration, with barge-in.
- [x] ASR wrapper: faster-whisper `small.en`, with Silero VAD turn ending.
- [x] Kokoro TTS wrapper with sentence-level streaming.
- [x] SmallWebRTC (or minimal audio WebSocket) transport, and the browser voice client.
- [x] Latency taps and the latency panel.
- [x] Gate integration with audio: drop user audio in `SECURE_CAPTURE`, and mute the mic client-side.
- [ ] PCI leak test 1 with real audio frames.

**Accept:** hold a spoken conversation, complete a payment by voice using the iframe, and observe "Audio to model: CLOSED" during capture. Report measured latencies in `docs/EVAL.md`.

## Phase 6: Hardening

- [x] Timeouts, cancel, decline, and insufficient-funds paths in both modes.
- [x] Spoken-card-number attempt: the assistant interrupts politely, and scrubber hits are logged without the digits.
- [ ] Verify offline operation: disable Wi-Fi, run the full flow.
- [ ] Verify no outbound connections other than localhost (`lsof -i` or a network monitor while running).
- [x] Write `docs/DECISIONS.md` future-work notes: real DTMF/telephony masking, real gateway, agent-assisted payments, PCI evidence, model fine-tuning (LoRA on the tool schema), and comparing SmolLM3-3B against Phi-4-mini.

**Accept:** the full test suite (`pytest`, `npm run build`, `npm run lint`) is green, and the offline run succeeds.

## Definition of done (whole POC)

1. Voice and text journeys work: authenticate, bill lookup, history, pay, receipt, agent handoff.
2. The gate provably keeps card data out of ASR, LLM, transcripts, and logs (all 9 leak tests pass).
3. Everything runs locally and offline after the one-time model download.
4. `docs/EVAL.md` contains latency numbers, router accuracy, and tool-call accuracy.
5. `docs/DECISIONS.md` lists every deviation and fallback used.

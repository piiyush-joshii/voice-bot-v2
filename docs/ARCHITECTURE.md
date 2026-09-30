# Architecture

## Design principle

**Handoff, don't handle.** The conversational layer collects intent and confirms amounts. Card capture happens in a separate service. The conversational layer only ever sees IDs, tokens, and status.

## Components

| Service | Port | Zone | Responsibility |
|---|---|---|---|
| `web` (React test console) | 5173 | Out of PCI scope | Mic/text UI, transcript, state and debug panels, embeds the payment iframe |
| `voice-agent` (Pipecat) | 7860 | Out of PCI scope | Voice/text pipeline, brain, tool execution, payment gate, debug event stream |
| `backend-api` (FastAPI) | 8001 | Out of PCI scope | Mock auth, billing, notifications, payment records |
| `payment-service` (FastAPI) | 8002 | **Simulated PCI zone** | Hosted capture page (keypad + form), Luhn check, mock gateway, tokens, signed webhooks |
| Ollama | 11434 | Local | Serves `phi4-mini` |

The web console and payment-service run on **different origins** (5173 vs 8002). The payment page is embedded via `<iframe>`, so the parent page cannot read what is typed into it.

## Data flow: bill payment

```
Browser mic ──WebRTC──▶ voice-agent
                          │ VAD → PaymentGate(open) → ASR → Router → LLM
                          │                                   │ tool: get_bill
                          │                                   ▼
                          │                              backend-api
                          │ tool: initiate_payment
                          ▼
                    payment-service  ◀── creates payment session, returns capture_url
                          │
voice-agent: gate → SECURE_CAPTURE (audio to ASR dropped, recording paused)
voice-agent ──debug WS──▶ web: {state: SECURE_CAPTURE, capture_url}
web: shows iframe(capture_url)   ← caller enters test card in the iframe only
                          │
payment-service: validate, mock-gateway charge, mint token
                          │ signed webhook {status, payment_ref, token, last4}
                          ▼
voice-agent /internal/payment-events → gate → PAYMENT_RESULT (audio resumes)
LLM sees only: "Payment succeeded, ref PAY-1234"
```

## What crosses each boundary

| From → To | Allowed content |
|---|---|
| web → voice-agent | Audio (only while gate open), text messages |
| voice-agent → LLM/ASR/logs | Scrubbed text, tool calls and results (IDs, amounts, status) |
| voice-agent → payment-service | account_id, amount, callback URL |
| payment-service → voice-agent | status, payment_ref, token, last4 |
| web iframe → web parent | `postMessage` with `{status}` only, never card fields |

Anything containing PAN, expiry, or CVV exists **only** inside payment-service memory and its iframe.

## Repo layout

```
ebpp-voice-poc/
├── README.md
├── docs/                      # these specs (+ DECISIONS.md created during build)
├── .env.example
├── scripts/
│   ├── dev.sh
│   └── download_models.sh
├── services/
│   ├── voice-agent/
│   │   ├── pyproject.toml
│   │   └── app/
│   │       ├── main.py
│   │       ├── config.py
│   │       ├── pipeline.py            # builds the Pipecat pipeline
│   │       ├── gate/                  # PaymentGate + state machine
│   │       ├── processors/            # scrubber, router, metrics taps
│   │       ├── services/              # speech (faster-whisper, Kokoro), embedder.py
│   │       ├── brain/                 # system prompt, tool schemas, tool executor
│   │       ├── api/                   # sessions, debug WS, payment-events webhook
│   │       └── logging_utils.py       # allowlisted structured logging
│   ├── backend-api/
│   │   └── app/                       # main.py, routes/, mock_data.py
│   └── payment-service/
│       └── app/                       # main.py, gateway_mock.py, luhn.py, templates/capture.html
├── web/                               # Vite + React + TypeScript
└── tests/
    ├── unit/
    ├── pci_leak/                      # gate and log leak tests
    └── e2e/                           # scripted dialogues
```

## Configuration (`.env.example`)

```
# Models
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=phi4-mini
ASR_BACKEND=whisper
TTS_BACKEND=kokoro
EMBED_MODEL=sentence-transformers/all-MiniLM-L6-v2
KOKORO_VOICE=af_heart

# Offline enforcement
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1

# Services
BACKEND_API_URL=http://localhost:8001
PAYMENT_SERVICE_URL=http://localhost:8002
VOICE_AGENT_URL=http://localhost:7860

# Security (POC values, not secrets)
WEBHOOK_HMAC_SECRET=dev-only-change-me
```

## Latency

Targets to measure and report: end-of-speech to first TTS audio under 1.5 s for router-handled turns, under 3 s for language-model turns.

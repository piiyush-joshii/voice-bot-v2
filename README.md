# EBPP Voice Agent POC (100% Local)

A local proof of concept for a conversational EBPP (Electronic Bill Presentment and Payment) agent that supports self-service journeys by voice and text, while keeping all cardholder data out of the AI path.

**Read the docs in this order:**

1. `docs/ARCHITECTURE.md` - components, ports, data flow, repo layout
2. `docs/PAYMENT_GATE_AND_PCI.md` - the most important design constraint
3. `docs/VOICE_PIPELINE.md` - models, processors, brain design, tools
4. `docs/API_SPEC.md` - endpoints for all three services
5. `docs/FRONTEND.md` - web test console
6. `docs/TASKS.md` - phased build plan with acceptance criteria

## Goals

- Caller can authenticate, hear their bill, ask about history, pay a bill, get a receipt, or ask for a human, by voice or text.
- **Card data never reaches the ASR, LLM, transcripts, logs, or recordings.** Payment capture happens in a separate simulated "PCI zone" service.


## Model stack

| Role | Model | Runtime |
|---|---|---|
| ASR | faster-whisper `small.en` | local, int8, CPU |
| Brain (reasoning + tool calling) | Phi-4-mini (3.8B) | Ollama (`phi4-mini`) |
| Intent router / FAQ retrieval | all-MiniLM-L6-v2 (22M) | sentence-transformers, local |
| TTS | Kokoro-82M v1.0 | `kokoro` package or `kokoro-onnx`, local |
| VAD | Silero VAD | local |
| Framework | Pipecat | Python |

## Prerequisites

```bash
# Ollama already installed
ollama pull phi4-mini

brew install espeak-ng ffmpeg      # Kokoro and audio deps
brew install uv node               # Python env manager + Node 20+
```

Python 3.11 or 3.12. Use `uv` for every Python service.

## Run (target end state)

```bash
# terminal 1
ollama serve

# terminal 2
cd services/backend-api && uv run uvicorn app.main:app --port 8001

# terminal 3
cd services/payment-service && uv run uvicorn app.main:app --port 8002

# terminal 4
cd services/voice-agent && uv run python -m app.main   # port 7860

# terminal 5
cd web && npm run dev                                   # port 5173
```

Also provide `scripts/dev.sh` that starts everything and `scripts/download_models.sh` that pre-fetches all weights.

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
- Everything runs on one laptop (Apple Silicon M4 MacBook Air is the reference machine).

## Hard constraints (non-negotiable)

1. **Local only.** No cloud APIs, no SaaS, no telemetry, no CDN assets, no remote fonts. Model weights may be downloaded **once** during setup; after that the app must run with the network disabled (`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`).
2. **Permissive licenses only** (Apache 2.0 / MIT). No Chinese-origin models.
3. **No real card data, ever.** Use only the test card numbers in `docs/PAYMENT_GATE_AND_PCI.md`.
4. This POC demonstrates PCI scope-reduction architecture. It is **not** a PCI certification.

## Model stack

| Role | Model | Runtime |
|---|---|---|
| ASR + end-of-utterance | NVIDIA Parakeet realtime EOU 120M | NeMo / ONNX, local (fallback: faster-whisper) |
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

## Rules for the AI coding agent (Cursor)

- Build strictly in the order of `docs/TASKS.md`. Finish each phase's acceptance criteria before starting the next.
- Do not add any dependency that calls a remote service. Check every new package.
- Pin dependency versions. Pipecat's API changes between releases, so **verify class names and signatures against the installed version** instead of assuming.
- Every model wrapper sits behind an interface (`ASRService`, `LLMService`, `TTSService`, `Embedder`) so backends can be swapped by config (`.env`).
- Never log raw audio or unscrubbed transcripts. Log structured events with allowlisted fields only.
- The payment gate is deterministic code. It must never depend on LLM output.
- Write tests alongside code. The PCI leak tests in `docs/PAYMENT_GATE_AND_PCI.md` must pass in CI (`pytest`).
- Prefer small, readable modules. Add a short docstring to every processor explaining what frames it consumes and emits.
- If a spec detail conflicts with reality (a library does not work on Apple Silicon, for example), implement the fallback listed in the docs and note it in `docs/DECISIONS.md`.

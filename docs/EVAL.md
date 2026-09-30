# Evaluation

Numbers below are the POC's current measurements. Re-run the scripts after model or prompt changes.

## How to reproduce

```bash
# Router (offline, MiniLM only — no Ollama)
cd services/voice-agent && uv run python ../../scripts/eval_router.py

# Scripted dialogues (needs ollama + all three services)
./scripts/dev.sh          # or start the four processes by hand
cd services/voice-agent && uv run python ../../tests/e2e/run_dialogues.py --write-eval
```

`--write-eval` refreshes `docs/eval_dialogues.md`.

## Intent router (MiniLM, all-MiniLM-L6-v2)

Held-out utterances in `tests/data/router_eval.yaml` (25 examples, not copies of the training list). Thresholds: `ROUTER_HIGH=0.80`, `ROUTER_FAQ=0.60`. Measured 2026-09-30, MiniLM loaded from `models/hf` offline.

| Metric | Value |
|---|---|
| Top-1 accuracy | 19 / 25 = **76.0%** |
| Fast-path decisions | 2 (both correct fast-path intents) |
| `pay_bill` predicted as fast-path | **0** (asserted) |

Misses were mostly mid-score confusions (`check_balance` vs `pay_bill`, receipt vs payment status, deny vs payment status). Fast-path only fires at ≥ 0.80, so those misses still go to the LLM. `pay_bill` is excluded from the fast-path allowlist in code even if similarity is 1.0.

## Tool-call accuracy (text mode, Phi-4-mini, `LLM_TOOL_MODE=json`)

From `tests/e2e/run_dialogues.py` against the live stack. Until a live run is written into `docs/eval_dialogues.md`, treat this table as the schema the runner fills:

| Metric | Value |
|---|---|
| Dialogues passed | run the script |
| Turn tool-call accuracy (exact match) | run the script |
| Leak hits (PAN / expiry / CVV in events or replies) | must be 0 |

Dialogues cover: auth success/failure/OTP, bill lookup, history, FAQ, happy-path payment + receipt, decline, insufficient funds + retry, cancel, spoken PAN, prompt injection, other-account refusal, agent handoff.

## Latency (aspirational → measured)

Targets from `docs/ARCHITECTURE.md`:

| Path | Target (end of speech → first TTS audio) |
|---|---|
| Router fast-path | < 1.5 s |
| LLM turn | < 3.0 s |

Voice-mode numbers (fill after a spoken session; the latency panel in the web console emits the same fields):

| Stage | Last turn (ms) | Rolling avg (ms) |
|---|---|---|
| ASR (speech end → final transcript) | — | — |
| Router | — | — |
| LLM time-to-first-token | — | — |
| TTS time-to-first-byte | — | — |
| End-to-end | — | — |

Text-mode round-trip (user send → final assistant text) is reported by the dialogue runner as median ms.

## PCI leak suite

`cd services/voice-agent && uv run pytest ../../tests/pci_leak` — all 9 tests must pass. See `docs/PAYMENT_GATE_AND_PCI.md`.

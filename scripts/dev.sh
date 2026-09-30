#!/usr/bin/env bash
# Starts Ollama (if not running), backend-api, payment-service, voice-agent, and the web console.
# Logs go to ./logs. Ctrl-C stops everything.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOGS="$ROOT/logs"
mkdir -p "$LOGS"
[ -f "$ROOT/.env" ] || cp "$ROOT/.env.example" "$ROOT/.env"

pids=()
cleanup() {
  echo; echo "Stopping..."
  for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

start() {
  local name="$1"; shift
  echo "==> $name (log: logs/$name.log)"
  ("$@" >"$LOGS/$name.log" 2>&1) &
  pids+=($!)
}

wait_for() {
  local url="$1" name="$2"
  for _ in $(seq 1 120); do
    curl -sf "$url" >/dev/null 2>&1 && { echo "    $name ready"; return 0; }
    sleep 0.5
  done
  echo "    $name did not become ready; see logs/$name.log" >&2
  return 1
}

if ! curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
  start ollama ollama serve
  wait_for http://localhost:11434/api/tags ollama
fi

export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
start backend-api bash -c "cd '$ROOT/services/backend-api' && exec uv run uvicorn app.main:app --host 127.0.0.1 --port 8001"
start payment-service bash -c "cd '$ROOT/services/payment-service' && exec uv run uvicorn app.main:app --host 127.0.0.1 --port 8002"
wait_for http://localhost:8001/health backend-api
wait_for http://localhost:8002/health payment-service
start voice-agent bash -c "cd '$ROOT/services/voice-agent' && exec uv run python -m app.main"
wait_for http://localhost:7860/health voice-agent
start web bash -c "cd '$ROOT/web' && exec npm run dev -- --host localhost --port 5173 --strictPort"
wait_for http://localhost:5173 web

echo
echo "All services up. Open http://localhost:5173"
echo "Mock accounts: ACC1001 (verifier 4321), ACC1002 (1234), ACC1003 (5678). OTP 123456."
echo "Test card: 4111 1111 1111 1111 (declined 4000 0000 0000 0002, insufficient 4000 0000 0000 9995)."
wait

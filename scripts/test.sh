#!/usr/bin/env bash
# Runs every test suite in its own service venv (each service has its own `app` package).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1

echo "==> backend-api"
(cd "$ROOT/services/backend-api" && uv run pytest -q ../../tests/unit/backend_api)
echo "==> payment-service"
(cd "$ROOT/services/payment-service" && uv run pytest -q ../../tests/unit/payment_service)
echo "==> voice-agent (unit + PCI leak tests)"
(cd "$ROOT/services/voice-agent" && uv run pytest -q ../../tests/unit/voice_agent ../../tests/pci_leak)

if [ -d "$ROOT/web/node_modules" ]; then
  echo "==> web (lint + build)"
  (cd "$ROOT/web" && npm run lint && npm run build)
fi

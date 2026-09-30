#!/usr/bin/env bash
# One-time model download into ./models. After this, run with HF_HUB_OFFLINE=1 / TRANSFORMERS_OFFLINE=1.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODELS="$ROOT/models"
mkdir -p "$MODELS/hf" "$MODELS/kokoro"

echo "==> Ollama: phi4-mini"
if command -v ollama >/dev/null 2>&1; then
  ollama pull phi4-mini
else
  echo "   ollama not found; install it and run: ollama pull phi4-mini" >&2
fi

echo "==> Kokoro-82M v1.0 (ONNX + voices)"
KOKORO_BASE="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
[ -f "$MODELS/kokoro/kokoro-v1.0.onnx" ] || curl -L --fail -o "$MODELS/kokoro/kokoro-v1.0.onnx" "$KOKORO_BASE/kokoro-v1.0.onnx"
[ -f "$MODELS/kokoro/voices-v1.0.bin" ] || curl -L --fail -o "$MODELS/kokoro/voices-v1.0.bin" "$KOKORO_BASE/voices-v1.0.bin"

echo "==> Hugging Face models (MiniLM embedder, faster-whisper small.en)"
cd "$ROOT/services/voice-agent"
HF_HOME="$MODELS/hf" HF_HUB_OFFLINE=0 TRANSFORMERS_OFFLINE=0 uv run python - <<'EOF'
from sentence_transformers import SentenceTransformer
from faster_whisper.utils import download_model

SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
print("MiniLM ready")
download_model("small.en")
print("faster-whisper small.en ready")
EOF

echo "==> Silero VAD: bundled with pipecat-ai (no download needed)"
echo
echo "Done. Models are in $MODELS."
echo "Keep HF_HUB_OFFLINE=1 and TRANSFORMERS_OFFLINE=1 in .env so nothing is fetched at runtime."

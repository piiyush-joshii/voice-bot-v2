"""voice-agent settings.

Importing this module loads the repo-root .env and pins the Hugging Face cache to ./models,
so it must be imported before any model library.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVICE_DIR.parents[1]
DATA_DIR = SERVICE_DIR / "data"


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.split(" #", 1)[0].strip()
        os.environ.setdefault(key.strip(), value)


_load_env_file(REPO_ROOT / ".env")


def _models_dir() -> Path:
    raw = os.environ.get("MODELS_DIR", "../../models")
    path = Path(raw)
    return path if path.is_absolute() else (SERVICE_DIR / path).resolve()


MODELS_DIR = _models_dir()
os.environ.setdefault("HF_HOME", str(MODELS_DIR / "hf"))
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass
class Settings:
    llm_base_url: str = field(default_factory=lambda: _env("LLM_BASE_URL", "http://localhost:11434").rstrip("/"))
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", "phi4-mini"))
    llm_tool_mode: str = field(default_factory=lambda: _env("LLM_TOOL_MODE", "json"))
    asr_backend: str = field(default_factory=lambda: _env("ASR_BACKEND", "whisper"))
    whisper_model: str = field(default_factory=lambda: _env("WHISPER_MODEL", "small.en"))
    tts_backend: str = field(default_factory=lambda: _env("TTS_BACKEND", "kokoro"))
    kokoro_voice: str = field(default_factory=lambda: _env("KOKORO_VOICE", "af_heart"))
    embed_model: str = field(default_factory=lambda: _env("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2"))
    router_high: float = field(default_factory=lambda: float(_env("ROUTER_HIGH", "0.80")))
    router_faq: float = field(default_factory=lambda: float(_env("ROUTER_FAQ", "0.60")))
    backend_api_url: str = field(default_factory=lambda: _env("BACKEND_API_URL", "http://localhost:8001"))
    payment_service_url: str = field(default_factory=lambda: _env("PAYMENT_SERVICE_URL", "http://localhost:8002"))
    voice_agent_url: str = field(default_factory=lambda: _env("VOICE_AGENT_URL", "http://localhost:7860"))
    web_origin: str = field(default_factory=lambda: _env("WEB_ORIGIN", "http://localhost:5173"))
    capture_timeout_seconds: float = field(default_factory=lambda: float(_env("CAPTURE_TIMEOUT_SECONDS", "120")))
    capture_timeout_grace_seconds: float = 5.0
    webhook_secret: bytes = field(default_factory=lambda: _env("WEBHOOK_HMAC_SECRET", "dev-only-change-me").encode())
    webhook_max_age_seconds: int = 300
    record_audio: bool = field(default_factory=lambda: _env("RECORD_AUDIO", "0") == "1")
    models_dir: Path = MODELS_DIR


settings = Settings()

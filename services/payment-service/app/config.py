"""payment-service settings. Reads its own .env (services/payment-service/.env) plus the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parents[1]


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_env_file(SERVICE_DIR / ".env")


def _csv(name: str, default: str) -> list[str]:
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


@dataclass
class Settings:
    webhook_secret: bytes = field(
        default_factory=lambda: os.environ.get("WEBHOOK_HMAC_SECRET", "dev-only-change-me").encode()
    )
    public_url: str = field(default_factory=lambda: os.environ.get("PAYMENT_SERVICE_URL", "http://localhost:8002"))
    allowed_frame_origins: list[str] = field(
        default_factory=lambda: _csv("ALLOWED_FRAME_ORIGINS", "http://localhost:5173")
    )
    allowed_callback_hosts: list[str] = field(
        default_factory=lambda: _csv("ALLOWED_CALLBACK_HOSTS", "localhost,127.0.0.1")
    )
    session_ttl_seconds: float = field(default_factory=lambda: float(os.environ.get("SESSION_TTL_SECONDS", "120")))
    max_attempts: int = 3


settings = Settings()

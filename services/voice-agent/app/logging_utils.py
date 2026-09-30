"""Allowlisted structured logging.

Only fields in ALLOWED_FIELDS are ever written. Every record also passes through the PAN
scrubber, and Pipecat's loguru output is capped at INFO and scrubbed the same way.
"""

from __future__ import annotations

import json
import logging
import sys
from collections import deque

from app.processors.scrubber import redact_for_logs

ALLOWED_FIELDS = (
    "session_id", "state", "event", "tool_name", "latency_ms", "status",
    "intent", "score", "path", "reason", "count", "mode", "from_state", "to_state",
)

_logger = logging.getLogger("voice_agent")


class PanRedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_for_logs(str(record.msg))
        if isinstance(record.args, tuple):
            record.args = tuple(redact_for_logs(a) if isinstance(a, str) else a for a in record.args)
        return True


class JsonEventFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {"ts": round(record.created, 3), "level": record.levelname, "logger": record.name,
                   "msg": record.getMessage()}
        for key in ALLOWED_FIELDS:
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        return redact_for_logs(json.dumps(payload, default=str))


class MemoryHandler(logging.Handler):
    """Keeps recent formatted records in memory so tests can scan everything that was logged."""

    def __init__(self, capacity: int = 5000):
        super().__init__()
        self.records: deque[str] = deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(self.format(record))


memory_handler = MemoryHandler()
_configured = False


def configure_logging(level: int = logging.INFO) -> None:
    global _configured
    if _configured:
        return
    _configured = True
    formatter = JsonEventFormatter()
    redactor = PanRedactingFilter()
    stream = logging.StreamHandler(sys.stderr)
    for handler in (stream, memory_handler):
        handler.setFormatter(formatter)
        handler.addFilter(redactor)
    root = logging.getLogger()
    root.handlers = [stream, memory_handler]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
    for noisy in ("httpx", "httpcore", "aioice", "aiortc", "sentence_transformers", "faster_whisper"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _configure_loguru()


def _configure_loguru() -> None:
    """Pipecat logs through loguru, and its DEBUG output includes transcript and TTS text."""
    try:
        from loguru import logger as loguru_logger
    except ImportError:
        return

    def sink(message) -> None:
        record = message.record
        text = redact_for_logs(record["message"])
        line = json.dumps({"ts": round(record["time"].timestamp(), 3), "level": record["level"].name,
                           "logger": f"pipecat.{record['name']}", "msg": text})
        sys.stderr.write(line + "\n")
        memory_handler.records.append(line)

    loguru_logger.remove()
    loguru_logger.add(sink, level="INFO")


def log_event(event: str, **fields) -> None:
    extra = {k: v for k, v in fields.items() if k in ALLOWED_FIELDS}
    extra["event"] = event
    _logger.info(event, extra=extra)

"""Logging for the PCI zone: allowlisted fields only, plus a PAN-redacting backstop filter."""

from __future__ import annotations

import logging
import re

ALLOWED_FIELDS = ("payment_session_id", "status", "last4", "failure_code", "http_status", "attempt")
PAN_LIKE = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")


class PanRedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = PAN_LIKE.sub("[REDACTED_PAN]", str(record.msg))
        if isinstance(record.args, tuple):
            record.args = tuple(PAN_LIKE.sub("[REDACTED_PAN]", a) if isinstance(a, str) else a
                                for a in record.args)
        return True


class AllowlistFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = " ".join(f"{k}={getattr(record, k)}" for k in ALLOWED_FIELDS if hasattr(record, k))
        return f"{base} {extras}".rstrip()


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(AllowlistFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    handler.addFilter(PanRedactingFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True

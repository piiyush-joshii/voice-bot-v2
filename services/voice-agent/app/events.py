"""Per-session debug event stream for the web console.

Only allowlisted event types and fields are emitted. Transcript text is scrubbed again here,
tool arguments that are authentication secrets are masked, and nothing from payment capture
other than status, payment_ref, and last4 is ever accepted.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque

from app.processors.scrubber import scrub_text

EVENT_FIELDS: dict[str, set[str]] = {
    "state_changed": {"from", "to", "reason"},
    "gate_status": {"audio_to_model", "recording", "frames_dropped"},
    "transcript": {"role", "text", "scrubbed", "final"},
    "router": {"intent", "score", "path"},
    "tool_call": {"name", "args"},
    "tool_result": {"name", "result"},
    "secure_capture": {"capture_url", "expires_at", "payment_session_id"},
    "payment_result": {"status", "payment_ref", "last4", "failure_code"},
    "latency": {"asr_ms", "router_ms", "llm_ttft_ms", "tts_ttfb_ms", "e2e_ms"},
    "leak_counters": {"scrubber_hits", "frames_dropped_secure"},
    "handoff": {"handoff_id", "summary"},
    "notice": {"level", "message"},
}
MASKED_ARGS = {"verifier", "code"}


def mask_args(args: dict) -> dict:
    return {k: ("****" if k in MASKED_ARGS and v else v) for k, v in (args or {}).items()}


class EventBus:
    def __init__(self, history: int = 500):
        self._subscribers: set[asyncio.Queue] = set()
        self.history: deque[dict] = deque(maxlen=history)

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def emit(self, event_type: str, **fields) -> dict:
        allowed = EVENT_FIELDS.get(event_type)
        if allowed is None:
            raise ValueError(f"unknown debug event type: {event_type}")
        event = {k: v for k, v in fields.items() if k in allowed}
        if event_type == "transcript":
            event["text"] = scrub_text(str(event.get("text", ""))).text
            event["scrubbed"] = True
        if event_type == "tool_call":
            event["args"] = mask_args(event.get("args", {}))
        event = {"type": event_type, **event, "ts": round(time.time(), 3)}
        self.history.append(event)
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass
        return event

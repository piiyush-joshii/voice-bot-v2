"""LLM service interface and the Ollama implementations.

Default mode is schema-constrained JSON (Ollama `format`): the model returns
{"action": "call_tool"|"reply", "tool": ..., "args": {...}, "reply": "..."}. The tool enum in the
schema contains only the tools allowed in the current gate state. Native OpenAI-style tool calling
is available behind LLM_TOOL_MODE=native (see docs/DECISIONS.md for why it is not the default).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Protocol

import httpx

ReplyDelta = Callable[[str], Awaitable[None]]


@dataclass
class Decision:
    action: str  # "call_tool" | "reply"
    tool: str | None = None
    args: dict = field(default_factory=dict)
    reply: str = ""
    ttft_ms: float = 0.0
    raw: str = ""


class LLMService(Protocol):
    async def decide(self, messages: list[dict], tools: list[str], on_reply_delta: ReplyDelta | None = None) -> Decision:
        ...


def decision_schema(tools: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["call_tool", "reply"] if tools else ["reply"]},
            "tool": {"type": "string", "enum": sorted(tools) + ["none"]},
            "args": {"type": "object"},
            "reply": {"type": "string"},
        },
        "required": ["action", "tool", "args", "reply"],
    }


class _ReplyStreamer:
    """Incrementally extracts the JSON string value of "reply" from a streaming JSON document."""

    def __init__(self) -> None:
        self._buf = ""
        self._pos: int | None = None
        self._done = False
        self._escape = False

    def feed(self, chunk: str) -> str:
        self._buf += chunk
        if self._done:
            return ""
        if self._pos is None:
            key = self._buf.find('"reply"')
            if key < 0:
                return ""
            colon = self._buf.find(":", key + 7)
            if colon < 0:
                return ""
            quote = self._buf.find('"', colon + 1)
            if quote < 0:
                return ""
            self._pos = quote + 1
        out = []
        while self._pos < len(self._buf):
            ch = self._buf[self._pos]
            self._pos += 1
            if self._escape:
                out.append({"n": " ", "t": " ", '"': '"', "\\": "\\", "/": "/"}.get(ch, ""))
                self._escape = False
            elif ch == "\\":
                self._escape = True
            elif ch == '"':
                self._done = True
                break
            else:
                out.append(ch)
        return "".join(out)


class OllamaJsonLLM:
    def __init__(self, base_url: str, model: str, temperature: float = 0.2, max_tokens: int = 200,
                 on_request: Callable[[list[dict]], None] | None = None):
        self._url = f"{base_url}/api/chat"
        self._model = model
        self._options = {"temperature": temperature, "num_predict": max_tokens}
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=5.0))
        self.on_request = on_request

    async def warmup(self) -> None:
        try:
            await self._client.post(self._url, json={"model": self._model, "messages": [], "keep_alive": "30m"})
        except httpx.HTTPError:
            pass

    async def decide(self, messages: list[dict], tools: list[str], on_reply_delta: ReplyDelta | None = None) -> Decision:
        if self.on_request:
            self.on_request(messages)
        body = {"model": self._model, "messages": messages, "stream": True, "format": decision_schema(tools),
                "options": self._options, "keep_alive": "30m"}
        t0 = time.perf_counter()
        ttft = 0.0
        raw = ""
        streamer = _ReplyStreamer()
        action_known: str | None = None
        async with self._client.stream("POST", self._url, json=body) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                data = json.loads(line)
                chunk = data.get("message", {}).get("content", "")
                if chunk and not ttft:
                    ttft = (time.perf_counter() - t0) * 1000
                raw += chunk
                if action_known is None and '"action"' in raw:
                    if '"reply"' in raw.split('"action"', 1)[1][:20]:
                        action_known = "reply"
                    elif '"call_tool"' in raw.split('"action"', 1)[1][:20]:
                        action_known = "call_tool"
                delta = streamer.feed(chunk)
                if delta and action_known == "reply" and on_reply_delta:
                    await on_reply_delta(delta)
                if data.get("done"):
                    break
        return parse_decision(raw, tools, ttft)


def parse_decision(raw: str, tools: list[str], ttft_ms: float = 0.0) -> Decision:
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return Decision("reply", reply="", ttft_ms=ttft_ms, raw=raw)
    action = obj.get("action", "reply")
    tool = obj.get("tool")
    args = obj.get("args") if isinstance(obj.get("args"), dict) else {}
    reply = str(obj.get("reply") or "")
    if action == "call_tool" and tool in tools:
        return Decision("call_tool", tool, args, reply, ttft_ms, raw)
    return Decision("reply", None, {}, reply, ttft_ms, raw)


class OllamaNativeToolsLLM:
    """OpenAI-compatible tool calling via Ollama /v1. Kept for model comparisons."""

    def __init__(self, base_url: str, model: str, tool_specs: dict[str, dict], temperature: float = 0.2,
                 on_request: Callable[[list[dict]], None] | None = None):
        self._url = f"{base_url}/v1/chat/completions"
        self._model = model
        self._specs = tool_specs
        self._temperature = temperature
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=5.0))
        self.on_request = on_request

    async def warmup(self) -> None:
        return None

    async def decide(self, messages: list[dict], tools: list[str], on_reply_delta: ReplyDelta | None = None) -> Decision:
        if self.on_request:
            self.on_request(messages)
        body = {"model": self._model, "messages": messages, "temperature": self._temperature,
                "tools": [self._specs[t] for t in tools if t in self._specs]}
        t0 = time.perf_counter()
        resp = await self._client.post(self._url, json=body)
        resp.raise_for_status()
        ttft = (time.perf_counter() - t0) * 1000
        msg = resp.json()["choices"][0]["message"]
        for call in msg.get("tool_calls") or []:
            name = call["function"]["name"]
            try:
                args = json.loads(call["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            if name in tools and "properties" not in args:
                return Decision("call_tool", name, args, "", ttft)
        text = msg.get("content") or ""
        if text and on_reply_delta:
            await on_reply_delta(text)
        return Decision("reply", reply=text, ttft_ms=ttft)

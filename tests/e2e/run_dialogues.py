"""Runs scripted dialogues (tests/e2e/dialogues/*.yaml) against the live local stack in text mode.

Requires backend-api (8001), payment-service (8002), voice-agent (7860), and Ollama running.
The runner plays the browser's role for the secure form: it submits the test card directly to
payment-service (same as the iframe would), never to the voice-agent.

    cd services/voice-agent && uv run python ../../tests/e2e/run_dialogues.py [--write-eval] [name ...]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import websockets
import yaml

ROOT = Path(__file__).resolve().parents[2]
DIALOGUES = Path(__file__).parent / "dialogues"
VOICE = "http://localhost:7860"
BACKEND = "http://localhost:8001"
PAYMENT = "http://localhost:8002"
CARD_VALUES = ("4111111111111111", "4000000000000002", "4000000000009995", "12/30", "11/29")


@dataclass
class TurnReport:
    user: str
    expected: list[str] | None
    called: list[str]
    state: str
    ok: bool
    notes: list[str] = field(default_factory=list)
    ms: float = 0.0


@dataclass
class DialogueReport:
    name: str
    turns: list[TurnReport]
    passed: bool
    leaks: list[str]
    final_state: str


class Session:
    def __init__(self):
        self.events: list[dict] = []
        self.assistant: list[str] = []
        self.state = "UNAUTHENTICATED"

    async def open(self, http: httpx.AsyncClient):
        body = (await http.post(f"{VOICE}/sessions", json={"mode": "text"})).json()
        self.sid = body["session_id"]
        self.text_ws = await websockets.connect(body["ws_text_url"])
        self.debug_ws = await websockets.connect(body["ws_debug_url"])
        self._debug_task = asyncio.create_task(self._pump_debug())
        await self._drain_opening()

    async def _drain_opening(self):
        """The bot speaks first. Drop that line so the first user turn is scored on its own reply."""
        while True:
            try:
                msg = json.loads(await asyncio.wait_for(self.text_ws.recv(), timeout=0.6))
            except asyncio.TimeoutError:
                return
            if msg.get("type") == "assistant_text" and msg.get("final"):
                self.assistant.append(msg["text"])

    async def _pump_debug(self):
        async for raw in self.debug_ws:
            ev = json.loads(raw)
            self.events.append(ev)
            if ev["type"] == "state_changed":
                self.state = ev["to"]

    async def say(self, text: str, timeout: float = 90) -> tuple[list[str], str]:
        mark = len(self.events)
        await self.text_ws.send(json.dumps({"type": "user_text", "text": text}))
        replies = []
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = json.loads(await asyncio.wait_for(self.text_ws.recv(), timeout=deadline - time.time()))
            if msg["type"] == "rejected":
                return [], "rejected"
            if msg.get("final"):
                replies.append(msg["text"])
                break
        # Some turns speak twice (e.g. verify then follow-up). Drain briefly.
        while True:
            try:
                msg = json.loads(await asyncio.wait_for(self.text_ws.recv(), timeout=0.4))
                if msg.get("final"):
                    replies.append(msg["text"])
            except asyncio.TimeoutError:
                break
        await asyncio.sleep(0.1)
        self.assistant.extend(replies)
        called = [e["name"] for e in self.events[mark:] if e["type"] == "tool_call"]
        return called, " ".join(replies)

    def capture_url(self) -> str | None:
        for ev in reversed(self.events):
            if ev["type"] == "secure_capture":
                return ev["capture_url"]
        return None

    async def wait_for_state(self, states: set[str], timeout: float = 15) -> str:
        deadline = time.time() + timeout
        while time.time() < deadline and self.state not in states:
            await asyncio.sleep(0.1)
        return self.state

    async def drain_assistant(self, timeout: float = 3.0):
        end = time.time() + timeout
        while time.time() < end:
            try:
                msg = json.loads(await asyncio.wait_for(self.text_ws.recv(), timeout=0.5))
                if msg.get("final"):
                    self.assistant.append(msg["text"])
                    return
            except asyncio.TimeoutError:
                continue

    async def close(self):
        self._debug_task.cancel()
        await self.text_ws.close()
        await self.debug_ws.close()


def find_leaks(blob: str) -> list[str]:
    compact = re.sub(r"[ -]", "", blob)
    return [v for v in CARD_VALUES if v in compact or v in blob]


def load_specs(paths: list[Path]) -> list[dict]:
    specs = []
    for path in paths:
        data = yaml.safe_load(path.read_text())
        specs.extend(data if isinstance(data, list) else [data])
    return specs


async def run_dialogue(spec: dict, http: httpx.AsyncClient) -> DialogueReport:
    await http.post(f"{BACKEND}/admin/reset")
    s = Session()
    await s.open(http)
    await asyncio.sleep(0.2)
    reports: list[TurnReport] = []
    passed = True
    for turn in spec["turns"]:
        if "card" in turn or "cancel" in turn:
            url = s.capture_url()
            notes = []
            if not url:
                reports.append(TurnReport("[secure form]", None, [], s.state, False, ["no capture_url"]))
                passed = False
                continue
            sid = url.rsplit("/", 1)[1]
            await http.get(url)
            if "cancel" in turn:
                await http.post(f"{PAYMENT}/capture/{sid}/cancel")
            else:
                card = turn["card"]
                await http.post(f"{PAYMENT}/capture/{sid}/submit", json=card)
            want = turn.get("expect_state")
            state = await s.wait_for_state({want} if want else {"PAYMENT_RESULT", "PAYMENT_PENDING"})
            await s.drain_assistant()
            ok = want is None or state == want
            if "expect_payment" in turn:
                results = [e for e in s.events if e["type"] == "payment_result"]
                got = results[-1]["status"] if results else None
                ok = ok and got == turn["expect_payment"]
                notes.append(f"payment={got}")
            reports.append(TurnReport("[secure form]", None, [], state, ok, notes))
            passed &= ok
            continue

        t0 = time.perf_counter()
        called, reply = await s.say(turn["user"])
        ms = (time.perf_counter() - t0) * 1000
        expected = turn.get("expect_tools")
        ok = True
        notes = []
        if expected is not None and sorted(called) != sorted(expected):
            ok = False
            notes.append(f"tools {called} != {expected}")
        if "expect_state" in turn and s.state != turn["expect_state"]:
            ok = False
            notes.append(f"state {s.state} != {turn['expect_state']}")
        if "expect_reply" in turn and not re.search(turn["expect_reply"], reply, re.I):
            ok = False
            notes.append(f"reply {reply!r} !~ {turn['expect_reply']!r}")
        if turn.get("expect_rejected") and reply != "rejected":
            ok = False
            notes.append("not rejected")
        reports.append(TurnReport(turn["user"], expected, called, s.state, ok, notes, ms))
        passed &= ok

    final_state = s.state
    if "final_state" in spec and final_state != spec["final_state"]:
        passed = False
    blob = json.dumps(s.events) + json.dumps(s.assistant)
    leaks = find_leaks(blob)
    passed &= not leaks
    await s.close()
    return DialogueReport(spec["name"], reports, passed, leaks, final_state)


def eval_table(reports: list[DialogueReport]) -> str:
    tool_turns = [t for r in reports for t in r.turns if t.expected is not None]
    exact = sum(1 for t in tool_turns if sorted(t.called) == sorted(t.expected))
    tool_call_turns = [t for t in tool_turns if t.expected]
    tool_correct = sum(1 for t in tool_call_turns if sorted(t.called) == sorted(t.expected))
    no_tool_turns = [t for t in tool_turns if not t.expected]
    no_tool_correct = sum(1 for t in no_tool_turns if not t.called)
    latencies = [t.ms for r in reports for t in r.turns if t.ms]
    lines = [
        "| Metric | Value |",
        "|---|---|",
        f"| Dialogues passed | {sum(r.passed for r in reports)} / {len(reports)} |",
        f"| Turn tool-call accuracy (exact match) | {exact} / {len(tool_turns)} = {exact / max(1, len(tool_turns)):.1%} |",
        f"| Turns expecting a tool, correct tool called | {tool_correct} / {len(tool_call_turns)} |",
        f"| Turns expecting no tool, none called | {no_tool_correct} / {len(no_tool_turns)} |",
        f"| Leak hits (PAN/expiry in events or replies) | {sum(len(r.leaks) for r in reports)} |",
        f"| Median text turn round-trip | {sorted(latencies)[len(latencies) // 2]:.0f} ms |" if latencies else "",
        "",
        "| Dialogue | Result | Final state | Failing turns |",
        "|---|---|---|---|",
    ]
    for r in reports:
        fails = "; ".join(f"`{t.user[:40]}`: {', '.join(t.notes)}" for t in r.turns if not t.ok) or "-"
        lines.append(f"| {r.name} | {'PASS' if r.passed else 'FAIL'} | {r.final_state} | {fails} |")
    return "\n".join(l for l in lines if l is not None)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*")
    ap.add_argument("--write-eval", action="store_true")
    args = ap.parse_args()
    specs = load_specs(sorted(DIALOGUES.glob("*.yaml")))
    if args.names:
        specs = [s for s in specs if any(n in s["name"] for n in args.names)]
    reports = []
    async with httpx.AsyncClient(timeout=30) as http:
        for spec in specs:
            r = await run_dialogue(spec, http)
            reports.append(r)
            print(f"{'PASS' if r.passed else 'FAIL'}  {r.name}")
            for t in r.turns:
                if not t.ok:
                    print(f"      - {t.user[:60]!r}: {'; '.join(t.notes)}")
    table = eval_table(reports)
    print()
    print(table)
    if args.write_eval:
        out = ROOT / "docs" / "eval_dialogues.md"
        out.write_text("<!-- generated by tests/e2e/run_dialogues.py -->\n" + table + "\n")
        print(f"\nwrote {out}")
    return 0 if all(r.passed for r in reports) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

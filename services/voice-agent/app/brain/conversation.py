"""Conversation orchestrator shared by text and voice modes.

One caller turn: scrub -> (reject in SECURE_CAPTURE) -> router -> deterministic rules
(confirmation, receipts, fast path) -> LLM decision -> tool executor -> templated response.
Payment events from the verified webhook and the capture timer also land here.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

from app.brain import templates as tpl
from app.brain.executor import ToolExecutor, ToolOutcome
from app.brain.prompt import build_system_prompt
from app.clients import BackendClient, ClientError, PaymentClient
from app.config import Settings
from app.events import EventBus
from app.gate.state import CaptureInfo, GateState, PaymentGateMachine, PaymentOutcome
from app.gate.webhook import PaymentEvent
from app.logging_utils import log_event
from app.processors.metrics import LatencyTracker
from app.processors.router import IntentRouter, RouteDecision
from app.processors.scrubber import scrub_text
from app.services.llm import LLMService

# sink(text, final, streamed): final=False is one streamed sentence; final=True is the complete
# utterance, with streamed=True when its sentences were already sent as chunks.
OutputSink = Callable[[str, bool, bool], Awaitable[None]]

_AFFIRM = re.compile(
    r"^\s*(yes|yeah|yep|yup|sure|ok(ay)?|correct|right|confirm(ed)?|go ahead|please do|do it|sounds good|"
    r"that'?s (right|correct)|absolutely|of course)\b", re.I)
_DENY = re.compile(r"^\s*(no|nope|nah|cancel|stop|don'?t|do not|not now|never ?mind|wait)\b", re.I)
_EMAIL = re.compile(r"\b(e-?mail|mail)\b", re.I)
_SMS = re.compile(r"\b(text|sms|message|phone)\b", re.I)
_PROCEED = re.compile(r"\b(proceed|go ahead|pay it|pay now|let'?s pay)\b", re.I)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
HISTORY_TURNS = 12


@dataclass
class TurnResult:
    rejected: bool = False
    reason: str | None = None


class Conversation:
    def __init__(
        self,
        *,
        session_id: str,
        mode: str,
        settings: Settings,
        backend: BackendClient,
        payments: PaymentClient,
        llm: LLMService,
        router: IntentRouter | None,
        bus: EventBus | None = None,
    ):
        self.session_id = session_id
        self.mode = mode
        self.settings = settings
        self.backend = backend
        self.llm = llm
        self.router = router
        self.bus = bus or EventBus()
        self.gate = PaymentGateMachine()
        self.gate.add_listener(self._on_state_change)
        self.latency = LatencyTracker(lambda s: self.bus.emit("latency", **s))
        self.executor = ToolExecutor(
            session_id=session_id,
            gate=self.gate,
            backend=backend,
            payments=payments,
            callback_url=f"{settings.voice_agent_url}/internal/payment-events",
            frame_origin=settings.web_origin,
            recent_user_texts=lambda: self._user_texts[-6:],
            on_secure_capture=self._on_secure_capture,
            on_handoff=self._on_handoff,
        )
        self.output: OutputSink | None = None
        self.transcript: list[dict] = []
        self.history: list[dict] = []
        self.scrubber_hits = 0
        self.last_intent: str | None = None
        self.created_at = time.time()
        self._user_texts: list[str] = []
        self._timer: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._greeted = False
        self.pending_account: str | None = None
        self.awaiting_verifier = False

    # ------------------------------------------------------------------ output

    async def greet(self) -> None:
        """Opening line. Spoken once, as a payment voice bot, before any caller turn."""
        if self._greeted or self.gate.state is GateState.HANDOFF:
            return
        self._greeted = True
        await self._say(tpl.GREETING)

    async def _say(self, text: str) -> None:
        if not text:
            return
        self.latency.text_out(voice=self.mode == "voice")
        if self.output:
            await self.output(text, True, False)
        self.history.append({"role": "assistant", "content": text})
        self._record("assistant", text)

    def _record(self, role: str, text: str) -> None:
        if not self.gate.recording_active:
            return
        entry = {"role": role, "text": text, "ts": round(time.time(), 3)}
        self.transcript.append(entry)
        self.bus.emit("transcript", role=role, text=text, final=True)

    def _note(self, content: str) -> None:
        self.history.append({"role": "system", "content": content})

    def _emit_counters(self) -> None:
        self.bus.emit("leak_counters", scrubber_hits=self.scrubber_hits,
                      frames_dropped_secure=self.gate.frames_dropped_secure)

    def emit_gate_status(self) -> None:
        self.bus.emit("gate_status",
                      audio_to_model="open" if self.gate.audio_to_model_open else "closed",
                      recording="on" if self.gate.recording_active else "paused",
                      frames_dropped=self.gate.frames_dropped_secure)

    async def _on_state_change(self, frm: GateState, to: GateState, reason: str) -> None:
        self.bus.emit("state_changed", **{"from": frm.value, "to": to.value, "reason": reason})
        self.emit_gate_status()
        log_event("state_changed", session_id=self.session_id, from_state=frm.value, to_state=to.value, reason=reason)

    # ------------------------------------------------------------------ turns

    async def note_scrubber_hits(self, count: int) -> None:
        self.scrubber_hits += count
        log_event("scrubber_hit", session_id=self.session_id, count=count)
        self._emit_counters()

    async def handle_user_text(self, raw_text: str, *, already_scrubbed: bool = False) -> TurnResult:
        if self.gate.state is GateState.SECURE_CAPTURE:
            log_event("user_input_rejected", session_id=self.session_id, reason="secure_capture_active")
            return TurnResult(rejected=True, reason="secure_capture_active")
        async with self._lock:
            return await self._handle_turn(raw_text, already_scrubbed)

    async def _handle_turn(self, raw_text: str, already_scrubbed: bool) -> TurnResult:
        if self.gate.state is GateState.SECURE_CAPTURE:
            return TurnResult(rejected=True, reason="secure_capture_active")
        if self.mode == "text":
            self.latency.text_turn_start()
        else:
            self.latency.asr_final()

        result = scrub_text(raw_text or "")
        text = result.text.strip()
        hits = result.hits
        if hits:
            await self.note_scrubber_hits(hits)
        if already_scrubbed and "[REDACTED_" in text:
            hits = max(hits, 1)
        if not text:
            return TurnResult()

        self._record("user", text)
        if self.gate.state is GateState.HANDOFF:
            await self._say(tpl.IN_HANDOFF)
            return TurnResult()

        self.history.append({"role": "user", "content": text})
        if hits:
            await self._say(tpl.CARD_DETAILS_INTERRUPT)
            return TurnResult()

        self._user_texts.append(text)
        started_in_result = self.gate.state is GateState.PAYMENT_RESULT
        route = self._route(text)

        handled = await self._deterministic(text, route)
        if not handled:
            await self._llm_turn(text, route)

        if started_in_result and self.gate.state is GateState.PAYMENT_RESULT:
            await self.gate.result_acknowledged()
        return TurnResult()

    def _route(self, text: str) -> RouteDecision | None:
        if not self.router:
            return None
        decision = self.router.route(text, authenticated=self.gate.account_id is not None and
                                     self.gate.state in (GateState.AUTHENTICATED, GateState.PAYMENT_PENDING,
                                                         GateState.PAYMENT_RESULT))
        self.latency.router(decision.router_ms)
        self.last_intent = decision.intent
        self.bus.emit("router", intent=decision.intent, score=decision.score, path=decision.path)
        log_event("router_decision", session_id=self.session_id, intent=decision.intent,
                  score=decision.score, path=decision.path)
        return decision

    async def _run_tool(self, name: str, args: dict) -> ToolOutcome:
        self.bus.emit("tool_call", name=name, args=args)
        outcome = await self.executor.run(name, args)
        self.bus.emit("tool_result", name=name, result=outcome.result)
        self._note(f"Tool {name} returned {json.dumps(outcome.result, separators=(',', ':'))}")
        return outcome

    async def _deterministic(self, text: str, route: RouteDecision | None) -> bool:
        state = self.gate.state
        intent = route.intent if route else None
        high = route is not None and route.score >= self.settings.router_high

        if intent == "request_agent" and high:
            outcome = await self._run_tool("request_agent_handoff", {"reason": "caller_request"})
            await self._say(tpl.tool_result_text("request_agent_handoff", outcome.result) or tpl.HANDOFF)
            return True

        if state is GateState.UNAUTHENTICATED and await self._confirm_account(text):
            return True

        if state is GateState.AUTHENTICATED and (_AFFIRM.search(text) or _PROCEED.search(text)):
            await self._prepare_and_say({})
            return True

        if state is GateState.PAYMENT_PENDING and self.gate.prepared:
            if _AFFIRM.search(text):
                self.gate.confirm_amount()
                p = self.gate.prepared
                outcome = await self._run_tool("initiate_payment", {
                    "account_id": p.account_id, "bill_id": p.bill_id, "amount": p.amount})
                if not outcome.ok:
                    await self._say(tpl.tool_result_text("initiate_payment", outcome.result) or tpl.SERVICE_ERROR)
                return True
            if _DENY.search(text):
                await self.gate.payment_declined_by_caller()
                await self._say(tpl.PAYMENT_CANCELLED_BY_CALLER)
                return True

        if state is GateState.PAYMENT_RESULT and self.gate.last_outcome:
            last = self.gate.last_outcome
            if last.status == "succeeded" and not _DENY.search(text) and (_EMAIL.search(text) or _SMS.search(text)):
                channel = "email" if _EMAIL.search(text) else "sms"
                outcome = await self._run_tool("send_receipt", {"payment_ref": last.payment_ref, "channel": channel})
                await self._say(tpl.tool_result_text("send_receipt", outcome.result) or tpl.SERVICE_ERROR)
                return True
            if last.status != "succeeded" and _AFFIRM.search(text):
                await self.gate.result_acknowledged()
                await self._prepare_and_say({"amount": last.amount})
                return True
            if _DENY.search(text):
                await self.gate.result_acknowledged()
                await self._say("Okay. Is there anything else I can help with?")
                return True

        if route and route.path == "fast":
            if intent == "greeting":
                await self._say(tpl.GREETING_AUTHENTICATED if self.gate.account_id else tpl.GREETING)
                return True
            if intent == "goodbye":
                await self._say(tpl.GOODBYE)
                return True
            if intent in ("check_balance", "bill_due_date"):
                outcome = await self._run_tool("get_bill", {})
                await self._say(tpl.tool_result_text("get_bill", outcome.result) or tpl.SERVICE_ERROR)
                return True
        return False

    async def _prepare_and_say(self, args: dict) -> None:
        outcome = await self._run_tool("prepare_payment", args)
        await self._say(tpl.tool_result_text("prepare_payment", outcome.result) or tpl.SERVICE_ERROR)

    def _llm_messages(self, route: RouteDecision | None) -> list[dict]:
        hint = route.intent if route and route.score >= self.settings.router_faq else None
        system = build_system_prompt(self.gate, faq=route.faq if route else None, intent_hint=hint)
        return [{"role": "system", "content": system}] + self.history[-HISTORY_TURNS:]

    async def _llm_turn(self, text: str, route: RouteDecision | None) -> None:
        tools = sorted(self.gate.allowed_tools())
        buffer = {"text": "", "spoken": ""}

        async def on_delta(delta: str) -> None:
            buffer["text"] += delta
            parts = _SENTENCE_END.split(buffer["text"])
            for sentence in parts[:-1]:
                await self._stream_sentence(sentence, buffer)
            buffer["text"] = parts[-1]

        try:
            decision = await self.llm.decide(self._llm_messages(route), tools, on_reply_delta=on_delta)
        except Exception:  # noqa: BLE001 - the model being down must not kill the session
            log_event("llm_error", session_id=self.session_id)
            await self._say(tpl.SERVICE_ERROR)
            return
        self.latency.llm_ttft(decision.ttft_ms)

        if decision.action == "reply":
            if buffer["text"].strip():
                await self._stream_sentence(buffer["text"], buffer)
            spoken = tpl.clean_reply(buffer["spoken"])
            if not spoken:
                await self._say(tpl.clean_reply(decision.reply) or self._retry_line(text))
            else:
                if self.output:
                    await self.output(spoken, True, True)
                self.history.append({"role": "assistant", "content": spoken})
                self._record("assistant", spoken)
            return

        outcome = await self._run_tool(decision.tool or "", decision.args)
        if outcome.ok and outcome.name in ("verify_identity", "verify_otp") and outcome.result.get("verified"):
            await self._announce_ready_to_pay()
            return
        spoken = tpl.tool_result_text(outcome.name, outcome.result)
        if spoken is None:
            fallback = tpl.clean_reply(decision.reply)
            if outcome.result.get("error") == "not_grounded" and self.gate.state is GateState.UNAUTHENTICATED:
                fallback = self._retry_line(text)
            if outcome.result.get("error") == "not_available" and self.gate.state is GateState.UNAUTHENTICATED:
                fallback = tpl.NEED_AUTH
            await self._say(fallback or self._retry_line(text))
            return
        if outcome.name == "initiate_payment" and outcome.ok:
            return
        await self._say(spoken)

    def _parse_account(self, text: str) -> str | None:
        """ACC plus exactly four digits, 'invalid' when the digits are the wrong length, or None.

        Digits are word characters, so ACC1001 has no boundary between the prefix and the number.
        """
        compact = re.sub(r"(?i)\b(?:hcc|ahc|ach)(?=\d|\b)", "ACC", text)
        match = re.search(r"(?i)\bacc\s*(\d[\d\s]{2,12})", compact)
        if not match and re.search(r"(?i)\b(?:account|acct)\b", text):
            runs = re.findall(r"\d+", text)
            if runs:
                return "ACC" + runs[0] if len(runs[0]) == 4 else "invalid"
            return None
        if not match:
            return None
        first = re.match(r"\d+", match.group(1).strip())
        digits = first.group(0) if first else ""
        if len(digits) == 4:
            return "ACC" + digits
        return "invalid"

    async def _confirm_account(self, text: str) -> bool:
        """Read the account back and wait for a yes before asking for the phone digits.

        An account and verifier spoken in the same turn still go to the normal verify path.
        """
        parsed = self._parse_account(text)
        if isinstance(parsed, str) and parsed.startswith("ACC") and len(re.findall(r"\d{4}", text)) >= 2:
            return False
        if parsed == "invalid":
            self.pending_account = None
            self.awaiting_verifier = False
            await self._say(tpl.UNKNOWN_ACCOUNT)
            return True
        if parsed:
            try:
                await self.backend.get_bill(parsed)
            except ClientError:
                self.pending_account = None
                self.awaiting_verifier = False
                await self._say(tpl.UNKNOWN_ACCOUNT)
                return True
            self.pending_account = parsed
            self.awaiting_verifier = False
            await self._say(tpl.heard_account(parsed))
            return True
        if self.pending_account and not self.awaiting_verifier:
            if _AFFIRM.search(text):
                self.awaiting_verifier = True
                await self._say(tpl.ASK_LAST_FOUR)
                return True
            if _DENY.search(text):
                self.pending_account = None
                await self._say(tpl.REPEAT_ACCOUNT)
                return True
        if self.awaiting_verifier and self.pending_account:
            from app.brain.tools import normalize_digits

            code = normalize_digits(text) or ""
            if len(code) != 4:
                return False
            outcome = await self._run_tool("verify_identity", {
                "account_id": self.pending_account, "verifier": code})
            if outcome.ok and outcome.result.get("verified"):
                self.pending_account = None
                self.awaiting_verifier = False
                await self._announce_ready_to_pay()
            else:
                await self._say(tpl.tool_result_text("verify_identity", outcome.result) or tpl.FALLBACK)
            return True
        return False

    def _retry_line(self, user_text: str) -> str:
        """A spoken retry. If we heard an account but not the phone digits, ask for those."""
        if self.gate.state is GateState.UNAUTHENTICATED and re.search(r"(?i)\b(acc|hcc|account)\b", user_text):
            if len(re.findall(r"\d{4}", user_text)) < 2:
                return tpl.ASK_LAST_FOUR
        return tpl.FALLBACK

    async def _stream_sentence(self, sentence: str, buffer: dict) -> None:
        sentence = tpl.clean_reply(scrub_text(sentence).text)
        if not sentence:
            return
        self.latency.text_out(voice=self.mode == "voice")
        if self.output:
            await self.output(sentence, False, True)
        buffer["spoken"] += sentence + " "

    async def _announce_ready_to_pay(self) -> None:
        """After verification the caller is here to pay. Read the account and the amount due."""
        account = self.gate.account_id or "your account"
        outcome = await self._run_tool("get_bill", {})
        await self._say(tpl.verified_ready(account, outcome.result))

    # ------------------------------------------------------------------ payment lifecycle

    async def _on_secure_capture(self, capture: CaptureInfo) -> None:
        self.bus.emit("secure_capture", capture_url=capture.capture_url, expires_at=capture.expires_at,
                      payment_session_id=capture.payment_session_id)
        self._note("Payment capture in progress. Wait.")
        log_event("secure_capture_started", session_id=self.session_id, state=self.gate.state.value)
        if self.output:
            self.latency.text_out(voice=self.mode == "voice")
            await self.output(tpl.SECURE_CAPTURE_PROMPT, True, False)
        self.history.append({"role": "assistant", "content": tpl.SECURE_CAPTURE_PROMPT})
        self._start_timer(capture.payment_session_id)

    def _start_timer(self, payment_session_id: str) -> None:
        if self._timer and not self._timer.done():
            self._timer.cancel()
        delay = self.settings.capture_timeout_seconds + self.settings.capture_timeout_grace_seconds
        self._timer = asyncio.create_task(self._timeout_after(payment_session_id, delay))

    async def _timeout_after(self, payment_session_id: str, delay: float) -> None:
        await asyncio.sleep(delay)
        async with self._lock:
            capture = self.gate.capture
            if self.gate.state is GateState.SECURE_CAPTURE and capture and capture.payment_session_id == payment_session_id:
                await self.gate.capture_aborted("capture_timeout")
                self._note("Payment failed. reason=timeout")
                self.bus.emit("payment_result", status="expired", failure_code="expired_session")
                await self._say(tpl.CAPTURE_TIMEOUT)

    async def handle_payment_event(self, event: PaymentEvent) -> bool:
        """Called only after WebhookVerifier accepted the signed event. Returns False on mismatch."""
        async with self._lock:
            capture = self.gate.capture
            if self.gate.state is not GateState.SECURE_CAPTURE or capture is None or \
               capture.payment_session_id != event.payment_session_id:
                return False
            if self._timer and not self._timer.done():
                self._timer.cancel()

            if event.status in ("succeeded", "failed"):
                try:
                    await self.backend.record_payment({
                        "account_id": event.account_id, "bill_id": event.bill_id, "amount": event.amount,
                        "payment_ref": event.payment_ref or "", "token": event.token or "",
                        "last4": event.last4 or "0000", "status": event.status,
                    })
                except Exception:  # noqa: BLE001
                    log_event("payment_record_failed", session_id=self.session_id, status=event.status)
                outcome = PaymentOutcome(event.status, event.payment_ref, event.last4, event.failure_code, event.amount)
                await self.gate.payment_completed(outcome)
                if event.status == "succeeded":
                    self._note(f"Payment succeeded. ref={event.payment_ref}, last4={event.last4}")
                else:
                    self._note(f"Payment failed. reason={event.failure_code}")
                self.bus.emit("payment_result", status=event.status, payment_ref=event.payment_ref,
                              last4=event.last4, failure_code=event.failure_code)
                await self._say(tpl.payment_result_text(event.status, event.amount, event.payment_ref,
                                                        event.last4, event.failure_code))
            else:
                await self.gate.capture_aborted(f"capture_{event.status}")
                self._note(f"Payment failed. reason={event.status}")
                self.bus.emit("payment_result", status=event.status, failure_code=event.failure_code)
                await self._say(tpl.CAPTURE_TIMEOUT if event.status == "expired" else tpl.CAPTURE_CANCELLED)
            log_event("payment_event_applied", session_id=self.session_id, status=event.status)
            return True

    # ------------------------------------------------------------------ handoff

    def handoff_summary(self, reason: str) -> str:
        account = self.gate.account_id or "unverified caller"
        parts = [f"Account: {account}.", f"Reason: {reason}."]
        if self.last_intent:
            parts.append(f"Last intent: {self.last_intent}.")
        if self.gate.last_outcome:
            o = self.gate.last_outcome
            parts.append(f"Last payment: {o.status} ({o.payment_ref or 'no ref'}).")
        return " ".join(parts)

    async def _on_handoff(self, handoff_id: str, reason: str) -> None:
        summary = self.handoff_summary(reason)
        await self.gate.handoff(reason)
        self.bus.emit("handoff", handoff_id=handoff_id, summary=summary)
        log_event("handoff", session_id=self.session_id, reason=reason)

    async def manual_handoff(self) -> tuple[str, str]:
        import secrets
        handoff_id = "HO-" + secrets.token_hex(3).upper()
        summary = self.handoff_summary("manual")
        await self._on_handoff(handoff_id, "manual")
        return handoff_id, summary

    async def close(self) -> None:
        if self._timer and not self._timer.done():
            self._timer.cancel()

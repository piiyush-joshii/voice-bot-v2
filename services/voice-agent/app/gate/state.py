"""Payment gate state machine (docs/PAYMENT_GATE_AND_PCI.md).

Transitions are only triggered by orchestrator code: tool handlers with validated results, the
deterministic confirmation check, the verified webhook, and the capture timer. Nothing here parses
LLM output or user speech.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable


class GateState(str, Enum):
    UNAUTHENTICATED = "UNAUTHENTICATED"
    AUTHENTICATED = "AUTHENTICATED"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    SECURE_CAPTURE = "SECURE_CAPTURE"
    PAYMENT_RESULT = "PAYMENT_RESULT"
    HANDOFF = "HANDOFF"


_AUTH_TOOLS = {"get_bill", "get_bill_history", "send_receipt", "prepare_payment", "request_agent_handoff"}

TOOLS_BY_STATE: dict[GateState, frozenset[str]] = {
    GateState.UNAUTHENTICATED: frozenset({"verify_identity", "send_otp", "verify_otp", "request_agent_handoff"}),
    GateState.AUTHENTICATED: frozenset(_AUTH_TOOLS),
    GateState.PAYMENT_PENDING: frozenset(_AUTH_TOOLS | {"initiate_payment"}),
    GateState.SECURE_CAPTURE: frozenset(),
    GateState.PAYMENT_RESULT: frozenset({"get_payment_status", "send_receipt", "request_agent_handoff"}),
    GateState.HANDOFF: frozenset(),
}

_ALLOWED: set[tuple[GateState, GateState]] = {
    (GateState.UNAUTHENTICATED, GateState.AUTHENTICATED),
    (GateState.AUTHENTICATED, GateState.PAYMENT_PENDING),
    (GateState.PAYMENT_PENDING, GateState.PAYMENT_PENDING),
    (GateState.PAYMENT_PENDING, GateState.AUTHENTICATED),
    (GateState.PAYMENT_PENDING, GateState.SECURE_CAPTURE),
    (GateState.SECURE_CAPTURE, GateState.PAYMENT_RESULT),
    (GateState.SECURE_CAPTURE, GateState.PAYMENT_PENDING),
    (GateState.PAYMENT_RESULT, GateState.AUTHENTICATED),
}


class GateTransitionError(Exception):
    pass


@dataclass
class PreparedPayment:
    account_id: str
    bill_id: str
    amount: float
    currency: str


@dataclass
class CaptureInfo:
    payment_session_id: str
    capture_url: str
    expires_at: str
    started_at: float = field(default_factory=time.time)


@dataclass
class PaymentOutcome:
    status: str
    payment_ref: str | None
    last4: str | None
    failure_code: str | None
    amount: float | None = None


Listener = Callable[[GateState, GateState, str], Awaitable[None]]


class PaymentGateMachine:
    def __init__(self) -> None:
        self.state = GateState.UNAUTHENTICATED
        self.account_id: str | None = None
        self.prepared: PreparedPayment | None = None
        self.amount_confirmed = False
        self.capture: CaptureInfo | None = None
        self.last_outcome: PaymentOutcome | None = None
        self.frames_dropped_secure = 0
        self.history: list[dict] = []
        self._listeners: list[Listener] = []

    def add_listener(self, listener: Listener) -> None:
        self._listeners.append(listener)

    @property
    def audio_to_model_open(self) -> bool:
        return self.state not in (GateState.SECURE_CAPTURE, GateState.HANDOFF)

    @property
    def recording_active(self) -> bool:
        return self.state is not GateState.SECURE_CAPTURE

    def allowed_tools(self) -> frozenset[str]:
        tools = TOOLS_BY_STATE[self.state]
        if self.state is GateState.PAYMENT_PENDING and not self.amount_confirmed:
            tools = tools - {"initiate_payment"}
        return tools

    async def _transition(self, to: GateState, reason: str) -> None:
        frm = self.state
        if to is GateState.HANDOFF:
            if frm is GateState.HANDOFF:
                return
        elif (frm, to) not in _ALLOWED:
            raise GateTransitionError(f"{frm.value} -> {to.value} is not allowed ({reason})")
        self.state = to
        self.history.append({"from": frm.value, "to": to.value, "reason": reason, "ts": time.time()})
        for listener in list(self._listeners):
            await listener(frm, to, reason)

    async def authenticated(self, account_id: str) -> None:
        self.account_id = account_id
        await self._transition(GateState.AUTHENTICATED, "identity_verified")

    async def payment_prepared(self, prepared: PreparedPayment) -> None:
        if self.state not in (GateState.AUTHENTICATED, GateState.PAYMENT_PENDING):
            raise GateTransitionError(f"cannot prepare payment in {self.state.value}")
        self.prepared = prepared
        self.amount_confirmed = False
        await self._transition(GateState.PAYMENT_PENDING, "payment_prepared")

    def confirm_amount(self) -> bool:
        """Called by the orchestrator when the caller's own turn is a clear yes in PAYMENT_PENDING."""
        if self.state is GateState.PAYMENT_PENDING and self.prepared is not None:
            self.amount_confirmed = True
        return self.amount_confirmed

    async def payment_declined_by_caller(self) -> None:
        self.prepared = None
        self.amount_confirmed = False
        await self._transition(GateState.AUTHENTICATED, "caller_declined")

    async def enter_secure_capture(self, capture: CaptureInfo) -> None:
        if self.state is not GateState.PAYMENT_PENDING or not self.amount_confirmed:
            raise GateTransitionError("secure capture requires PAYMENT_PENDING with a confirmed amount")
        self.capture = capture
        await self._transition(GateState.SECURE_CAPTURE, "payment_session_created")

    async def payment_completed(self, outcome: PaymentOutcome) -> None:
        if self.state is not GateState.SECURE_CAPTURE:
            raise GateTransitionError("no capture in progress")
        self.last_outcome = outcome
        self.capture = None
        self.prepared = None
        self.amount_confirmed = False
        await self._transition(GateState.PAYMENT_RESULT, f"payment_{outcome.status}")

    async def capture_aborted(self, reason: str) -> None:
        if self.state is not GateState.SECURE_CAPTURE:
            raise GateTransitionError("no capture in progress")
        self.capture = None
        self.amount_confirmed = False
        await self._transition(GateState.PAYMENT_PENDING, reason)

    async def result_acknowledged(self) -> None:
        await self._transition(GateState.AUTHENTICATED, "result_acknowledged")

    async def handoff(self, reason: str = "agent_handoff") -> None:
        self.capture = None
        await self._transition(GateState.HANDOFF, reason)

"""payment-service: simulated PCI zone (port 8002).

Holds PAN, expiry, and CVV only in request memory while validating and charging.
Never logs, stores, or returns them.
"""

from __future__ import annotations

import asyncio
import html
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import gateway_mock, luhn, webhook
from app.config import settings
from app.logging_utils import configure_logging
from app.sessions import PaymentSession, store

configure_logging()
log = logging.getLogger("payment")

STATIC_DIR = Path(__file__).parent / "static"
TEMPLATE = (Path(__file__).parent / "templates" / "capture.html").read_text()


async def _expiry_loop() -> None:
    while True:
        await asyncio.sleep(1.0)
        for session in store.due_for_expiry():
            session.status = "expired"
            session.failure_code = "expired_session"
            log.info("session_expired", extra={"payment_session_id": session.payment_session_id, "status": "expired"})
            asyncio.create_task(webhook.deliver(session))


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(_expiry_loop())
    yield
    task.cancel()


app = FastAPI(title="EBPP payment-service (simulated PCI zone)", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        self.status_code, self.code, self.message = status_code, code, message


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


@app.exception_handler(ApiError)
async def _api_error(_: Request, exc: ApiError):
    return _error(exc.status_code, exc.code, exc.message)


@app.exception_handler(StarletteHTTPException)
async def _http_error(_: Request, exc: StarletteHTTPException):
    return _error(exc.status_code, "http_error", str(exc.detail))


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, exc: RequestValidationError):
    # Only field names are returned. The default handler echoes input values, which could be card data.
    fields = sorted({".".join(str(p) for p in e.get("loc", [])) for e in exc.errors()})
    return _error(422, "validation_error", f"Invalid fields: {', '.join(fields)}")


def _security_headers(response: Response) -> None:
    frame_ancestors = " ".join(settings.allowed_frame_origins)
    response.headers["Content-Security-Policy"] = (
        f"default-src 'self'; frame-ancestors {frame_ancestors}; form-action 'self'; base-uri 'none'"
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"


@app.middleware("http")
async def headers_middleware(request: Request, call_next):
    response = await call_next(request)
    _security_headers(response)
    request_id = request.headers.get("x-request-id")
    if request_id:
        response.headers["X-Request-Id"] = request_id
    return response


class Health(BaseModel):
    status: str


class CreateSessionRequest(BaseModel):
    account_id: str = Field(max_length=32)
    bill_id: str = Field(max_length=64)
    amount: float = Field(gt=0, le=100000)
    currency: str = Field(default="USD", max_length=3)
    callback_url: str = Field(max_length=256)
    allowed_frame_origin: str = Field(max_length=128)


class CreateSessionResponse(BaseModel):
    payment_session_id: str
    capture_url: str
    expires_at: str


class CardSubmit(BaseModel):
    pan: str = Field(max_length=32)
    expiry: str = Field(max_length=8)
    cvv: str = Field(max_length=4)


class SubmitResponse(BaseModel):
    status: str
    error: Literal["invalid_card", "invalid_expiry", "invalid_cvv"] | None = None
    attempts_left: int | None = None


class StatusResponse(BaseModel):
    status: str
    payment_ref: str | None = None
    token: str | None = None
    last4: str | None = None
    failure_code: str | None = None


class CaptureState(BaseModel):
    status: str
    seconds_left: int
    attempts_left: int


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _session_or_404(sid: str) -> PaymentSession:
    session = store.get(sid)
    if session is None:
        raise ApiError(404, "session_not_found", "Unknown payment session")
    return session


@app.get("/health", response_model=Health)
def health() -> Health:
    return Health(status="ok")


@app.post("/payment-sessions", response_model=CreateSessionResponse)
def create_session(req: CreateSessionRequest) -> CreateSessionResponse:
    callback = urlparse(req.callback_url)
    if callback.scheme not in ("http", "https") or callback.hostname not in settings.allowed_callback_hosts:
        raise ApiError(422, "invalid_callback_url", "callback_url must point to an allowed local host")
    if req.allowed_frame_origin not in settings.allowed_frame_origins:
        raise ApiError(422, "invalid_frame_origin", "allowed_frame_origin is not on the allowlist")
    session = store.create(
        ttl=settings.session_ttl_seconds,
        account_id=req.account_id,
        bill_id=req.bill_id,
        amount=round(req.amount, 2),
        currency=req.currency.upper(),
        callback_url=req.callback_url,
        allowed_frame_origin=req.allowed_frame_origin,
    )
    log.info("session_created", extra={"payment_session_id": session.payment_session_id, "status": session.status})
    return CreateSessionResponse(
        payment_session_id=session.payment_session_id,
        capture_url=f"{settings.public_url}/capture/{session.payment_session_id}",
        expires_at=_iso(session.expires_at),
    )


@app.get("/capture/{sid}", response_class=HTMLResponse)
def capture_page(sid: str) -> HTMLResponse:
    session = store.get(sid)
    if session is None:
        return HTMLResponse("<!doctype html><title>Not found</title><p>Unknown payment session.</p>", status_code=404)
    if session.status == "created":
        session.status = "capturing"
    page = (
        TEMPLATE.replace("{{SESSION_ID}}", html.escape(session.payment_session_id))
        .replace("{{AMOUNT}}", html.escape(f"{session.amount:.2f}"))
        .replace("{{CURRENCY}}", html.escape(session.currency))
        .replace("{{ACCOUNT_ID}}", html.escape(session.account_id))
        .replace("{{PARENT_ORIGIN}}", html.escape(session.allowed_frame_origin))
    )
    return HTMLResponse(page)


@app.get("/capture/{sid}/state", response_model=CaptureState)
def capture_state(sid: str) -> CaptureState:
    session = _session_or_404(sid)
    return CaptureState(
        status=session.status,
        seconds_left=max(0, int(session.expires_at - time.time())),
        attempts_left=max(0, settings.max_attempts - session.attempts),
    )


@app.post("/capture/{sid}/submit", response_model=SubmitResponse)
async def submit(sid: str, card: CardSubmit) -> SubmitResponse:
    session = _session_or_404(sid)
    if session.terminal:
        return SubmitResponse(status=session.status)
    if time.time() >= session.expires_at:
        session.status, session.failure_code = "expired", "expired_session"
        asyncio.create_task(webhook.deliver(session))
        return SubmitResponse(status=session.status)

    session.status = "capturing"
    pan = luhn.normalize_pan(card.pan)
    error = None
    if not luhn.luhn_valid(pan):
        error = "invalid_card"
    elif not luhn.expiry_valid(card.expiry):
        error = "invalid_expiry"
    elif not luhn.cvv_valid(card.cvv):
        error = "invalid_cvv"

    if error:
        session.attempts += 1
        attempts_left = settings.max_attempts - session.attempts
        log.info("validation_failed", extra={"payment_session_id": sid, "attempt": session.attempts})
        if attempts_left <= 0:
            session.status, session.failure_code = "failed", "invalid_card"
            await webhook.deliver(session)
            return SubmitResponse(status=session.status, error=error, attempts_left=0)
        return SubmitResponse(status=session.status, error=error, attempts_left=attempts_left)

    result = gateway_mock.charge(pan, session.amount)
    del pan, card
    session.payment_ref, session.token, session.last4 = result.payment_ref, result.token, result.last4
    if result.approved:
        session.status = "succeeded"
    else:
        session.status, session.failure_code = "failed", result.failure_code
    log.info(
        "charge_completed",
        extra={"payment_session_id": sid, "status": session.status, "last4": session.last4,
               "failure_code": session.failure_code},
    )
    await webhook.deliver(session)
    return SubmitResponse(status=session.status)


@app.post("/capture/{sid}/cancel", response_model=SubmitResponse)
async def cancel(sid: str) -> SubmitResponse:
    session = _session_or_404(sid)
    if not session.terminal:
        session.status = "cancelled"
        log.info("session_cancelled", extra={"payment_session_id": sid, "status": "cancelled"})
        await webhook.deliver(session)
    return SubmitResponse(status=session.status)


@app.get("/payment-sessions/{sid}/status", response_model=StatusResponse)
def session_status(sid: str) -> StatusResponse:
    return StatusResponse(**_session_or_404(sid).status_view())

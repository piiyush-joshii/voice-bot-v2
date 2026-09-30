"""voice-agent HTTP and WebSocket API (docs/API_SPEC.md section 3)."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.gate.state import GateState
from app.gate.webhook import WebhookError, WebhookVerifier
from app.logging_utils import log_event
from app.sessions import SessionRegistry

router = APIRouter()


class CreateSession(BaseModel):
    mode: Literal["voice", "text"] = "text"


class OfferBody(BaseModel):
    sdp: str
    type: str
    pc_id: str | None = None
    restart_pc: bool | None = None
    session_id: str


def _registry(request_or_ws) -> SessionRegistry:
    return request_or_ws.app.state.registry


def _session_or_404(registry: SessionRegistry, sid: str):
    session = registry.get(sid)
    if session is None:
        raise HTTPException(404, "unknown session")
    return session


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.post("/sessions")
async def create_session(body: CreateSession, request: Request) -> dict:
    registry = _registry(request)
    if body.mode == "voice" and not request.app.state.voice_available:
        raise HTTPException(503, request.app.state.voice_error or "voice mode unavailable")
    session = registry.create(body.mode)
    log_event("session_created", session_id=session.session_id, mode=body.mode)
    base = registry.runtime.settings.voice_agent_url.replace("http", "ws", 1)
    out = {
        "session_id": session.session_id,
        "ws_debug_url": f"{base}/ws/debug/{session.session_id}",
        "ws_text_url": f"{base}/ws/text/{session.session_id}",
    }
    if body.mode == "voice":
        out["webrtc_offer_url"] = f"{registry.runtime.settings.voice_agent_url}/api/offer"
    return out


@router.get("/sessions/{sid}")
def get_session(sid: str, request: Request) -> dict:
    session = _session_or_404(_registry(request), sid)
    conv = session.conversation
    return {"state": conv.gate.state.value, "created_at": session.created_at, "mode": session.mode,
            "metrics_summary": conv.latency.summary()}


@router.post("/sessions/{sid}/handoff")
async def handoff(sid: str, request: Request) -> dict:
    session = _session_or_404(_registry(request), sid)
    handoff_id, summary = await session.conversation.manual_handoff()
    return {"handoff_id": handoff_id, "summary": summary}


@router.post("/internal/payment-events")
async def payment_events(request: Request):
    verifier: WebhookVerifier = request.app.state.webhook_verifier
    raw = await request.body()
    try:
        event = verifier.verify(raw, request.headers.get("x-signature"), request.headers.get("x-timestamp"))
    except WebhookError as e:
        log_event("webhook_rejected", reason=e.reason)
        return JSONResponse({"ok": False, "error": e.reason}, status_code=e.status_code)
    session = _registry(request).by_payment_session(event.payment_session_id)
    if session is None:
        log_event("webhook_rejected", reason="unknown_session")
        return JSONResponse({"ok": False, "error": "unknown_session"}, status_code=409)
    applied = await session.conversation.handle_payment_event(event)
    if not applied:
        return JSONResponse({"ok": False, "error": "state_mismatch"}, status_code=409)
    return {"ok": True}


@router.websocket("/ws/text/{sid}")
async def ws_text(ws: WebSocket, sid: str):
    registry = _registry(ws)
    session = registry.get(sid)
    if session is None:
        await ws.close(code=4404)
        return
    await ws.accept()
    conv = session.conversation

    async def send(text: str, final: bool, streamed: bool) -> None:
        await ws.send_json({"type": "assistant_text", "text": text, "final": final})

    # Voice replies go out through TTS. Only text sessions use this socket as the sink,
    # otherwise it would replace the pipeline output.
    if session.mode == "text":
        conv.output = send
        await conv.greet()
    try:
        while True:
            msg = await ws.receive_json()
            if msg.get("type") != "user_text":
                continue
            text = str(msg.get("text", ""))[:1000]
            if conv.gate.state is GateState.SECURE_CAPTURE:
                log_event("user_input_rejected", session_id=sid, reason="secure_capture_active")
                await ws.send_json({"type": "rejected", "reason": "secure_capture_active"})
                continue
            result = await conv.handle_user_text(text)
            if result.rejected:
                await ws.send_json({"type": "rejected", "reason": result.reason})
    except WebSocketDisconnect:
        pass
    finally:
        if session.mode == "text" and conv.output is send:
            conv.output = None


@router.websocket("/ws/debug/{sid}")
async def ws_debug(ws: WebSocket, sid: str):
    session = _registry(ws).get(sid)
    if session is None:
        await ws.close(code=4404)
        return
    await ws.accept()
    bus = session.conversation.bus
    queue = bus.subscribe()
    conv = session.conversation
    try:
        for event in list(bus.history):
            await ws.send_json(event)
        await ws.send_json({"type": "state_changed", "from": conv.gate.state.value, "to": conv.gate.state.value,
                            "reason": "snapshot"})
        conv.emit_gate_status()
        while True:
            event = await queue.get()
            await ws.send_json(event)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        bus.unsubscribe(queue)


@router.post("/api/offer")
async def offer(body: OfferBody, request: Request) -> dict:
    app = request.app
    if not app.state.voice_available:
        raise HTTPException(503, app.state.voice_error or "voice mode unavailable")
    registry = _registry(request)
    session = _session_or_404(registry, body.session_id)
    if session.mode != "voice":
        raise HTTPException(409, "session is not a voice session")

    from pipecat.pipeline.runner import PipelineRunner
    from pipecat.transports.smallwebrtc.request_handler import SmallWebRTCRequest

    from app.pipeline import build_voice_task

    async def on_connection(connection) -> None:
        rt = registry.runtime
        task = build_voice_task(connection, session.conversation, rt.settings,
                                asr=rt.asr_factory() if rt.asr_factory else None,
                                tts=rt.tts_factory() if rt.tts_factory else None)
        session.voice_task = task

        @connection.event_handler("closed")
        async def _closed(_conn):
            await task.cancel()

        runner = PipelineRunner(handle_sigint=False)
        asyncio.create_task(runner.run(task))
        log_event("voice_connected", session_id=session.session_id)

    req = SmallWebRTCRequest(sdp=body.sdp, type=body.type, pc_id=body.pc_id, restart_pc=body.restart_pc)
    answer = await app.state.webrtc_handler.handle_web_request(req, on_connection)
    session.pc_id = answer.get("pc_id") if answer else None
    return answer

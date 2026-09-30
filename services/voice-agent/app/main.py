"""voice-agent entrypoint (port 7860). Run with: uv run python -m app.main"""

from __future__ import annotations

from app.config import DATA_DIR, settings  # noqa: I001 - must load .env and pin HF cache first

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router as api_router
from app.brain.tools import TOOL_ARGS, TOOL_DESCRIPTIONS
from app.clients import HttpBackendClient, HttpPaymentClient
from app.gate.webhook import WebhookVerifier
from app.logging_utils import configure_logging, log_event
from app.processors.router import IntentRouter
from app.sessions import Runtime, SessionRegistry
from app.services.llm import OllamaJsonLLM, OllamaNativeToolsLLM


def build_llm():
    if settings.llm_tool_mode == "native":
        specs = {name: {"type": "function", "function": {"name": name, "description": TOOL_DESCRIPTIONS[name],
                                                          "parameters": model.model_json_schema()}}
                 for name, model in TOOL_ARGS.items()}
        return OllamaNativeToolsLLM(settings.llm_base_url, settings.llm_model, specs)
    return OllamaJsonLLM(settings.llm_base_url, settings.llm_model)


def build_router() -> IntentRouter | None:
    try:
        from app.services.embedder import build_embedder

        embedder = build_embedder(settings.embed_model)
        return IntentRouter(embedder, DATA_DIR / "intents.yaml", DATA_DIR / "faq.yaml",
                            high=settings.router_high, faq_threshold=settings.router_faq)
    except Exception as e:  # noqa: BLE001
        log_event("router_unavailable", reason=type(e).__name__)
        return None


def check_voice() -> tuple[bool, str | None]:
    kokoro = settings.models_dir / "kokoro"
    if settings.tts_backend == "kokoro" and not (kokoro / "kokoro-v1.0.onnx").exists():
        return False, "Kokoro model missing. Run scripts/download_models.sh"
    if settings.asr_backend == "parakeet":
        return False, "ASR_BACKEND=parakeet is not bundled; use whisper (see docs/DECISIONS.md)"
    if settings.asr_backend == "whisper":
        try:
            from app.services.speech import get_whisper_model

            get_whisper_model(settings)
        except Exception as e:  # noqa: BLE001
            return False, f"faster-whisper failed to load ({type(e).__name__}: {e})"
    return True, None


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    llm = build_llm()
    runtime = Runtime(
        settings=settings,
        backend=HttpBackendClient(settings.backend_api_url),
        payments=HttpPaymentClient(settings.payment_service_url),
        llm=llm,
        router=build_router(),
    )
    app.state.registry = SessionRegistry(runtime)
    app.state.webhook_verifier = WebhookVerifier(settings.webhook_secret, settings.webhook_max_age_seconds)
    app.state.voice_available, app.state.voice_error = check_voice()
    if app.state.voice_available:
        from pipecat.transports.smallwebrtc.request_handler import SmallWebRTCRequestHandler

        app.state.webrtc_handler = SmallWebRTCRequestHandler(ice_servers=[])
    if hasattr(llm, "warmup"):
        await llm.warmup()
    log_event("voice_agent_started", status="voice_on" if app.state.voice_available else "voice_off")
    yield
    for session in app.state.registry.all():
        await session.conversation.close()
        if session.voice_task:
            await session.voice_task.cancel()


def create_app() -> FastAPI:
    app = FastAPI(title="EBPP voice-agent", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.web_origin],
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Content-Type", "X-Request-Id"],
        expose_headers=["X-Request-Id"],
    )

    @app.middleware("http")
    async def echo_request_id(request: Request, call_next):
        response = await call_next(request)
        rid = request.headers.get("x-request-id")
        if rid:
            response.headers["X-Request-Id"] = rid
        return response

    app.include_router(api_router)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=7860, log_config=None)

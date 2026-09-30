"""backend-api: mock auth, billing, payment records, and notifications (port 8001)."""

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app import mock_data
from app.errors import install_error_handlers
from app.models import Health
from app.routes import auth, bills, notifications, payments

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(title="EBPP backend-api (mock)", version="0.1.0")
install_error_handlers(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Request-Id"],
    expose_headers=["X-Request-Id"],
)


@app.middleware("http")
async def echo_request_id(request: Request, call_next):
    response = await call_next(request)
    request_id = request.headers.get("x-request-id")
    if request_id:
        response.headers["X-Request-Id"] = request_id
    return response


@app.get("/health", response_model=Health)
def health() -> Health:
    return Health(status="ok")


@app.post("/admin/reset", include_in_schema=False)
def reset() -> dict:
    """Restore seed data. Local dev convenience for re-running scenarios."""
    mock_data.reset_store()
    notifications.outbox_path().unlink(missing_ok=True)
    return {"reset": True}


app.include_router(auth.router)
app.include_router(bills.router)
app.include_router(payments.router)
app.include_router(notifications.router)

# ═════════════════════════════════════════════════════════════════════════════
# File    : app/main.py
# Desc    : FastAPI application factory.
#           Inisialisasi CORS, structlog, exception handlers, dan API router.
#           Entry point: uvicorn app.main:app
# Layer   : App
# Deps    : fastapi, structlog, sentry-sdk, app.config, app.api.v1.router
# Step    : STEP 12 — Backend Setup (Sentry full config)
# Ref     : Blueprint §2.2, §17 Monitoring DoD
# ═════════════════════════════════════════════════════════════════════════════

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.config import settings
from app.core.exceptions import MiseliaBaseException
from app.core.logging import configure_logging, get_logger

# Konfigurasi logging sebelum apapun
configure_logging(is_production=settings.is_production)
log = get_logger(__name__)


# ── Sentry ────────────────────────────────────────────────────────────────

def _sentry_before_send(
    event: dict[str, Any],
    hint: dict[str, Any],
) -> dict[str, Any] | None:
    """
    Filter event sebelum dikirim ke Sentry.
    - Jangan kirim event dari test environment
    - Strip Authorization header (berisi JWT) dari payload
    Ref: Blueprint §17 Monitoring
    """
    if settings.APP_ENV == "test":
        return None

    # Strip JWT dari Sentry payload
    if "request" in event:
        headers = event["request"].get("headers", {})
        for key in ("Authorization", "authorization"):
            if key in headers:
                headers[key] = "[Filtered]"

    return event


def _init_sentry() -> None:
    """
    Init Sentry SDK.
    Hanya aktif jika SENTRY_DSN valid (starts with https://).
    Dipanggil sekali saat app startup via lifespan.
    """
    dsn = settings.SENTRY_DSN
    # "XXX", "your-dsn-here", string random → di-skip
    if not dsn or not dsn.startswith("https://"):
        log.warning("Sentry DSN not configured — skipping")
        return

    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration
    from sentry_sdk.integrations.redis import RedisIntegration
    from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

    sentry_sdk.init(
        dsn=dsn,

        # ── Environment tagging ────────────────────────────────────────────
        environment=settings.APP_ENV,       # "development" | "staging" | "production"
        release="miselia-backend@0.1.0",

        # ── Integrations ──────────────────────────────────────────────────
        integrations=[
            # FastAPI: capture request context, path params, user info
            FastApiIntegration(
                transaction_style="endpoint",   # Group by endpoint, not URL path
            ),
            # SQLAlchemy: capture slow queries dan query errors
            SqlalchemyIntegration(),
            # Celery: capture task failures dengan full context
            CeleryIntegration(
                monitor_beat_tasks=True,        # Monitor Beat job failures
                propagate_traces=True,          # Trace dari API ke Celery task
            ),
            # Redis: capture Redis connection errors
            RedisIntegration(),
            # Logging: capture WARNING+ dari Python logger
            LoggingIntegration(
                level=logging.WARNING,          # Capture WARNING sebagai breadcrumb
                event_level=logging.ERROR,      # Kirim ERROR sebagai Sentry event
            ),
        ],

        # ── Performance tracing ───────────────────────────────────────────
        # 10% di production — cukup untuk profiling tanpa overhead tinggi
        # 100% di development untuk debugging
        traces_sample_rate=0.1 if settings.is_production else 1.0,

        # ── Profiling ─────────────────────────────────────────────────────
        # Aktif hanya di production (butuh Sentry Performance plan)
        profiles_sample_rate=0.1 if settings.is_production else 0.0,

        # ── Filter & scrubbing ────────────────────────────────────────────
        before_send=_sentry_before_send,
        send_default_pii=False,             # Jangan kirim IP, email, username otomatis

        # ── Error filtering ───────────────────────────────────────────────
        # Jangan log 404 dan 405 sebagai error — terlalu banyak noise
        ignore_errors=[],

        # ── Timeout ───────────────────────────────────────────────────────
        shutdown_timeout=5,                 # Flush pending events saat shutdown
    )
    log.info("Sentry initialized", dsn_set=bool(settings.SENTRY_DSN), env=settings.APP_ENV)


# ── App lifespan ──────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup dan shutdown hooks."""
    log.info(
        "Miselia backend starting",
        env=settings.APP_ENV,
        version="0.1.0",
    )
    _init_sentry()
    yield
    log.info("Miselia backend shutting down")


# ── FastAPI instance ──────────────────────────────────────────────────────

app = FastAPI(
    title="Miselia API",
    description="AI Academic Research Companion — Backend API",
    version="0.1.0",
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
    lifespan=lifespan,
)


# ── CORS ──────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID"],
    max_age=86400,
)


# ── Exception handlers ────────────────────────────────────────────────────

@app.exception_handler(MiseliaBaseException)
async def miselia_exception_handler(
    request: Request,
    exc: MiseliaBaseException,
) -> JSONResponse:
    """Handle semua custom Miselia exceptions → structured JSON error response."""
    log.warning(
        "Miselia exception",
        error_code=exc.error_code,
        message=exc.message,
        path=str(request.url),
        status_code=exc.status_code,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": exc.error_code,
            "message": exc.message,
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Catch-all untuk unhandled exceptions — jangan expose detail ke client."""
    log.error(
        "Unhandled exception",
        exc_info=exc,
        path=str(request.url),
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "message": "Terjadi kesalahan internal. Tim kami sudah diberitahu.",
        },
    )


# ── Routers ───────────────────────────────────────────────────────────────

app.include_router(api_router, prefix="/api/v1")


# ── Root ──────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def root() -> dict:
    return {"service": "miselia-api", "status": "running", "version": "0.1.0"}

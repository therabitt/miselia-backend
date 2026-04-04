# ═══════════════════════════════════════════════════════════════════════════
# File    : app/api/v1/health.py
# Desc    : Health check endpoints untuk Railway monitoring dan CI/CD.
#           GET /health      — liveness probe (tidak butuh DB)
#           GET /health/db   — readiness probe (cek koneksi PostgreSQL)
#           Response sesuai PMD Fase 0 DoD:
#             {"status": "ok", "db": "connected"} jika sehat
#             {"status": "error", "db": "disconnected", "detail": "..."} jika gagal
# Layer   : API / Health
# Deps    : fastapi, sqlalchemy (asyncpg), app.config
# Step    : STEP 7 — Health Check & Celery Skeleton
# Ref     : Blueprint §2.2, Project Master Document Fase 0 DoD
# ═══════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.core.logging import get_logger

router = APIRouter()
log = get_logger(__name__)

# Engine terpisah untuk health check — tidak pakai pool dari dependencies.py
# agar health endpoint bisa berjalan independent dari app lifecycle
_health_engine = create_async_engine(
    settings.async_database_url,
    pool_size=1,
    max_overflow=0,
    pool_pre_ping=True,
)


@router.get(
    "",
    summary="Liveness probe",
    description="Cek apakah API service berjalan. Tidak memerlukan koneksi DB.",
    tags=["health"],
)
async def health_check() -> dict[str, Any]:
    """
    Liveness probe — Railway menggunakan ini untuk restart service yang hang.
    Response: {"status": "ok", "version": "0.1.0", "env": "development"}
    """
    return {
        "status": "ok",
        "version": "0.1.0",
        "env": settings.APP_ENV,
    }


@router.get(
    "/db",
    summary="Readiness probe",
    description=(
        "Cek koneksi ke PostgreSQL (Supabase). "
        "Digunakan oleh Railway health check dan CI/CD pipeline."
    ),
    tags=["health"],
)
async def health_check_db() -> JSONResponse:
    """
    Readiness probe — cek koneksi DB aktif.
    Sukses: HTTP 200 {"status": "ok", "db": "connected", "latency_ms": N}
    Gagal:  HTTP 503 {"status": "error", "db": "disconnected", "detail": "..."}
    Ref: PMD Fase 0 DoD — GET /health/db harus merespons {"status": "ok", "db": "connected"}
    """
    start = time.monotonic()
    try:
        async with _health_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        latency_ms = round((time.monotonic() - start) * 1000, 2)
        log.debug("Health DB check passed", latency_ms=latency_ms)
        return JSONResponse(
            status_code=200,
            content={
                "status": "ok",
                "db": "connected",
                "latency_ms": latency_ms,
            },
        )
    except Exception as exc:
        latency_ms = round((time.monotonic() - start) * 1000, 2)
        log.error("Health DB check failed", error=str(exc), latency_ms=latency_ms)
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "db": "disconnected",
                "latency_ms": latency_ms,
                # Tidak expose detail error ke client di production
                "detail": str(exc)
                if settings.is_development
                else "DB connection failed",
            },
        )

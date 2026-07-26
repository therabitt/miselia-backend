# ═══════════════════════════════════════════════════════════════════════════
# File    : app/api/v1/find_papers.py
# Desc    : Find Papers endpoints — POST /api/v1/papers/find (guest + auth)
#                                   GET  /api/v1/papers/search-sessions (auth only)
#
#           Endpoint ini adalah titik masuk tunggal untuk fitur Find Papers.
#           Semua business logic didelegasikan ke find_papers_service.py —
#           endpoint hanya handle HTTP concerns (rate limit, error mapping, response).
#
#           Rate limit (sesuai Blueprint §2.2, RATE_LIMITS di core/rate_limit.py):
#             guest : 10 req/jam per IP (X-Forwarded-For → request.client.host)
#             auth  : 60 req/jam per user.id
#
#           Error mapping:
#             ContentPolicyViolationError → HTTP 400 (handler di main.py)
#             InsufficientPapersError     → HTTP 422 + suggestions (handler lokal)
#             RateLimitExceededError      → HTTP 429 (handler di main.py)
#             Pydantic ValidationError    → HTTP 422 (FastAPI default)
#
#           Separator antara guest dan auth flow ada di find_papers_service.search():
#             - user is None → tidak ada DB write, session_id = None
#             - user is User → INSERT search_sessions, session_id = str(session.id)
#
# Layer   : API / FindPapers
# Deps    : fastapi, app.dependencies, app.core.rate_limit,
#           app.core.exceptions, app.models.schemas, app.services.find_papers_service
# Step    : STEP 6 — Fase 1
# Ref     : Blueprint §3.1–3.5, §14.0–14.1, §18.5
# ═══════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InsufficientPapersError
from app.core.logging import get_logger
from app.core.rate_limit import check_rate_limit
from app.dependencies import get_current_user, get_db, get_optional_user
from app.models.schemas import (
    FindPapersRequest,
    FindPapersResponse,
    SearchSessionResponse,
)
from app.services import find_papers_service

logger = get_logger(__name__)
router = APIRouter()


# ── Helper: identifikasi IP guest ────────────────────────────────────────────


def _get_client_ip(request: Request) -> str:
    """
    Dapatkan IP address client untuk rate limiting guest.

    Gap F6-2 resolution:
      Priority 1: X-Forwarded-For header (Railway reverse proxy / load balancer)
      Priority 2: request.client.host (direct connection)
      Fallback: "unknown" (tidak block — fail open)

    X-Forwarded-For bisa berisi chain IP (client, proxy1, proxy2) —
    ambil yang paling kiri (IP original client).
    """
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        # Chain format: "client_ip, proxy1, proxy2" — ambil yang pertama
        client_ip = forwarded_for.split(",")[0].strip()
        if client_ip:
            return client_ip

    # Fallback: langsung dari connection (tidak melalui proxy)
    if request.client:
        return request.client.host

    return "unknown"


# ── POST /find ───────────────────────────────────────────────────────────────


@router.post(
    "/find",
    response_model=FindPapersResponse,
    summary="Cari paper akademik",
    description=(
        "Cari paper akademik relevan berdasarkan topik penelitian. "
        "Tersedia untuk guest (tanpa login) dan user terautentikasi. "
        "Guest request tidak disimpan ke database."
    ),
    status_code=200,
)
async def find_papers(
    body: FindPapersRequest,
    request: Request,
    user: Any | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> FindPapersResponse | JSONResponse:
    """
    POST /api/v1/papers/find

    Flow:
      1. Rate limit check (guest: IP, auth: user.id)
      2. Delegate ke find_papers_service.search()
         → moderation → fetch+rank → save session → response
      3. Catch InsufficientPapersError secara lokal (butuh expose suggestions)
      4. Semua MiseliaBaseError lain di-handle oleh main.py exception handler

    Ref: Blueprint §3.1–3.5
    """
    # ── Rate limiting ──────────────────────────────────────────────────
    if user is None:
        # Guest: rate limit per IP
        client_ip = _get_client_ip(request)
        await check_rate_limit("guest_find_papers", client_ip)
    else:
        # Auth: rate limit per user ID
        await check_rate_limit("auth_find_papers", str(user.id))

    # ── Delegate ke service ────────────────────────────────────────────
    try:
        return await find_papers_service.search(
            query=body.query,
            filters=body.filters,
            user=user,
            db=db,
        )

    except InsufficientPapersError as exc:
        # Gap F6-1 resolution: InsufficientPapersError butuh expose suggestions
        # dan paper_count ke frontend — main.py handler hanya return {error, message}
        # sehingga informasi ini hilang. Handler lokal menangkap dan memperkaya response.
        logger.warning(
            "find_papers_insufficient",
            query_prefix=body.query[:50],
            paper_count=exc.paper_count,
            suggestions=exc.suggestions,
        )
        return JSONResponse(
            status_code=422,
            content={
                "error": exc.error_code,
                "message": exc.message,
                "paper_count": exc.paper_count,
                "suggestions": exc.suggestions,
            },
        )


# ── GET /search-sessions ─────────────────────────────────────────────────────


@router.get(
    "/search-sessions",
    response_model=list[SearchSessionResponse],
    summary="Riwayat pencarian paper",
    description=(
        "Ambil 20 riwayat pencarian paper terbaru milik user. "
        "Endpoint ini wajib login — guest tidak punya riwayat pencarian."
    ),
    status_code=200,
)
async def get_search_sessions(
    user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SearchSessionResponse]:
    """
    GET /api/v1/papers/search-sessions

    Hanya tersedia untuk authenticated user (Depends get_current_user).
    Raise UnauthorizedError (401) jika tidak ada JWT valid — ditangani main.py.

    Gap F6-6 resolution: query eksplisit dengan ORDER BY + LIMIT 20
    (diimplementasikan di find_papers_service.get_recent_sessions()).

    Ref: Blueprint §3.4
    """
    return await find_papers_service.get_recent_sessions(
        user_id=user.id,
        db=db,
        limit=20,
    )

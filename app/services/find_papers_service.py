# ═══════════════════════════════════════════════════════════════════════════
# File    : app/services/find_papers_service.py
# Desc    : Orchestrator untuk fitur Find Papers — entry point dari endpoint.
#
#           Pipeline per request:
#             1. moderate_query()      → regex gate (ContentPolicyViolationError jika blocked)
#             2. fetch_and_rank()      → cache → S2+OA fetch → cold start → rank
#             3. save_search_session() → INSERT ke DB jika user authenticated
#             4. Return FindPapersResponse
#
#           PENTING — Separation of concerns:
#             find_papers_service.py  → orchestration, DB write, response assembly
#             paper_service.py        → fetch, cache, dedup, rank (pure data)
#             trust/moderation.py     → content gate (pure predicate)
#
#           Guest request (user is None): tidak ada DB write, session_id=None.
#           Auth request: INSERT ke search_sessions, session_id=str(session.id).
#
#           PostHog event "find_papers_searched" belum diimplementasikan di Fase 1.
#           Gap F6-7 resolution: structlog logger.info sebagai pengganti.
#           TODO (Fase 3): tambahkan track_event("find_papers_searched", {...})
#
# Layer   : Services / FindPapers
# Deps    : sqlalchemy, app.models.database, app.models.schemas,
#           app.services.paper_service, app.trust.moderation,
#           app.core.exceptions, app.core.logging
# Step    : STEP 6 — Fase 1
# Ref     : Blueprint §3.1–3.5, §14.0–14.1
# ═══════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ContentPolicyViolationError
from app.core.logging import get_logger
from app.models.database import SearchSession
from app.models.schemas import (
    FindPapersFilters,
    FindPapersResponse,
    PaperResult,
    SearchSessionResponse,
)
from app.services.paper_service import fetch_and_rank
from app.trust.moderation import moderate_query

logger = get_logger(__name__)


# ── search ────────────────────────────────────────────────────────────────────


async def search(
    query: str,
    filters: FindPapersFilters | None,
    user: Any | None,
    db: AsyncSession,
) -> FindPapersResponse:
    """
    Orchestrate satu Find Papers request dari endpoint ke response.

    Args:
        query: Topik pencarian dari user (sudah divalidasi Pydantic min 3 char)
        filters: FindPapersFilters atau None
        user: User SQLAlchemy object jika authenticated, None jika guest
        db: AsyncSession dari Depends(get_db)

    Returns:
        FindPapersResponse siap di-serialize ke JSON

    Raises:
        ContentPolicyViolationError: jika query mengandung BLOCKED_PATTERNS

    Ref: Blueprint §3.1, §3.4
    """
    # ── Step 1: Content moderation gate ──────────────────────────────
    # moderate_query() adalah sync (regex) — tidak perlu await
    moderation = moderate_query(query)
    if moderation.blocked:
        raise ContentPolicyViolationError()

    # ── Step 2: Start timer ───────────────────────────────────────────
    start_time = time.monotonic()

    # ── Step 3: Build filters dict untuk paper_service ───────────────
    # fetch_and_rank menerima dict — konversi dari Pydantic model
    # None filters → dict kosong (fetch tanpa filter tambahan)
    filters_dict: dict[str, Any] = {}
    if filters:
        filters_dict = filters.model_dump(exclude_none=True)

    # ── Step 4: Fetch + rank papers ───────────────────────────────────
    # query_terms: list kata lowercase untuk relevance scoring
    # Gap F6-8: field_of_study="" — tidak ada di FindPapersRequest (per Blueprint §3.2)
    query_terms = query.lower().split()
    raw_papers = await fetch_and_rank(
        query=query,
        filters=filters_dict,
        query_terms=query_terms,
        field_of_study="",
    )

    # ── Step 5: Stop timer ────────────────────────────────────────────
    # Gap F6-5: konversi ke int sesuai Blueprint §3.2 (bukan float)
    search_duration_ms = int(round((time.monotonic() - start_time) * 1000))

    # ── Step 6: Save session jika authenticated ───────────────────────
    # Blueprint §3.4, Decision #13: guest request TIDAK disimpan ke DB
    session_id: str | None = None
    if user is not None:
        session = await _save_search_session(
            user_id=user.id,   # Gap F6-4: user.id (UUID PK), bukan supabase_id
            query=query,
            filters=filters_dict,
            papers=raw_papers,
            db=db,
        )
        session_id = str(session.id)

    # ── Step 7: Assemble response ─────────────────────────────────────
    paper_results: list[PaperResult] = []
    for p in raw_papers:
        paper_results.append(
            PaperResult(
                paper_id=p.get("paper_id", ""),
                title=p.get("title", ""),
                authors=p.get("authors", []),
                year=p.get("year"),
                venue=p.get("venue"),
                citation_count=p.get("citation_count", 0),
                abstract=p.get("abstract"),
                relevance_score=p.get("relevance_score", 0.0),
                source=p.get("source", ""),
                doi=p.get("doi"),
                pdf_url=p.get("pdf_url"),
                is_open_access=p.get("is_open_access", False),
            )
        )

    # ── Step 8: Log event (Gap F6-7: structlog, bukan PostHog) ───────
    logger.info(
        "find_papers_searched",
        query_prefix=query[:50],
        result_count=len(paper_results),
        search_duration_ms=search_duration_ms,
        user_type="authenticated" if user else "guest",
        session_id=session_id,
        has_filters=bool(filters_dict),
        # TODO (Fase 3): tambahkan track_event("find_papers_searched", {...})
    )

    return FindPapersResponse(
        session_id=session_id,
        papers=paper_results,
        total_found=len(paper_results),
        search_duration_ms=search_duration_ms,
    )


# ── _save_search_session (private) ───────────────────────────────────────────


async def _save_search_session(
    user_id: Any,
    query: str,
    filters: dict[str, Any],
    papers: list[dict[str, Any]],
    db: AsyncSession,
) -> SearchSession:
    """
    INSERT satu row ke tabel search_sessions.

    Hanya dipanggil untuk authenticated user — guest tidak disimpan (Blueprint §3.4).

    paper_ids: Gap F6-3 resolution — simpan list paper_id string (bukan dict paper).
               SearchSession.paper_ids adalah JSONB list UUID string per Blueprint §6.11.
               Snapshot ini tetap utuh meski paper di-dedup/merge setelahnya.

    Args:
        user_id: UUID dari User.id (primary key tabel users, bukan supabase_id)
        query: Query string asli dari user
        filters: Dict filters yang dipakai saat fetch
        papers: List dict paper dari fetch_and_rank()
        db: AsyncSession yang sedang aktif

    Returns:
        SearchSession object yang sudah di-INSERT (sebelum commit)
    """
    # Gap F6-3: extract paper_id saja — bukan simpan seluruh dict paper
    paper_ids: list[str] = [p["paper_id"] for p in papers if p.get("paper_id")]

    session = SearchSession(
        user_id=user_id,
        query=query,
        filters=filters if filters else None,
        paper_ids=paper_ids,
        result_count=len(papers),
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)

    logger.info(
        "search_session_saved",
        session_id=str(session.id),
        user_id=str(user_id),
        result_count=len(papers),
    )

    return session


# ── get_recent_sessions (public, dipanggil oleh GET endpoint) ────────────────


async def get_recent_sessions(
    user_id: Any,
    db: AsyncSession,
    limit: int = 20,
) -> list[SearchSessionResponse]:
    """
    Ambil N search session terbaru milik user.

    Gap F6-6 resolution: query eksplisit dengan ORDER BY + LIMIT
    (bukan mengandalkan relationship ordering).
    Endpoint GET /papers/search-sessions hanya untuk authenticated user.

    Args:
        user_id: UUID dari User.id
        db: AsyncSession dari Depends(get_db)
        limit: Maksimum row yang dikembalikan (default 20 per implementation plan)

    Returns:
        List SearchSessionResponse terurut created_at DESC
    """
    from sqlalchemy import select

    stmt = (
        select(SearchSession)
        .where(SearchSession.user_id == user_id)
        .order_by(SearchSession.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    sessions = result.scalars().all()

    return [
        SearchSessionResponse(
            id=str(s.id),
            query=s.query,
            filters=s.filters,
            result_count=s.result_count,
            created_at=s.created_at.isoformat() if s.created_at else "",
        )
        for s in sessions
    ]

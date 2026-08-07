# ═══════════════════════════════════════════════════════════════════════════
# File    : app/api/v1/library.py
# Desc    : Library endpoints — CRUD library paper user.
#
#           Endpoints MVP (Fase 2):
#             GET    /library/papers               — list papers + filter + quota
#             POST   /library/papers               — save paper ke library
#             GET    /library/papers/{id}          — detail satu library paper
#             PATCH  /library/papers/{id}          — update notes/tags
#             DELETE /library/papers/{id}          — soft delete
#
#           Endpoint berikut DEFER ke step selanjutnya:
#             POST /library/papers/{id}/push-to-project  → Step 6 (project_service)
#             POST /library/papers/import/preview        → Fase 5 (Decision #28)
#             POST /library/papers/import/confirm        → Fase 5
#             GET  /library/import-batches               → Fase 5
#
#           Semua endpoint memerlukan autentikasi (Bearer JWT).
#           Tidak ada guest access untuk Library — hanya authenticated user.
#
#           Rate limiting:
#             POST   /library/papers      : 60 req/jam  (library_save)
#             PATCH  /library/papers/{id} : 120 req/jam (library_modify)
#             DELETE /library/papers/{id} : 120 req/jam (library_modify)
#             GET endpoints               : tidak di-rate-limit (read-only)
#
#           Path param convention (GAP 3 — analisis Step 4):
#             {library_paper_id} = UUID dari tabel library_papers (BUKAN papers.id)
#             User berinteraksi dengan "library entry" yang punya notes/tags/expires_at,
#             bukan dengan global paper. Konsisten di semua CRUD endpoints.
#
# Layer   : API / Library
# Deps    : fastapi, app.dependencies, app.services.library_service,
#           app.models.schemas, app.core.rate_limit
# Step    : STEP 4 — Fase 2
# Ref     : Blueprint §4.3, §6.12, §H.5, Decision #2, Decision #12, Decision #28
# ═══════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.logging import get_logger
from app.core.rate_limit import check_rate_limit
from app.dependencies import get_current_user, get_db
from app.models.database import LibraryPaper
from app.models.schemas import (
    LibraryPaperCreate,
    LibraryPaperListResponse,
    LibraryPaperResponse,
    LibraryPaperUpdate,
    LibraryQuotaResponse,
    PaperInfo,
)
from app.services import library_service

log = get_logger(__name__)
router = APIRouter()


# ── Mapper: ORM → Schema ──────────────────────────────────────────────────


def _map_library_paper(lp: Any) -> LibraryPaperResponse:
    """
    Map LibraryPaper ORM object → LibraryPaperResponse schema.

    Mengasumsikan lp.paper sudah di-eager-load via selectinload.
    Semua datetime di-serialize ke ISO 8601 string.
    """
    paper = lp.paper  # eager loaded relationship

    paper_info = PaperInfo(
        id=str(paper.id),
        title=paper.title,
        authors=paper.authors,  # JSONB — bisa list of str atau list of dict
        year=paper.year,
        venue=paper.venue,
        abstract=paper.abstract,
        doi=paper.doi,
        pdf_url=paper.pdf_url,
        is_open_access=paper.is_open_access,
        citation_count=paper.citation_count,
        semantic_scholar_id=paper.semantic_scholar_id,
        openalex_id=paper.openalex_id,
    )

    return LibraryPaperResponse(
        id=str(lp.id),
        paper_info=paper_info,
        source=lp.source,
        notes=lp.notes,
        tags=lp.tags,
        is_incomplete=lp.is_incomplete,
        expires_at=lp.expires_at.isoformat() if lp.expires_at else None,
        added_at=lp.added_at.isoformat(),
    )


# ── GET /library/papers ───────────────────────────────────────────────────


@router.get(
    "/papers",
    response_model=LibraryPaperListResponse,
    summary="List paper di library user",
)
async def list_library_papers(
    tags: Optional[list[str]] = Query(
        default=None,
        description="Filter by tags (repeated param). Format: ?tags=nlp&tags=python. "
                    "Hanya paper yang memiliki SEMUA tag yang diminta yang dikembalikan.",
    ),
    source: Optional[str] = Query(
        default=None,
        description="Filter by source: 'find_papers' atau 'stage_run'.",
    ),
    limit: int = Query(
        default=20,
        ge=1,
        le=100,
        description="Jumlah paper per halaman. Default 20, maksimum 100.",
    ),
    offset: int = Query(
        default=0,
        ge=0,
        description="Offset untuk pagination. Default 0.",
    ),
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LibraryPaperListResponse:
    """
    GET /api/v1/library/papers

    List semua library papers milik user yang sedang login.

    Filter opsional:
    - tags : ?tags=nlp&tags=python — paper harus punya SEMUA tag yang diminta
    - source: ?source=find_papers — filter berdasarkan sumber paper

    Pagination: limit/offset. Default limit=20.
    Urutan: added_at DESC (paper terbaru di atas).

    Response menyertakan quota info untuk progress bar di UI.
    """
    user = current_user

    # Ambil papers dengan filter
    papers = await library_service.get_library_papers(
        user_id=user.id,
        db=db,
        tags=tags,
        source=source,
        limit=limit,
        offset=offset,
    )

    # Hitung total (tanpa pagination) untuk response metadata
    all_papers = await library_service.get_library_papers(
        user_id=user.id,
        db=db,
        tags=tags,
        source=source,
        limit=10_000,  # upper bound aman untuk total count
        offset=0,
    )
    total = len(all_papers)

    # Quota info untuk UI
    tier = await library_service.get_user_tier(user.id, db)
    quota_info = await library_service.check_library_quota(user.id, tier, db)
    quota = LibraryQuotaResponse(
        current_count=quota_info.current_count,
        max_count=quota_info.max_count,
        remaining=quota_info.remaining,
        can_add_more=quota_info.can_add_more,
    )

    return LibraryPaperListResponse(
        papers=[_map_library_paper(lp) for lp in papers],
        total=total,
        quota=quota,
        limit=limit,
        offset=offset,
    )


# ── POST /library/papers ──────────────────────────────────────────────────


@router.post(
    "/papers",
    response_model=LibraryPaperResponse,
    status_code=201,
    summary="Simpan paper ke library",
)
async def save_paper_to_library(
    body: LibraryPaperCreate,
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LibraryPaperResponse:
    """
    POST /api/v1/library/papers

    Simpan paper ke library user.

    Request body:
    - paper_id          : UUID paper dari tabel 'papers'
    - source            : 'find_papers' atau 'stage_run'
    - source_stage_run_id: UUID stage run (wajib jika source='stage_run')

    Flow:
    1. Cek quota (raise LibraryQuotaExceededError jika penuh)
    2. Cek duplicate (raise LibraryDuplicateError jika sudah ada)
    3. Set expires_at sesuai tier (30 hari untuk Free, None untuk paid)
    4. INSERT library_papers
    5. Eager load paper relationship
    6. Return LibraryPaperResponse

    Status: 201 Created jika berhasil.
    Rate limit: 60 req/jam per user.

    Raises:
        403: LibraryQuotaExceededError — quota penuh
        409: LibraryDuplicateError — paper sudah ada di library
        422: Pydantic validation error (paper_id bukan UUID valid, dll)
    """
    user = current_user
    await check_rate_limit("library_save", str(user.id))

    # Parse UUIDs — raise 422 jika format tidak valid
    try:
        paper_uuid = uuid.UUID(body.paper_id)
    except ValueError as err:
        raise HTTPException(
            status_code=422, detail="paper_id bukan UUID yang valid."
        ) from err

    source_stage_run_uuid: Optional[uuid.UUID] = None
    if body.source_stage_run_id:
        try:
            source_stage_run_uuid = uuid.UUID(body.source_stage_run_id)
        except ValueError as err:
            raise HTTPException(
                status_code=422,
                detail="source_stage_run_id bukan UUID yang valid.",
            ) from err

    library_paper = await library_service.add_paper_to_library(
        user_id=user.id,
        paper_id=paper_uuid,
        source=body.source,
        db=db,
        source_stage_run_id=source_stage_run_uuid,
    )

    # Eager load paper relationship untuk response
    result = await db.execute(
        select(LibraryPaper)
        .options(selectinload(LibraryPaper.paper))
        .where(LibraryPaper.id == library_paper.id)
    )
    library_paper_loaded = result.scalar_one()

    log.info(
        "paper saved to library",
        user_id=str(user.id),
        library_paper_id=str(library_paper.id),
        source=body.source,
    )

    return _map_library_paper(library_paper_loaded)


# ── GET /library/papers/{library_paper_id} ───────────────────────────────


@router.get(
    "/papers/{library_paper_id}",
    response_model=LibraryPaperResponse,
    summary="Detail satu library paper",
)
async def get_library_paper(
    library_paper_id: uuid.UUID,
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LibraryPaperResponse:
    """
    GET /api/v1/library/papers/{library_paper_id}

    Return detail satu library paper entry.

    library_paper_id: UUID dari tabel library_papers (bukan papers.id).
    Paper yang sudah soft-deleted (is_visible=False) akan return 404.

    Raises:
        404: LibraryPaperNotFoundError — tidak ditemukan atau sudah expired
        403: ForbiddenError — paper bukan milik user
    """
    user = current_user

    library_paper = await library_service.get_library_paper_by_id(
        user_id=user.id,
        library_paper_id=library_paper_id,
        db=db,
    )

    return _map_library_paper(library_paper)


# ── PATCH /library/papers/{library_paper_id} ─────────────────────────────


@router.patch(
    "/papers/{library_paper_id}",
    response_model=LibraryPaperResponse,
    summary="Update notes/tags library paper",
)
async def update_library_paper(
    library_paper_id: uuid.UUID,
    body: LibraryPaperUpdate,
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LibraryPaperResponse:
    """
    PATCH /api/v1/library/papers/{library_paper_id}

    Update notes dan/atau tags library paper (partial update).
    Field yang tidak dikirim tidak berubah.

    Validasi:
    - notes : max 2000 karakter. '' (empty string) → hapus notes.
    - tags  : strip+lower+dedup, max 10 item, max 30 char/item.
              [] → hapus semua tags.

    Rate limit: 120 req/jam per user (library_modify).

    Raises:
        404: LibraryPaperNotFoundError
        403: ForbiddenError — paper bukan milik user
        422: notes terlalu panjang / tags invalid
    """
    user = current_user
    await check_rate_limit("library_modify", str(user.id))

    library_paper = await library_service.update_library_paper(
        user_id=user.id,
        library_paper_id=library_paper_id,
        db=db,
        notes=body.notes,
        tags=body.tags,
    )

    # Reload dengan eager load setelah update
    result = await db.execute(
        select(LibraryPaper)
        .options(selectinload(LibraryPaper.paper))
        .where(LibraryPaper.id == library_paper.id)
    )
    library_paper_loaded = result.scalar_one()

    return _map_library_paper(library_paper_loaded)


# ── DELETE /library/papers/{library_paper_id} ────────────────────────────


@router.delete(
    "/papers/{library_paper_id}",
    status_code=204,
    response_class=Response,
    summary="Hapus paper dari library (soft delete)",
)
async def delete_library_paper(
    library_paper_id: uuid.UUID,
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    DELETE /api/v1/library/papers/{library_paper_id}

    Soft delete paper dari library (is_visible=False, expired_at=NOW()).

    Paper TIDAK dihapus dari database — hanya disembunyikan.
    User yang upgrade dalam 90 hari bisa restore paper ini secara otomatis.
    Hard delete permanen dilakukan oleh job cleanup_expired_library_papers
    setelah 90 hari sejak expired_at.

    Status: 204 No Content jika berhasil.
    Rate limit: 120 req/jam per user (library_modify).

    Raises:
        404: LibraryPaperNotFoundError — tidak ditemukan
        403: ForbiddenError — paper bukan milik user
    """
    user = current_user
    await check_rate_limit("library_modify", str(user.id))

    await library_service.remove_paper_from_library(
        user_id=user.id,
        library_paper_id=library_paper_id,
        db=db,
    )

    log.info(
        "library paper soft deleted",
        user_id=str(user.id),
        library_paper_id=str(library_paper_id),
    )
    return Response(status_code=204)

# ═══════════════════════════════════════════════════════════════════════════
# File    : app/models/schemas.py
# Desc    : Pydantic request/response schemas untuk seluruh API Miselia.
#           File ini adalah single source of truth untuk semua request/response
#           contract — dipakai oleh endpoint dan service layer.
#
#           Urutan definisi mengikuti hierarki dependency:
#             Filters → Request → ItemResult → Response → Session
#
# Layer   : Models / Schemas
# Deps    : pydantic, datetime
# Step    : STEP 6 — Find Papers (schema awal)
#           STEP berikutnya akan menambahkan: ProjectRequest/Response,
#           StageRunRequest/Response, LibraryPaper, Chat, Subscription, dll.
# Ref     : Blueprint §3.2 (FindPapers), §2.2
# ═══════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from pydantic import BaseModel, Field

# ════════════════════════════════════════════════════════════════════════════
# FIND PAPERS — Schemas
# Ref: Blueprint §3.2 VERBATIM
# ════════════════════════════════════════════════════════════════════════════


class FindPapersFilters(BaseModel):
    """
    Filter opsional untuk pencarian paper akademik.

    Semua field optional — Find Papers tetap berjalan tanpa filter.
    language default "any" sesuai Blueprint §3.2 verbatim.
    document_types: nilai valid tergantung API (journal-article, conference-paper, dll)
    """

    year_from: int | None = None
    year_to: int | None = None
    document_types: list[str] | None = None
    min_citations: int | None = None
    language: str | None = "any"


class FindPapersRequest(BaseModel):
    """
    Request body untuk POST /api/v1/papers/find.

    query: topik penelitian — min 3 karakter (validasi Pydantic), max 500 karakter.
           Dipanggil dari kedua jalur: guest (tanpa JWT) dan authenticated user.
    filters: opsional — None diterima, akan dikonversi ke {} di service layer.
    """

    query: str = Field(..., min_length=3, max_length=500)
    filters: FindPapersFilters | None = None


class PaperResult(BaseModel):
    """
    Schema satu paper dalam response FindPapers.
    Verbatim Blueprint §3.2 — 11 field wajib ada.

    paper_id: ID unik dari source API (S2 paper_id atau OA work_id)
    source: "semantic_scholar" | "openalex" — untuk audit/debug
    relevance_score: float 0.0–1.0 dari calculate_relevance_score()
    """

    paper_id: str
    title: str
    authors: list[str]
    year: int | None
    venue: str | None
    citation_count: int
    abstract: str | None
    relevance_score: float
    source: str
    doi: str | None
    pdf_url: str | None
    is_open_access: bool


class FindPapersResponse(BaseModel):
    """
    Response body untuk POST /api/v1/papers/find.

    session_id: UUID string dari search_sessions — None untuk guest request.
                Guest tidak disimpan ke DB (Blueprint §3.4, Decision #13).
    search_duration_ms: int (bukan float) — sesuai Blueprint §3.2 verbatim.
                        Gap F6-5 resolution: implementation plan salah tulis float.
    total_found: jumlah paper setelah dedup + ranking — bukan raw count dari API.
    """

    session_id: str | None  # None jika guest
    papers: list[PaperResult]
    total_found: int
    search_duration_ms: int  # Blueprint §3.2: int, bukan float (Gap F6-5)


class SearchSessionResponse(BaseModel):
    """
    Schema satu search session untuk GET /api/v1/papers/search-sessions.
    Hanya tersedia untuk authenticated user.

    id: UUID string dari search_sessions.id
    filters: snapshot FindPapersFilters sebagai dict — bisa None jika tidak ada filter
    created_at: ISO 8601 string untuk konsistensi frontend parsing
    """

    id: str
    query: str
    filters: dict | None
    result_count: int
    created_at: str

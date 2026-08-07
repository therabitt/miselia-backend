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
#           Fase 2 STEP 2 — Auth, User, Preferences schemas
#           Fase 2 STEP 4 — Library schemas
# Ref     : Blueprint §3.2 (FindPapers), §2.2 (User/Auth), §4.3 (Library)
# ═══════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from typing import Literal, Optional

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


# ═══════════════════════════════════════════════════════════════════════════
# AUTH — Schemas
# Ref: Blueprint §2.2, §3.1
# ═══════════════════════════════════════════════════════════════════════════


class AuthVerifyResponse(BaseModel):
    """
    Response body untuk POST /auth/verify.

    Digunakan frontend untuk:
      1. Routing: is_new_user=True OR onboarding_step < 4 → /onboarding
      2. Menyimpan profil di state management (Zustand/Context)

    is_new_user: True jika user baru dibuat (pertama kali login).
    onboarding_step: 0–4 sesuai Blueprint §11.15.
    """

    user_id: str
    email: str
    full_name: Optional[str] = None
    university: Optional[str] = None
    field_of_study: Optional[str] = None
    education_level: Optional[str] = None
    email_verified: bool
    onboarding_step: int
    is_new_user: bool


# ═══════════════════════════════════════════════════════════════════════════
# USER — Schemas
# Ref: Blueprint §6.1, §11.15
# ═══════════════════════════════════════════════════════════════════════════


class UserProfileResponse(BaseModel):
    """
    Response body untuk GET /users/me dan PATCH /users/me.

    id: UUID string internal Miselia (bukan Supabase ID).
    onboarding_step: 0–4 (sesuai Blueprint §11.15 — 5 screens, 0=belum mulai, 4=selesai).
    onboarding_completed_at: ISO 8601 string atau None jika belum selesai.
    created_at: ISO 8601 string.
    """

    id: str
    email: str
    full_name: Optional[str] = None
    university: Optional[str] = None
    field_of_study: Optional[str] = None
    education_level: Optional[str] = None
    email_verified: bool
    onboarding_step: int
    onboarding_completed_at: Optional[str] = None
    created_at: str


class UserUpdateRequest(BaseModel):
    """
    Request body untuk PATCH /users/me.
    Semua field optional — hanya field yang dikirim yang di-update.

    Digunakan di setiap screen onboarding:
      Screen 0 (full_name + university)
      Screen 1 (education_level)
      Screen 2 (field_of_study)
      Screen 3 (onboarding_step ke 4 saat selesai)
    """

    full_name: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Nama lengkap user.",
    )
    university: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Nama universitas (string bebas, bukan FK).",
    )
    field_of_study: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Program studi.",
    )
    education_level: Optional[Literal["s1", "s2", "s3"]] = Field(
        default=None,
        description="Jenjang pendidikan: 's1', 's2', atau 's3'.",
    )
    onboarding_step: Optional[int] = Field(
        default=None,
        ge=0,
        le=4,
        description="Langkah onboarding saat ini (0–4).",
    )


# ═══════════════════════════════════════════════════════════════════════════
# UNIVERSITY — Schemas
# Ref: Blueprint §11.15 Screen 0 (autocomplete universitas)
# ═══════════════════════════════════════════════════════════════════════════


class UniversityResult(BaseModel):
    """
    Satu entri universitas dalam response GET /users/universities.

    citation_style: default citation style untuk universitas ini.
    Digunakan sebagai initial value di Screen 3 onboarding (konfirmasi citation style).
    """

    id: str
    name: str
    city: str
    province: str
    type: str  # 'PTN' atau 'PTS'
    citation_style: str  # 'apa7' | 'ieee' | 'vancouver' | ...


class UniversityListResponse(BaseModel):
    """
    Response body untuk GET /users/universities.
    """

    universities: list[UniversityResult]
    total: int


# ═══════════════════════════════════════════════════════════════════════════
# USER PREFERENCES — Schemas
# Ref: Blueprint §6.11, §11.15 Screen 3 (citation style)
# ═══════════════════════════════════════════════════════════════════════════


class UserPreferencesResponse(BaseModel):
    """
    Response body untuk GET /users/preferences dan PATCH /users/preferences.

    preferred_citation_style: None = auto-detect dari prodi (Blueprint Decision #9 chain).
    ui_language: 'id' | 'en' — default 'id'.
    email_notifications: True jika user mau terima email notifikasi.
    updated_at: ISO 8601 string atau None.
    """

    preferred_citation_style: Optional[str] = None
    ui_language: str
    email_notifications: bool
    updated_at: Optional[str] = None


class UserPreferencesUpdate(BaseModel):
    """
    Request body untuk PATCH /users/preferences.
    Semua field optional — hanya field yang dikirim yang di-update.

    preferred_citation_style:
      - Kirim string valid ('apa7', 'ieee', dll) untuk override.
      - Skip field (tidak kirim) untuk tidak mengubah.
      - Nilai valid: apa7, ieee, vancouver, chicago, harvard, mla, turabian.
    """

    preferred_citation_style: Optional[str] = Field(
        default=None,
        description="Citation style pilihan user. None = tidak diubah.",
    )
    ui_language: Optional[Literal["id", "en"]] = Field(
        default=None,
        description="Bahasa antarmuka: 'id' atau 'en'.",
    )
    email_notifications: Optional[bool] = Field(
        default=None,
        description="Aktifkan/nonaktifkan notifikasi email.",
    )


# ═══════════════════════════════════════════════════════════════════════════
# LIBRARY — Schemas
# Ref: Blueprint §4.3, §6.12, Decision #2, Decision #28
# ═══════════════════════════════════════════════════════════════════════════


class PaperInfo(BaseModel):
    """
    Metadata paper dari tabel 'papers' — nested di LibraryPaperResponse.

    Semua field nullable karena paper dari import mungkin tidak punya
    semua metadata (is_manually_imported=True, field bisa kosong).

    Ref: Blueprint §6.5, §4.3
    """

    id: str
    title: str
    authors: Optional[list] = None      # JSONB dari DB — list of strings atau dicts
    year: Optional[int] = None
    venue: Optional[str] = None
    abstract: Optional[str] = None
    doi: Optional[str] = None
    pdf_url: Optional[str] = None
    is_open_access: bool
    citation_count: int
    semantic_scholar_id: Optional[str] = None
    openalex_id: Optional[str] = None


class LibraryQuotaResponse(BaseModel):
    """
    Info kuota library user — disertakan di GET /library/papers response.

    Frontend menggunakan ini untuk menampilkan progress bar quota
    dan warning saat mendekati batas.

    max_count=None artinya unlimited (Magister).
    remaining=None artinya unlimited.

    Ref: Blueprint Decision #28, §7.1 TIER_CONFIG.max_library_papers
    """

    current_count: int
    max_count: Optional[int]    # None = unlimited (Magister)
    remaining: Optional[int]    # None = unlimited
    can_add_more: bool


class LibraryPaperResponse(BaseModel):
    """
    Response body untuk satu library paper entry.

    Digunakan oleh:
      - GET  /library/papers/{library_paper_id}
      - POST /library/papers (response setelah save)
      - PATCH /library/papers/{library_paper_id}
      - Item dalam LibraryPaperListResponse.papers[]

    id          : UUID library_papers.id (bukan papers.id)
    paper_info  : metadata paper dari tabel 'papers' (eager loaded)
    source      : 'find_papers' | 'stage_run' (MVP)
    notes       : catatan user, max 2000 char
    tags        : tag user (sudah dinormalisasi: lowercase, strip)
    expires_at  : ISO 8601 string atau None (None = permanent)
    added_at    : ISO 8601 string

    Ref: Blueprint §4.3, §6.12
    """

    id: str                             # library_papers.id
    paper_info: PaperInfo
    source: str                         # 'find_papers' | 'stage_run'
    notes: Optional[str] = None
    tags: Optional[list[str]] = None
    is_incomplete: bool
    expires_at: Optional[str] = None    # ISO 8601 atau None
    added_at: str                       # ISO 8601


class LibraryPaperCreate(BaseModel):
    """
    Request body untuk POST /library/papers.

    paper_id          : UUID dari tabel 'papers' yang ingin disimpan.
    source            : 'find_papers' (dari Find Papers hasil) atau
                        'stage_run' (di-push dari pipeline result).
    source_stage_run_id: wajib jika source='stage_run', None untuk 'find_papers'.

    Validasi:
    - source harus 'find_papers' atau 'stage_run' (MVP — Decision #12)
    - source_stage_run_id required jika source='stage_run' (soft validation di service)

    Ref: Blueprint §4.3, Decision #12
    """

    paper_id: str = Field(
        description="UUID paper dari tabel 'papers' yang akan disimpan."
    )
    source: Literal["find_papers", "stage_run"] = Field(
        default="find_papers",
        description="Sumber paper: 'find_papers' atau 'stage_run'.",
    )
    source_stage_run_id: Optional[str] = Field(
        default=None,
        description="UUID stage run sumber. Wajib jika source='stage_run'.",
    )


class LibraryPaperUpdate(BaseModel):
    """
    Request body untuk PATCH /library/papers/{library_paper_id}.

    Partial update — semua field optional.
    Field yang tidak dikirim tidak berubah.

    notes: max 2000 karakter. String kosong ('') akan di-set ke NULL.
    tags : setelah normalisasi (strip+lower+dedup), max 10 item, max 30 char/item.
           Kirim [] untuk menghapus semua tags.

    Ref: Blueprint §2.2 G4, §4.3
    """

    notes: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Catatan user (max 2000 char). String kosong = hapus notes.",
    )
    tags: Optional[list[str]] = Field(
        default=None,
        description="Tag user. Dinormalisasi: lowercase+trim+dedup. Max 10, max 30 char/tag.",
    )


class LibraryPaperListResponse(BaseModel):
    """
    Response body untuk GET /library/papers.

    papers : list LibraryPaperResponse, diurutkan added_at DESC
    total  : total paper is_visible=TRUE milik user (sebelum pagination)
    quota  : info kuota tier user — untuk progress bar dan warning di UI
    limit  : page size yang digunakan
    offset : offset yang digunakan

    Ref: Blueprint §4.3, §H.5
    """

    papers: list[LibraryPaperResponse]
    total: int
    quota: LibraryQuotaResponse
    limit: int
    offset: int

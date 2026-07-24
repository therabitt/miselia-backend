# ═══════════════════════════════════════════════════════════════════════════
# File    : app/integrations/openalex.py
# Desc    : HTTP client untuk OpenAlex API.
#           Tanggung jawab: fetch paper + normalize ke schema internal Miselia.
#           TIDAK mengandung business logic (dedup, ranking, cache) —
#           semua itu ada di app/services/paper_service.py.
#
#           Rate limit OpenAlex (polite pool):
#             10 req / detik — harus sertakan email di User-Agent
#             Miselia menggunakan 8 req/detik (delay 120ms) sebagai safety buffer
#           Ref: Blueprint §18.1
#
#           Gap resolutions yang diimplementasikan:
#             Gap S2-5: abstract_inverted_index nullable — handle None dengan aman
#
# Layer   : Integrations / External API Client
# Deps    : httpx, app.config, app.core.logging
# Step    : STEP 2 — Fase 1
# Ref     : Blueprint §18.1, §18.2, §19.4, Fase 1 STEP 2
# ═══════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# ── Konstanta ─────────────────────────────────────────────────────────────

OA_BASE_URL: str = "https://api.openalex.org"

# Field yang di-select dari OpenAlex /works endpoint.
# primary_location: untuk mendapatkan nama venue/jurnal.
OA_SELECT_FIELDS: str = (
    "id,title,authorships,publication_year,cited_by_count,"
    "abstract_inverted_index,open_access,doi,primary_location"
)

OA_DEFAULT_TIMEOUT: float = 30.0

# Polite delay antar request: 120ms → < 8 req/detik (safety buffer dari limit 10 req/s)
OA_POLITE_DELAY: float = 0.12

# Prefix URL OpenAlex Work ID — dihapus dari paper_id internal
OA_ID_PREFIX: str = "https://openalex.org/"

# Prefix DOI URL — dihapus saat normalisasi
OA_DOI_PREFIX: str = "https://doi.org/"

# Maksimum query yang dijalankan per panggilan (konsisten dengan S2)
OA_MAX_QUERIES: int = 3


# ── Public Functions ───────────────────────────────────────────────────────


async def fetch_from_openalex(
    queries: list[str],
    filters: dict[str, Any],
    max_candidates: int,
) -> list[dict[str, Any]]:
    """
    Fetch paper dari OpenAlex /works endpoint menggunakan search + filter.

    Args:
        queries: List query string. Maksimum 3 pertama yang dieksekusi.
        filters: Dict dari FindPapersFilters (year_from, year_to, dll).
        max_candidates: Jumlah maksimum kandidat yang ingin dikembalikan.

    Returns:
        List paper dalam schema internal Miselia (lihat normalize_oa_papers).

    Behavior:
        - User-Agent menyertakan email (polite pool Miselia/2.0).
        - asyncio.sleep(OA_POLITE_DELAY) setelah setiap request.
        - Semua exception di-log dan dilanjutkan ke query berikutnya (fail-open).
        - Paper tanpa title di-skip.

    Ref: Blueprint §18.1, §18.2
    """
    user_agent = f"Miselia/2.0 (mailto:{settings.OPENALEX_EMAIL})"
    headers: dict[str, str] = {"User-Agent": user_agent}

    active_queries = queries[:OA_MAX_QUERIES]
    per_query_limit = min(100, max_candidates // max(1, len(active_queries)))
    oa_filter_str = _build_oa_filter_string(filters)

    all_works: list[dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=OA_DEFAULT_TIMEOUT) as client:
        for query in active_queries:
            params: dict[str, Any] = {
                "search": query,
                "per-page": per_query_limit,
                "select": OA_SELECT_FIELDS,
            }
            if oa_filter_str:
                params["filter"] = oa_filter_str

            try:
                resp = await client.get(
                    f"{OA_BASE_URL}/works",
                    params=params,
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
                works = data.get("results", [])
                all_works.extend(works)

                logger.info(
                    "oa_fetch_ok",
                    query_prefix=query[:50],
                    count=len(works),
                )

            except httpx.TimeoutException:
                logger.warning(
                    "oa_timeout",
                    query_prefix=query[:50],
                )
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "oa_http_error",
                    query_prefix=query[:50],
                    status=exc.response.status_code,
                )
            except Exception as exc:
                logger.error(
                    "oa_unexpected_error",
                    query_prefix=query[:50],
                    error=str(exc),
                )

            # Polite delay setelah setiap request (termasuk yang error)
            # agar tetap di bawah 8 req/detik ke OpenAlex polite pool
            await asyncio.sleep(OA_POLITE_DELAY)

    normalized = normalize_oa_papers(all_works)
    logger.info(
        "oa_fetch_complete",
        raw_count=len(all_works),
        normalized_count=len(normalized),
    )
    return normalized


def normalize_oa_papers(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Normalisasi raw response OpenAlex /works ke schema internal Miselia.

    Schema internal:
        paper_id        : str  — "oa:{work_id}" (tanpa URL prefix OpenAlex)
        title           : str
        authors         : list[str]
        year            : int | None
        venue           : str | None
        citation_count  : int
        abstract        : str | None  — hasil reconstruct_abstract()
        doi             : str | None  — lowercase, tanpa "https://doi.org/"
        pdf_url         : str | None
        is_open_access  : bool
        source          : str  — selalu "openalex"
        full_text       : None  — tidak tersedia dari API
        abstract_language : None  — detect di-defer ke paper_service

    Gap S2-5: abstract_inverted_index bisa None → reconstruct_abstract aman handle None.
    """
    result: list[dict[str, Any]] = []

    for work in raw:
        title = work.get("title") or ""
        if not title.strip():
            # Skip paper tanpa judul — data tidak valid
            continue

        # paper_id: strip URL prefix OpenAlex dan tambah prefix "oa:"
        raw_id: str = work.get("id") or ""
        work_id = raw_id.replace(OA_ID_PREFIX, "").strip()
        paper_id = f"oa:{work_id}" if work_id else f"oa:{raw_id}"

        # authors: dari authorships → author.display_name
        authorships: list[dict[str, Any]] = work.get("authorships") or []
        authors: list[str] = []
        for authorship in authorships:
            author_obj: dict[str, Any] = authorship.get("author") or {}
            display_name: str = author_obj.get("display_name", "").strip()
            if display_name:
                authors.append(display_name)

        # venue: dari primary_location → source.display_name
        primary_location: dict[str, Any] = work.get("primary_location") or {}
        source_obj: dict[str, Any] = primary_location.get("source") or {}
        venue: str | None = source_obj.get("display_name") or None

        # abstract: reconstruct dari inverted index (Gap S2-5 — handle None)
        inverted_index: dict[str, Any] | None = work.get("abstract_inverted_index")
        abstract: str | None = reconstruct_abstract(inverted_index)

        # doi: normalize — strip URL prefix + lowercase
        raw_doi: str | None = work.get("doi")
        doi: str | None = None
        if raw_doi:
            doi = raw_doi.replace(OA_DOI_PREFIX, "").lower().strip()
            if not doi:
                doi = None

        # open access
        open_access: dict[str, Any] = work.get("open_access") or {}
        is_open_access: bool = bool(open_access.get("is_oa", False))
        pdf_url: str | None = open_access.get("oa_url") or None

        result.append(
            {
                "paper_id": paper_id,
                "title": title.strip(),
                "authors": authors,
                "year": work.get("publication_year"),
                "venue": venue.strip() if venue else None,
                "citation_count": work.get("cited_by_count") or 0,
                "abstract": abstract,
                "doi": doi,
                "pdf_url": pdf_url,
                "is_open_access": is_open_access,
                "source": "openalex",
                "full_text": None,
                "abstract_language": None,
            }
        )

    return result


def reconstruct_abstract(inverted_index: dict[str, Any] | None) -> str | None:
    """
    Rebuild abstract dari OpenAlex inverted index format ke plain text.

    OpenAlex menyimpan abstract sebagai inverted index:
        {"word": [position1, position2, ...], "another": [position3]}

    Fungsi ini mengembalikan None jika:
        - inverted_index adalah None (Gap S2-5)
        - inverted_index kosong {}

    Args:
        inverted_index: Dict word → list[int] dari OpenAlex API,
                       atau None jika tidak tersedia.

    Returns:
        String abstract yang sudah di-reconstruct, atau None jika tidak ada.

    Ref: Blueprint §18.2
    """
    if not inverted_index:
        # None atau dict kosong — aman return None
        return None

    # Bangun mapping: position → word
    position_word: dict[int, str] = {}
    for word, positions in inverted_index.items():
        for pos in positions:
            position_word[pos] = word

    if not position_word:
        return None

    # Susun kata berdasarkan urutan posisi
    sorted_words = [position_word[pos] for pos in sorted(position_word.keys())]
    return " ".join(sorted_words)


# ── Private Helpers ────────────────────────────────────────────────────────


def _build_oa_filter_string(filters: dict[str, Any]) -> str:
    """
    Translate FindPapersFilters ke OpenAlex filter string format.

    OpenAlex filter format: "key:value,key2:value2" atau "key:>=value"

    Filter yang didukung OpenAlex:
        year_from → "publication_year:>={year_from}"
        year_to → "publication_year:<={year_to}"
        min_citations → "cited_by_count:>={n}"
        language "id" → "language:id"

    Filter yang TIDAK didukung di level API (difilter post-fetch):
        document_types → OpenAlex pakai "type" tapi mapping tidak 1:1

    Ref: Blueprint §18.2, §19.4, Gap F1-6
    """
    filter_parts: list[str] = []

    year_from: int | None = filters.get("year_from")
    year_to: int | None = filters.get("year_to")

    if year_from:
        filter_parts.append(f"publication_year:>={year_from}")
    if year_to:
        filter_parts.append(f"publication_year:<={year_to}")

    min_citations: int | None = filters.get("min_citations")
    if min_citations and min_citations > 0:
        filter_parts.append(f"cited_by_count:>={min_citations}")

    language: str | None = filters.get("language")
    if language and language.lower() == "id":
        # Tambah filter bahasa Indonesia untuk enrichment konteks lokal
        # Ref: Blueprint §19.4 — paper lokal sebagai konteks tambahan
        filter_parts.append("language:id")

    return ",".join(filter_parts)

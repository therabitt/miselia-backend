# ═══════════════════════════════════════════════════════════════════════════
# File    : app/integrations/semantic_scholar.py
# Desc    : HTTP client untuk Semantic Scholar Academic Graph API v1.
#           Tanggung jawab: fetch paper + normalize ke schema internal Miselia.
#           TIDAK mengandung business logic (dedup, ranking, cache) —
#           semua itu ada di app/services/paper_service.py.
#
#           Rate limit S2:
#             100 req / 5 menit per IP (tanpa key)
#             100 req / 5 menit dengan dedicated bucket (dengan API key)
#           Ref: Blueprint §18.1
#
#           Gap resolutions yang diimplementasikan:
#             Gap S2-3: API key dikirim conditional (tidak kirim jika None)
#             Gap S2-4: Field venue adalah object (bukan string langsung)
#
# Layer   : Integrations / External API Client
# Deps    : httpx, app.config, app.core.logging
# Step    : STEP 2 — Fase 1
# Ref     : Blueprint §18.1, §18.2, Fase 1 STEP 2
# ═══════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# ── Konstanta ─────────────────────────────────────────────────────────────

S2_BASE_URL: str = "https://api.semanticscholar.org/graph/v1"

# Field yang di-request dari S2 API.
# Catatan: publicationVenue dan journal keduanya di-request karena
# S2 tidak selalu mengisi keduanya secara konsisten (Gap S2-4).
S2_SEARCH_FIELDS: str = (
    "paperId,title,authors,year,citationCount,abstract,"
    "openAccessPdf,externalIds,publicationVenue,journal"
)

S2_DEFAULT_TIMEOUT: float = 30.0

# Maksimum query yang dijalankan per panggilan (hemat quota rate limit)
S2_MAX_QUERIES: int = 3


# ── Public Functions ───────────────────────────────────────────────────────


async def fetch_from_semantic_scholar(
    queries: list[str],
    filters: dict[str, Any],
    max_candidates: int,
) -> list[dict[str, Any]]:
    """
    Fetch paper dari Semantic Scholar menggunakan paper/search endpoint.

    Args:
        queries: List query string. Maksimum 3 pertama yang dieksekusi.
        filters: Dict dari FindPapersFilters (year_from, year_to, dll).
        max_candidates: Jumlah maksimum kandidat yang ingin dikembalikan.

    Returns:
        List paper dalam schema internal Miselia (lihat normalize_s2_papers).

    Behavior:
        - Loop maks S2_MAX_QUERIES query, limit per query dibagi merata.
        - HTTP 429: log warning + emit log event, hentikan loop (jangan retry).
        - TimeoutException: log warning + sleep 5 detik + lanjut query berikutnya.
        - Error lain: log error + lanjut query berikutnya.
        - API key dikirim hanya jika settings.SEMANTIC_SCHOLAR_API_KEY tidak None.

    Ref: Blueprint §18.2, Gap S2-3, Gap S2-4
    """
    # Build headers — API key conditional (Gap S2-3)
    headers: dict[str, str] = {"User-Agent": "Miselia/2.0"}
    if settings.SEMANTIC_SCHOLAR_API_KEY:
        headers["x-api-key"] = settings.SEMANTIC_SCHOLAR_API_KEY

    active_queries = queries[:S2_MAX_QUERIES]
    per_query_limit = min(100, max_candidates // max(1, len(active_queries)))
    s2_filter_params = _build_s2_filters(filters)

    all_papers: list[dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=S2_DEFAULT_TIMEOUT) as client:
        for query in active_queries:
            params: dict[str, Any] = {
                "query": query,
                "limit": per_query_limit,
                "fields": S2_SEARCH_FIELDS,
                **s2_filter_params,
            }

            try:
                resp = await client.get(
                    f"{S2_BASE_URL}/paper/search",
                    params=params,
                    headers=headers,
                )

                if resp.status_code == 429:
                    logger.warning(
                        "s2_rate_limit_429",
                        query_prefix=query[:50],
                        status=429,
                    )
                    # Hentikan seluruh loop — S2 bucket exhausted
                    break

                if resp.status_code == 400:
                    # Query tidak valid (terlalu pendek, karakter aneh, dll)
                    logger.warning(
                        "s2_bad_request",
                        query_prefix=query[:50],
                        status=400,
                        response=resp.text[:200],
                    )
                    continue

                resp.raise_for_status()
                data = resp.json()
                papers = data.get("data", [])
                all_papers.extend(papers)

                logger.info(
                    "s2_fetch_ok",
                    query_prefix=query[:50],
                    count=len(papers),
                )

            except httpx.TimeoutException:
                logger.warning(
                    "s2_timeout",
                    query_prefix=query[:50],
                )
                await asyncio.sleep(5)
                continue

            except httpx.HTTPStatusError as exc:
                logger.error(
                    "s2_http_error",
                    query_prefix=query[:50],
                    status=exc.response.status_code,
                )
                continue

            except Exception as exc:
                logger.error(
                    "s2_unexpected_error",
                    query_prefix=query[:50],
                    error=str(exc),
                )
                continue

    normalized = normalize_s2_papers(all_papers)
    logger.info(
        "s2_fetch_complete",
        raw_count=len(all_papers),
        normalized_count=len(normalized),
    )
    return normalized


def normalize_s2_papers(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Normalisasi raw response S2 ke schema internal Miselia.

    Schema internal:
        paper_id        : str  — "s2:{paperId}"
        title           : str
        authors         : list[str]
        year            : int | None
        venue           : str | None
        citation_count  : int
        abstract        : str | None
        doi             : str | None  — lowercase, stripped
        pdf_url         : str | None
        is_open_access  : bool
        source          : str  — selalu "semantic_scholar"
        full_text       : None  — tidak tersedia dari API
        abstract_language : None  — detect di-defer ke paper_service

    Gap S2-4: venue diambil dari publicationVenue.name ATAU journal.name.
    """
    result: list[dict[str, Any]] = []

    for paper in raw:
        title = paper.get("title") or ""
        if not title.strip():
            # Skip paper tanpa judul — data tidak valid
            continue

        # authors: list of {"name": "..."}
        authors_raw = paper.get("authors") or []
        authors: list[str] = [
            a.get("name", "").strip() for a in authors_raw if a.get("name", "").strip()
        ]

        # venue: Gap S2-4 — bisa dari publicationVenue atau journal (object, bukan string)
        pub_venue: dict[str, Any] = paper.get("publicationVenue") or {}
        journal: dict[str, Any] = paper.get("journal") or {}
        venue: str | None = pub_venue.get("name") or journal.get("name") or None

        # doi: dari externalIds, normalize ke lowercase + strip whitespace
        external_ids: dict[str, Any] = paper.get("externalIds") or {}
        raw_doi: str | None = external_ids.get("DOI")
        doi: str | None = raw_doi.lower().strip() if raw_doi else None

        # open access + pdf url
        open_access_pdf: dict[str, Any] = paper.get("openAccessPdf") or {}
        pdf_url: str | None = open_access_pdf.get("url") or None
        is_open_access: bool = pdf_url is not None

        result.append(
            {
                "paper_id": f"s2:{paper.get('paperId', '')}",
                "title": title.strip(),
                "authors": authors,
                "year": paper.get("year"),
                "venue": venue.strip() if venue else None,
                "citation_count": paper.get("citationCount") or 0,
                "abstract": paper.get("abstract") or None,
                "doi": doi,
                "pdf_url": pdf_url,
                "is_open_access": is_open_access,
                "source": "semantic_scholar",
                "full_text": None,
                "abstract_language": None,
            }
        )

    return result


# ── Private Helpers ────────────────────────────────────────────────────────


def _build_s2_filters(filters: dict[str, Any]) -> dict[str, Any]:
    """
    Translate FindPapersFilters ke S2 query parameters.

    S2 mendukung:
        yearFilter: "YYYY-YYYY" atau "YYYY-" atau "-YYYY"
        publicationTypes: comma-separated string (JournalArticle, Conference, etc.)

    Filter yang TIDAK di-support S2 (akan di-filter post-fetch di paper_service):
        min_citations → S2 tidak support, filter setelah fetch
        language → S2 tidak support, filter setelah fetch

    Ref: Blueprint §18.2, Gap F1-6
    """
    params: dict[str, Any] = {}

    year_from: int | None = filters.get("year_from")
    year_to: int | None = filters.get("year_to")

    if year_from and year_to:
        params["yearFilter"] = f"{year_from}-{year_to}"
    elif year_from:
        params["yearFilter"] = f"{year_from}-"
    elif year_to:
        params["yearFilter"] = f"-{year_to}"

    # document_types: map ke S2 publicationTypes
    doc_types: list[str] | None = filters.get("document_types")
    if doc_types:
        # Mapping: user-facing → S2 API value
        type_mapping: dict[str, str] = {
            "journal": "JournalArticle",
            "conference": "Conference",
            "review": "Review",
            "book_chapter": "BookSection",
            "preprint": "Preprint",
        }
        s2_types = [type_mapping[t] for t in doc_types if t in type_mapping]
        if s2_types:
            params["publicationTypes"] = ",".join(s2_types)

    return params

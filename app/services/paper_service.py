# ═══════════════════════════════════════════════════════════════════════════
# File    : app/services/paper_service.py
# Desc    : Paper service — business logic layer untuk fetch, dedup, dan ranking.
#
#           STEP 3 (bagian core) mencakup:
#             - compute_title_hash()         → SHA-256 fingerprint untuk dedup
#             - merge_and_dedup()            → deduplikasi S2 + OA, merge strategy
#             - calculate_relevance_score()  → ranking sesuai Blueprint §3.3
#             - check_s2_rate_limit()        → Redis sliding window untuk S2 API
#             - fetch_papers_with_resilience() → parallel fetch S2+OA dengan fallback
#
#           STEP 4 (belum diimplementasikan di file ini) akan menambahkan:
#             - get_cached_or_fetch()        → Redis cache layer (TTL 24 jam)
#             - should_run_query_translation() / augment_query_with_mapping()
#             - validate_paper_count()
#             - fetch_and_rank()             → fungsi utama yang dipanggil find_papers_service
#
#           PENTING — Separation of concerns:
#             - integrations/semantic_scholar.py & openalex.py → HTTP client saja
#             - services/paper_service.py (ini) → business logic
#             - core/rate_limit.py → user-facing rate limit (guest/auth endpoint)
#             - check_s2_rate_limit() di sini → S2 API sliding window (berbeda!)
#
# Layer   : Services / Paper
# Deps    : asyncio, hashlib, math, redis.asyncio, app.core.logging,
#           app.integrations.semantic_scholar, app.integrations.openalex
# Step    : STEP 3 — Fase 1
# Ref     : Blueprint §3.3, §18.1, §18.2, §18.5
# ═══════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import asyncio
import hashlib
import math
import re
import string
import time
from typing import Any

import redis.asyncio as aioredis

from app.config import settings
from app.core.logging import get_logger
from app.integrations.openalex import fetch_from_openalex
from app.integrations.semantic_scholar import fetch_from_semantic_scholar

logger = get_logger(__name__)

# ── Konstanta Rate Limit S2 API ───────────────────────────────────────────
# Catatan: Ini BUKAN sama dengan core/rate_limit.py.
# Ini adalah sliding window Redis untuk melacak BERAPA KALI kita hit S2 API,
# bukan berapa kali user hit endpoint kita.
# Ref: Blueprint §18.1, §18.2

S2_RATE_KEY: str = "rate:semantic_scholar"
S2_MAX_REQUESTS: int = 90       # 90 dari 100 sebagai safety buffer (Blueprint §18.2)
S2_WINDOW_SECONDS: int = 300    # 5 menit sesuai S2 rate limit window

# ── Konstanta Relevance Scoring ───────────────────────────────────────────
# Tahun base untuk recency bonus — sesuai Blueprint §3.3
_CURRENT_YEAR: int = 2026
_RECENCY_WINDOW: int = 5        # paper dalam 5 tahun terakhir mendapat bonus


# ── Redis Client (lazy init, terpisah dari core/rate_limit.py) ───────────

_redis_client: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    """
    Lazy-init Redis client untuk paper_service.
    Terpisah dari get_redis() di core/rate_limit.py agar tidak ada coupling.
    Menggunakan URL yang sama dari settings.REDIS_URL.
    """
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


# ── Helper: Title Normalization & Hashing ────────────────────────────────


def _normalize_title(title: str) -> str:
    """
    Normalisasi judul paper untuk keperluan dedup.
    Pipeline: lowercase → strip → remove punctuation → collapse whitespace.

    Contoh:
        "Machine Learning: A Survey (2022)" → "machine learning a survey 2022"

    Normalisasi yang konsisten memastikan dedup bekerja meski ada perbedaan
    kecil dalam penulisan judul antar sumber (S2 vs OA).
    """
    # Lowercase + strip
    normalized = title.lower().strip()
    # Hapus semua karakter non-alphanumeric kecuali spasi
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    # Collapse multiple whitespace menjadi satu
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def compute_title_hash(title: str, year: int | None) -> str:
    """
    Hitung SHA-256 fingerprint dari judul + tahun untuk keperluan dedup.

    Formula: SHA-256(normalize(title) + str(year or ""))
    Return: hex digest 64 karakter (sesuai kolom title_hash VARCHAR(64) di DB)

    Ref: Blueprint §984 (dedup strategy), kolom papers.title_hash
    """
    normalized = _normalize_title(title)
    year_str = str(year) if year else ""
    raw = f"{normalized}{year_str}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ── Core: Merge & Dedup ───────────────────────────────────────────────────


def merge_and_dedup(
    s2_papers: list[dict[str, Any]],
    oa_papers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Deduplikasi paper dari dua sumber (Semantic Scholar + OpenAlex) dan
    merge field-level menggunakan strategy yang terdefinisi.

    Dedup Priority (sesuai Blueprint §984):
      1. DOI: lowercase, stripped — paling reliable, hapus duplikat antar sumber
      2. Fallback: title_hash = SHA-256(normalize(title) + str(year)) — jika DOI kosong

    Merge Strategy per field:
      title         → S2 wins (lebih konsisten, title case)
      authors       → S2 wins (lebih structured)
      year          → S2 wins jika ada, fallback OA
      venue         → S2 wins jika ada, fallback OA
      citation_count → S2 wins (lebih sering diupdate, lebih akurat)
      abstract      → OA wins jika S2 None (OA lebih sering punya abstract)
      doi           → pertama yang ada (seharusnya sama)
      pdf_url       → OA wins (OA lebih sering punya oa_url yang valid)
      is_open_access → True jika salah satu sumber True (OR logic)
      source        → "semantic_scholar+openalex" jika dari keduanya, else sumber asal

    Args:
        s2_papers: List paper dari Semantic Scholar (sudah normalized)
        oa_papers: List paper dari OpenAlex (sudah normalized)

    Returns:
        List paper yang sudah di-dedup dan di-merge (Gap P3-2, P3-3)

    Ref: Blueprint §3.3, §18.2, Gap P3-2, Gap P3-3
    """
    # ── Pass 1: Index S2 papers by DOI dan title_hash ──────────────────
    doi_index: dict[str, dict[str, Any]] = {}       # doi → paper dict
    hash_index: dict[str, dict[str, Any]] = {}      # title_hash → paper dict
    merged: list[dict[str, Any]] = []               # hasil akhir

    for paper in s2_papers:
        doi = paper.get("doi")
        title = paper.get("title", "")
        year = paper.get("year")
        th = compute_title_hash(title, year)

        # Simpan ke index
        if doi:
            doi_index[doi] = paper
        hash_index[th] = paper
        merged.append(paper)

    # ── Pass 2: Loop OA papers, merge jika duplikat, tambah jika baru ──
    dupes_removed = 0

    for oa_paper in oa_papers:
        oa_doi = oa_paper.get("doi")
        oa_title = oa_paper.get("title", "")
        oa_year = oa_paper.get("year")
        oa_hash = compute_title_hash(oa_title, oa_year)

        # Cek duplikat: doi first, fallback title_hash
        existing: dict[str, Any] | None = None
        if oa_doi and oa_doi in doi_index:
            existing = doi_index[oa_doi]
        elif oa_hash in hash_index:
            existing = hash_index[oa_hash]

        if existing is not None:
            # ── Duplikat ditemukan → merge OA ke existing S2 entry ─────
            dupes_removed += 1

            # abstract: OA wins jika S2 tidak punya
            if not existing.get("abstract") and oa_paper.get("abstract"):
                existing["abstract"] = oa_paper["abstract"]

            # pdf_url: OA wins (OA lebih sering punya oa_url valid)
            if not existing.get("pdf_url") and oa_paper.get("pdf_url"):
                existing["pdf_url"] = oa_paper["pdf_url"]

            # is_open_access: OR — True jika salah satu True
            if oa_paper.get("is_open_access"):
                existing["is_open_access"] = True

            # source: update ke combined jika sebelumnya single source
            if existing.get("source") == "semantic_scholar":
                existing["source"] = "semantic_scholar+openalex"

            # doi: isi jika S2 tidak punya DOI tapi OA punya
            if not existing.get("doi") and oa_doi:
                existing["doi"] = oa_doi
                doi_index[oa_doi] = existing

        else:
            # ── Paper baru dari OA, belum ada di S2 ────────────────────
            merged.append(oa_paper)
            if oa_doi:
                doi_index[oa_doi] = oa_paper
            hash_index[oa_hash] = oa_paper

    logger.info(
        "dedup_complete",
        s2_count=len(s2_papers),
        oa_count=len(oa_papers),
        merged_count=len(merged),
        dupes_removed=dupes_removed,
    )

    return merged


# ── Core: Relevance Scoring ───────────────────────────────────────────────


def calculate_relevance_score(paper: dict[str, Any], query_terms: list[str]) -> float:
    """
    Hitung relevance score paper terhadap query terms.

    Formula sesuai Blueprint §3.3 VERBATIM:
      title_match_ratio    = matches_in_title / len(query_terms)    × 0.4
      abstract_match_ratio = matches_in_abstract / len(query_terms) × 0.3 (jika abstract ada)
      citation_score       = min(log10(citation_count + 1) / 4, 1.0) × 0.2
      recency_bonus        = +0.1 jika year >= (current_year - recency_window)
      TOTAL                = min(sum, 1.0)

    Args:
        paper: Dict paper dalam schema internal Miselia
        query_terms: List kata dari query user (sudah di-split dan lowercase)

    Returns:
        Float 0.0–1.0

    Gap P3-4: Guard untuk query_terms kosong → return 0.0 (cegah ZeroDivisionError)

    Ref: Blueprint §3.3
    """
    # Gap P3-4: guard empty query_terms
    if not query_terms:
        return 0.0

    score: float = 0.0
    title: str = (paper.get("title") or "").lower()
    abstract: str | None = paper.get("abstract")
    citation_count: int = paper.get("citation_count") or 0
    year: int | None = paper.get("year")

    # ── Component 1: Title match (weight 0.4) ─────────────────────────
    title_matches = sum(1 for term in query_terms if term.lower() in title)
    score += (title_matches / len(query_terms)) * 0.4

    # ── Component 2: Abstract match (weight 0.3, hanya jika ada abstract) ─
    if abstract:
        abstract_lower = abstract.lower()
        abstract_matches = sum(1 for term in query_terms if term.lower() in abstract_lower)
        score += (abstract_matches / len(query_terms)) * 0.3

    # ── Component 3: Citation score (weight 0.2, log scale) ───────────
    # log10(0+1)=0, log10(9+1)≈1.0, log10(9999+1)≈4.0
    # Dibagi 4 agar cap di 1.0 tercapai saat citation_count ≈ 10000
    citation_score = min(math.log10(citation_count + 1) / 4, 1.0)
    score += citation_score * 0.2

    # ── Component 4: Recency bonus (weight 0.1) ───────────────────────
    if year and year >= (_CURRENT_YEAR - _RECENCY_WINDOW):
        score += 0.1

    # Cap di 1.0
    return min(score, 1.0)


# ── S2 API Rate Limit (Sliding Window ZSET) ───────────────────────────────


async def check_s2_rate_limit() -> bool:
    """
    Cek apakah kita masih bisa hit Semantic Scholar API.
    Menggunakan Redis sliding window dengan Sorted Set (ZSET).

    Pattern (sesuai Blueprint §18.2, diperbaiki dari Gap S2-2):
      ZREMRANGEBYSCORE  → hapus entries lama di luar window
      ZCARD             → hitung entries aktif dalam window
      Jika count < S2_MAX_REQUESTS: ZADD entry baru, return True
      Else: return False (throttled, skip S2)

    Return:
      True  → S2 bisa di-hit (belum mencapai limit)
      False → S2 throttled (gunakan OA saja)

    Fail-open: jika Redis down → return True (jangan block request karena infra)

    Gap S2-2 resolution: menggunakan async pipeline Redis yang benar.
    Ref: Blueprint §18.2
    """
    try:
        redis = _get_redis()
        now = time.time()
        window_start = now - S2_WINDOW_SECONDS

        # Gunakan pipeline async untuk atomicity
        async with redis.pipeline(transaction=False) as pipe:
            # Hapus entries yang sudah di luar window
            pipe.zremrangebyscore(S2_RATE_KEY, 0, window_start)
            # Hitung jumlah entries dalam window saat ini
            pipe.zcard(S2_RATE_KEY)
            results = await pipe.execute()

        current_count: int = results[1]  # hasil ZCARD

        if current_count < S2_MAX_REQUESTS:
            # Masih boleh — tambahkan entry baru dan set TTL
            async with redis.pipeline(transaction=False) as pipe:
                pipe.zadd(S2_RATE_KEY, {str(now): now})
                pipe.expire(S2_RATE_KEY, S2_WINDOW_SECONDS + 60)  # TTL safety
                await pipe.execute()
            return True
        else:
            logger.warning(
                "s2_rate_limit_reached",
                current_count=current_count,
                max_requests=S2_MAX_REQUESTS,
                window_seconds=S2_WINDOW_SECONDS,
            )
            return False

    except Exception as exc:
        # Fail-open: Redis down tidak boleh memblokir request
        logger.warning(
            "s2_rate_limit_redis_error",
            error=str(exc),
            action="fail_open_allow_s2",
        )
        return True


# ── Core: Parallel Fetch dengan Resilience ───────────────────────────────


async def fetch_papers_with_resilience(
    optimized_queries: list[str],
    filters: dict[str, Any],
    max_candidates: int = 100,
    pipeline: str = "find_papers",
) -> list[dict[str, Any]]:
    """
    Fetch paper dari S2 + OpenAlex secara paralel dengan rate limit handling.

    Strategy (sesuai Blueprint §18.2, diperbaiki dari Gap S2-1):
      1. Pre-check S2 rate limit SEBELUM membuat tasks (fix asyncio.TaskGroup bug)
      2. OA selalu di-fetch (lebih longgar rate limit-nya)
      3. S2 di-fetch hanya jika rate limit belum tercapai
      4. asyncio.gather dengan return_exceptions=True (fail-safe)
      5. Filter Exception dari hasil gather sebelum merge
      6. merge_and_dedup(s2_results, oa_results)

    Args:
        optimized_queries: List query string yang sudah dioptimasi
        filters: Dict FindPapersFilters
        max_candidates: Total maksimum kandidat paper
        pipeline: Nama pipeline pemanggil (untuk logging/analytics)

    Returns:
        List paper yang sudah di-dedup, siap untuk ranking

    Gap S2-1 resolution: pre-check rate limit di luar gather, tidak await di dalam TaskGroup.
    Gap P3-5 resolution: filter Exception results dari asyncio.gather.
    Ref: Blueprint §18.2, §18.5
    """
    # ── Step 1: Pre-check S2 rate limit ──────────────────────────────
    s2_allowed = await check_s2_rate_limit()

    if not s2_allowed:
        logger.warning(
            "s2_rate_limit_skipped",
            pipeline=pipeline,
            action="openalex_only",
        )

    # ── Step 2: Bangun task list ──────────────────────────────────────
    # OA selalu ada. S2 conditional berdasarkan rate limit.
    # Gap S2-1: task list dibangun SEBELUM gather, bukan di dalam TaskGroup.
    coroutines = []
    s2_included = False

    if s2_allowed:
        coroutines.append(
            fetch_from_semantic_scholar(optimized_queries, filters, max_candidates)
        )
        s2_included = True

    coroutines.append(
        fetch_from_openalex(optimized_queries, filters, max_candidates)
    )

    # ── Step 3: Parallel fetch ────────────────────────────────────────
    # return_exceptions=True: jika salah satu gagal, yang lain tetap jalan
    results = await asyncio.gather(*coroutines, return_exceptions=True)

    # ── Step 4: Parse hasil + filter Exception (Gap P3-5) ─────────────
    s2_results: list[dict[str, Any]] = []
    oa_results: list[dict[str, Any]] = []

    if s2_included:
        s2_raw = results[0]
        oa_raw = results[1]
    else:
        s2_raw = []
        oa_raw = results[0]

    # Filter Exception — jangan crash jika salah satu task gagal
    if isinstance(s2_raw, Exception):
        logger.error(
            "s2_gather_exception",
            error=str(s2_raw),
            pipeline=pipeline,
        )
        s2_results = []
    else:
        s2_results = s2_raw if isinstance(s2_raw, list) else []

    if isinstance(oa_raw, Exception):
        logger.error(
            "oa_gather_exception",
            error=str(oa_raw),
            pipeline=pipeline,
        )
        oa_results = []
    else:
        oa_results = oa_raw if isinstance(oa_raw, list) else []

    # ── Step 5: Merge + Dedup ─────────────────────────────────────────
    merged = merge_and_dedup(s2_results, oa_results)

    logger.info(
        "fetch_papers_complete",
        s2_count=len(s2_results),
        oa_count=len(oa_results),
        merged_count=len(merged),
        pipeline=pipeline,
        s2_was_included=s2_included,
    )

    return merged

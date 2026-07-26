# ═══════════════════════════════════════════════════════════════════════════
# File    : app/services/paper_service.py
# Desc    : Paper service — business logic layer untuk fetch, dedup, dan ranking.
#
#           STEP 3 (core) mencakup:
#             - compute_title_hash()           → SHA-256 fingerprint untuk dedup
#             - merge_and_dedup()              → deduplikasi S2 + OA, merge strategy
#             - calculate_relevance_score()    → ranking sesuai Blueprint §3.3
#             - check_s2_rate_limit()          → Redis sliding window untuk S2 API
#             - fetch_papers_with_resilience() → parallel fetch S2+OA dengan fallback
#
#           STEP 4 (extended) mencakup:
#             - _build_cache_key()             → deterministic Redis key untuk paper cache
#             - get_cached_or_fetch()          → Redis cache layer (TTL: PAPER_CACHE_TTL)
#             - dedup_single_list()            → dedup satu list (untuk augmented results)
#             - COLD_START_THRESHOLD, MIN_PAPERS_FOR_RUN → threshold Blueprint §19.2–19.5
#             - INDONESIAN_MARKERS             → heuristic trigger cold start check
#             - INDONESIAN_CONCEPT_MAPPING     → mapping UMKM→SME, dll (Blueprint §19.3)
#             - PROMPT_0_QUERY_TRANSLATION     → template prompt terjemahan (Blueprint §19.2)
#             - should_run_query_translation() → cek apakah perlu query translation
#             - augment_query_with_mapping()   → replace keyword lokal dengan ekuivalen
#             - validate_paper_count()         → graceful degradation + augmentasi
#             - fetch_and_rank()               → fungsi utama dipanggil find_papers_service
#
#           PENTING — Separation of concerns:
#             - integrations/semantic_scholar.py & openalex.py → HTTP client saja
#             - services/paper_service.py (ini) → business logic
#             - core/rate_limit.py → user-facing rate limit (guest/auth endpoint)
#             - check_s2_rate_limit() di sini → S2 API sliding window (berbeda!)
#
# Layer   : Services / Paper
# Deps    : asyncio, hashlib, json, math, redis.asyncio, app.core.logging,
#           app.integrations.semantic_scholar, app.integrations.openalex
# Step    : STEP 3 + STEP 4 — Fase 1
# Ref     : Blueprint §3.3, §18.1, §18.2, §18.3, §18.5, §19.2–19.5
# ═══════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import time
from typing import Any

import redis.asyncio as aioredis

from app.config import settings
from app.core.exceptions import InsufficientPapersError
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


# ═══════════════════════════════════════════════════════════════════════════════
# STEP 4: Redis Cache Layer + Indonesian Query Strategy + Graceful Degradation
# Ref: Blueprint §18.3, §19.2–19.5
# ═══════════════════════════════════════════════════════════════════════════════

# ── Threshold Constants ───────────────────────────────────────────────────────
# Nilai verbatim dari Blueprint §19.2 dan §19.5

COLD_START_THRESHOLD: int = 5
# Minimum paper relevan sebelum cold start strategy dipicu.
# < 5 paper tidak cukup untuk menghasilkan lit review yang koheren.
# Ref: Blueprint §19.2

MIN_PAPERS_FOR_RUN: int = 5
# Minimum paper yang harus ada agar pipeline bisa berjalan.
# Jika masih < 5 setelah augmentasi → raise InsufficientPapersError.
# Ref: Blueprint §19.5


# ── Indonesian Cold Start Detection ──────────────────────────────────────────
# Verbatim dari Blueprint §19.2 — daftar kata penanda konteks lokal Indonesia.
# Dipakai oleh should_run_query_translation() sebagai heuristic trigger.

INDONESIAN_MARKERS: list[str] = [
    "umkm", "bumdes", "kelurahan", "kecamatan", "desa", "kabupaten",
    "provinsi", "daerah", "lokal", "nasional", "indonesia", "jawa",
    "bali", "sumatera", "sulawesi", "kalimantan", "papua", "ntt", "nusa tenggara",
    "batik", "wayang", "adat", "pesantren", "madrasah",
]


# ── Indonesian Concept Mapping ────────────────────────────────────────────────
# Verbatim dari Blueprint §19.3 — mapping istilah lokal Indonesia ke ekuivalen
# akademik internasional. Dipakai oleh augment_query_with_mapping().

INDONESIAN_CONCEPT_MAPPING: dict[str, list[str]] = {
    # Institusi & organisasi
    "umkm": ["SME", "small medium enterprise", "micro enterprise", "informal economy"],
    "bumdes": ["village enterprise", "rural cooperative", "community enterprise"],
    "pesantren": ["Islamic boarding school", "religious education institution"],
    "koperasi": ["cooperative", "credit union", "mutual organization"],

    # Konsep sosial-ekonomi
    "ketahanan pangan": ["food security", "food resilience"],
    "kemiskinan": ["poverty", "income inequality", "livelihood"],
    "pemberdayaan masyarakat": ["community empowerment", "social capital", "capacity building"],
    "otonomi daerah": ["regional autonomy", "decentralization", "local governance"],

    # Pendidikan
    "kurikulum merdeka": ["student-centered curriculum", "competency-based education"],
    "pembelajaran daring": ["online learning", "e-learning", "distance education"],

    # Pariwisata
    "wisata halal": ["halal tourism", "Muslim-friendly tourism"],
    "desa wisata": ["rural tourism", "village tourism", "agrotourism"],

    # Teknologi & digital
    "fintech syariah": ["Islamic fintech", "sharia-compliant financial technology"],
    "e-commerce lokal": ["local e-commerce", "digital marketplace", "platform economy"],
}


# ── Prompt Template Query Translation ────────────────────────────────────────
# Verbatim dari Blueprint §19.2 — dipakai oleh pipeline P1/P2 untuk
# menerjemahkan topik lokal Indonesia ke query akademik internasional.
# Belum dipanggil di STEP 4 — hanya didefinisikan sebagai string konstanta.
# Curly braces double-escaped {{ }} karena string ini adalah f-string template
# yang akan di-format oleh caller saat pemanggilan OpenAI.

PROMPT_0_QUERY_TRANSLATION: str = """\
Kamu adalah asisten penelitian yang ahli dalam menerjemahkan topik penelitian lokal
menjadi query pencarian paper akademik internasional yang efektif.

Topik penelitian: {topic}
Bidang studi: {field_of_study}
Konteks: Topik ini ditulis dalam konteks Indonesia dan mungkin memiliki nama lokal
yang perlu diterjemahkan atau diabstraksikan ke konsep universal.

Tugasmu:
1. Identifikasi konsep inti dari topik (terlepas dari konteks lokal)
2. Terjemahkan ke istilah akademik dalam Bahasa Inggris yang umum digunakan
   dalam literatur internasional
3. Sertakan keyword lokal sebagai konteks (dalam bahasa aslinya) untuk filter
   jika tersedia paper yang membahas konteks ASEAN atau Asia Tenggara

Output HANYA JSON:
{{
  "core_concepts": ["concept 1", "concept 2", "concept 3"],
  "english_translation": "abstracted topic in English academic terms",
  "local_keywords": ["keyword lokal 1", "keyword lokal 2"],
  "suggested_queries_en": [
    "broad query in English",
    "specific query with methodology",
    "Southeast Asia context query"
  ],
  "local_context_note": "Apakah ada ekuivalen konsep internasional yang langsung? (y/n + penjelasan)"
}}
"""


# ── Redis Cache: Private Key Builder ─────────────────────────────────────────


def _build_cache_key(query: str, filters: dict[str, Any]) -> str:
    """
    Buat cache key yang deterministic untuk paper cache Redis.

    Formula: f"paper_cache:{SHA-256(query + json(filters, sort_keys=True))[:16]}"

    Gap P4-6 resolution: json.dumps dengan sort_keys=True menggantikan
    str(sorted(filters.items())) dari Blueprint — lebih reliable untuk
    nested structures (list/dict sebagai value).

    Args:
        query: Query string yang dikirim ke API
        filters: Dict filter (year_from, year_to, dll)

    Returns:
        String key Redis dalam format "paper_cache:{16-char hex}"

    Ref: Blueprint §18.3
    """
    filters_str = json.dumps(filters, sort_keys=True, default=str)
    raw = query + filters_str
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"paper_cache:{digest}"


# ── Redis Cache: Get-or-Fetch ─────────────────────────────────────────────────


async def get_cached_or_fetch(
    query: str,
    filters: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    Check Redis cache sebelum hit API eksternal.

    Strategy (sesuai Blueprint §18.3):
      Cache hit  → return parsed JSON + log paper_cache_hit
      Cache miss → fetch_papers_with_resilience → simpan ke Redis → return

    TTL: settings.PAPER_CACHE_TTL (default 86400 = 24 jam)
    Cache key: _build_cache_key(query, filters) → 16-char SHA-256 prefix

    Gap P4-1 resolution: semua Redis call menggunakan await (async API).
    Gap P4-2 resolution: log paper_cache_hit via structlog, bukan track_event().
    Fail-open: jika Redis error → langsung fetch, tidak crash.

    Args:
        query: Query string utama
        filters: Dict filter yang dipakai saat fetch

    Returns:
        List paper dalam schema internal Miselia

    Ref: Blueprint §18.3
    """
    cache_key = _build_cache_key(query, filters)
    redis = _get_redis()

    # ── Cache check ───────────────────────────────────────────────────
    try:
        cached_raw: str | None = await redis.get(cache_key)
        if cached_raw:
            logger.info(
                "paper_cache_hit",
                query_prefix=query[:30],
                cache_key=cache_key,
            )
            return json.loads(cached_raw)
    except Exception as exc:
        # Redis read error → fail-open, lanjut ke fetch
        logger.warning(
            "paper_cache_read_error",
            error=str(exc),
            action="proceed_to_fetch",
        )

    # ── Cache miss → fetch ────────────────────────────────────────────
    results = await fetch_papers_with_resilience(
        optimized_queries=[query],
        filters=filters,
        max_candidates=100,
        pipeline="cached_fetch",
    )

    # ── Simpan ke cache ───────────────────────────────────────────────
    try:
        await redis.setex(
            cache_key,
            settings.PAPER_CACHE_TTL,
            json.dumps(results),
        )
        logger.info(
            "paper_cache_miss_stored",
            query_prefix=query[:30],
            result_count=len(results),
            ttl=settings.PAPER_CACHE_TTL,
        )
    except Exception as exc:
        # Redis write error → tidak fatal, hasil tetap dikembalikan
        logger.warning(
            "paper_cache_write_error",
            error=str(exc),
        )

    return results


# ── Dedup Tunggal (Private) ───────────────────────────────────────────────────


def _dedup_single_list(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Deduplikasi satu list paper menggunakan DOI-first + title_hash fallback.

    Diperlukan oleh validate_paper_count() dan fetch_and_rank() untuk dedup
    setelah menggabungkan hasil augmented fetch dengan hasil awal.
    Berbeda dari merge_and_dedup() yang menerima dua list terpisah (S2 vs OA).

    Strategy:
      - Loop paper → skip jika doi atau title_hash sudah terlihat
      - Pertahankan urutan (paper pertama menang — biasanya lebih relevan)

    Gap P4-3 resolution: fungsi ini menggantikan deduplicate() yang tidak ada
    di Blueprint §19.5.

    Args:
        papers: List paper dalam schema internal Miselia

    Returns:
        List paper yang sudah di-dedup, urutan asli dipertahankan
    """
    seen_doi: set[str] = set()
    seen_hash: set[str] = set()
    result: list[dict[str, Any]] = []

    for paper in papers:
        doi = paper.get("doi")
        title = paper.get("title", "")
        year = paper.get("year")
        th = compute_title_hash(title, year)

        if doi and doi in seen_doi:
            continue
        if th in seen_hash:
            continue

        if doi:
            seen_doi.add(doi)
        seen_hash.add(th)
        result.append(paper)

    return result


# ── Indonesian Cold Start: Detection ─────────────────────────────────────────


def should_run_query_translation(
    topic: str,
    field_of_study: str,
    initial_result_count: int = 0,
) -> bool:
    """
    Tentukan apakah perlu menjalankan Prompt 0 (Query Translation) untuk topik.

    Trigger kondisi (sesuai Blueprint §19.2 VERBATIM):
      1. initial_result_count < COLD_START_THRESHOLD
         → trigger paling reliable, tidak butuh heuristic string
      2. ATAU topic mengandung kata dari INDONESIAN_MARKERS
         → topik sangat lokal, kemungkinan besar cold start

    Args:
        topic: Topik penelitian dari user (bisa Bahasa Indonesia atau Inggris)
        field_of_study: Bidang studi (tersedia untuk konteks future use)
        initial_result_count: Jumlah paper relevan dari fetch awal

    Returns:
        True  → jalankan query translation sebelum retry
        False → tidak perlu (hasil awal sudah cukup)

    Ref: Blueprint §19.2
    """
    # Trigger 1: result count terlalu sedikit (paling reliable)
    if initial_result_count < COLD_START_THRESHOLD:
        return True

    # Trigger 2: heuristic string matching — topik sangat lokal
    topic_lower = topic.lower()
    return any(marker in topic_lower for marker in INDONESIAN_MARKERS)


# ── Indonesian Cold Start: Query Augmentation ─────────────────────────────────


def augment_query_with_mapping(topic: str) -> list[str]:
    """
    Replace atau augmentasi keyword lokal Indonesia dengan ekuivalen akademik
    internasional menggunakan INDONESIAN_CONCEPT_MAPPING.

    Strategy (sesuai Blueprint §19.3 VERBATIM):
      - Cari setiap indo_term dalam topic (case-insensitive via .lower())
      - Jika ditemukan: buat augmented query dengan replace term → ekuivalen
      - Maksimum 2 ekuivalen per term ([:2])
      - Return [topic] jika tidak ada match (original sebagai fallback)

    Args:
        topic: Topik penelitian dari user

    Returns:
        List query yang sudah di-augmentasi.
        Return [topic] jika tidak ada keyword lokal yang ditemukan.

    Ref: Blueprint §19.3
    """
    augmented: list[str] = []
    topic_lower = topic.lower()

    for indo_term, en_equivalents in INDONESIAN_CONCEPT_MAPPING.items():
        if indo_term in topic_lower:
            for en_term in en_equivalents[:2]:  # max 2 ekuivalen per term
                augmented_query = topic_lower.replace(indo_term, en_term)
                augmented.append(augmented_query)

    return augmented if augmented else [topic]


# ── Graceful Degradation: Validate Paper Count ───────────────────────────────


async def validate_paper_count(
    papers: list[dict[str, Any]],
    stage_type: str,
    topic: str,
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Validasi jumlah paper setelah fetch, sebelum LLM synthesis.
    Mencoba augmentasi query jika paper terlalu sedikit.

    Strategy (sesuai Blueprint §19.5, dengan perbaikan Gap P4-3, P4-4):
      Jika len(papers) < MIN_PAPERS_FOR_RUN:
        1. stage_type in {'literature_review', 'systematic_review'}:
           → augment_query_with_mapping(topic)
           → fetch additional (max 50 candidates)
           → _dedup_single_list(papers + additional)
        2. Jika masih < MIN_PAPERS_FOR_RUN: raise InsufficientPapersError

    Gap P4-4 resolution: return list[dict] bukan mutate-in-place.
      Caller HARUS menggunakan return value:
        papers = await validate_paper_count(papers, ...)

    Gap P4-3 resolution: _dedup_single_list() menggantikan deduplicate()
      yang tidak ada di Blueprint asli.

    Args:
        papers: List paper yang sudah di-fetch
        stage_type: Tipe stage pipeline ('literature_review', dll)
        topic: Topik penelitian (untuk augmentasi dan pesan error)
        filters: Filter yang dipakai saat fetch awal (untuk retry augmented)

    Returns:
        List paper final (sudah di-augment dan di-dedup jika perlu)

    Raises:
        InsufficientPapersError: jika paper < MIN_PAPERS_FOR_RUN setelah augmentasi

    Ref: Blueprint §19.5
    """
    # Mutable default fix — jangan pakai {} sebagai default argument (Gap P4-7 style)
    safe_filters: dict[str, Any] = filters if filters is not None else {}

    if len(papers) < MIN_PAPERS_FOR_RUN:
        if stage_type in {"literature_review", "systematic_review"}:
            augmented_queries = augment_query_with_mapping(topic)
            logger.info(
                "validate_paper_count_augmenting",
                initial_count=len(papers),
                stage_type=stage_type,
                augmented_queries=augmented_queries[:2],
            )

            additional = await fetch_papers_with_resilience(
                optimized_queries=augmented_queries,
                filters=safe_filters,
                max_candidates=50,
                pipeline="narrative",
            )

            # Dedup gabungan: papers awal + augmented results
            papers = _dedup_single_list(papers + additional)

            logger.info(
                "validate_paper_count_after_augment",
                count_after=len(papers),
                additional_found=len(additional),
            )

    # Final check setelah augmentasi (atau tanpa augmentasi jika stage type lain)
    if len(papers) < MIN_PAPERS_FOR_RUN:
        raise InsufficientPapersError(
            paper_count=len(papers),
            topic=topic,
            suggestions=[
                "Coba perluas topik ke konsep yang lebih umum",
                "Gunakan istilah Bahasa Inggris jika topik sangat spesifik",
                "Kurangi batasan tahun — coba mulai dari 2000 jika sebelumnya 2015+",
            ],
        )

    return papers


# ── Fungsi Utama: Fetch → Cache → Augment → Rank ─────────────────────────────


async def fetch_and_rank(
    query: str,
    filters: dict[str, Any],
    query_terms: list[str],
    field_of_study: str = "",
    max_candidates: int = 100,
) -> list[dict[str, Any]]:
    """
    Fungsi utama paper service — dipanggil oleh find_papers_service (STEP 6).

    Orchestrasi:
      1. get_cached_or_fetch(query, filters)
         → cek Redis cache, fetch dari S2+OA jika miss
      2. Cold start check via should_run_query_translation()
         → jika triggered: augment_query_with_mapping(query)
         → fetch additional dengan augmented queries
         → _dedup_single_list(papers + additional)
      3. calculate_relevance_score() untuk setiap paper → tambahkan ke dict
      4. Sort descending by relevance_score
      5. Return list terurut

    Gap P4-5 resolution: field_of_study sebagai parameter opsional
      untuk diteruskan ke should_run_query_translation() — trigger utama
      saat ini berbasis result count, field_of_study untuk future extension.

    Args:
        query: Query string utama (sudah dioptimasi oleh find_papers_service)
        filters: Dict FindPapersFilters (year_from, year_to, dll)
        query_terms: List kata untuk relevance scoring (lowercase)
        field_of_study: Bidang studi untuk konteks cold start (opsional)
        max_candidates: Maksimum kandidat paper per fetch

    Returns:
        List paper terurut by relevance_score descending.
        Field 'relevance_score' (float 0.0–1.0) ditambahkan ke setiap paper dict.

    Ref: Blueprint §3.3, §18.3, §19.2–19.4
    """
    # ── Step 1: Get from cache atau fetch fresh ───────────────────────
    papers = await get_cached_or_fetch(query, filters)

    # ── Step 2: Cold start augmentation jika hasil terlalu sedikit ────
    if should_run_query_translation(
        topic=query,
        field_of_study=field_of_study,
        initial_result_count=len(papers),
    ):
        logger.info(
            "fetch_and_rank_cold_start_triggered",
            initial_count=len(papers),
            query_prefix=query[:50],
        )
        augmented_queries = augment_query_with_mapping(query)

        # Fetch dengan augmented queries (max_candidates // 2 untuk hemat quota)
        additional = await fetch_papers_with_resilience(
            optimized_queries=augmented_queries,
            filters=filters,
            max_candidates=max(50, max_candidates // 2),
            pipeline="cold_start_augment",
        )

        if additional:
            papers = _dedup_single_list(papers + additional)
            logger.info(
                "fetch_and_rank_augment_complete",
                final_count=len(papers),
                additional_found=len(additional),
            )

    # ── Step 3: Calculate relevance score dan tambahkan ke dict ───────
    for paper in papers:
        paper["relevance_score"] = calculate_relevance_score(paper, query_terms)

    # ── Step 4: Sort descending — paper paling relevan di atas ────────
    papers.sort(key=lambda p: p["relevance_score"], reverse=True)

    logger.info(
        "fetch_and_rank_complete",
        total_papers=len(papers),
        query_prefix=query[:50],
        top_score=papers[0]["relevance_score"] if papers else 0.0,
    )

    return papers

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

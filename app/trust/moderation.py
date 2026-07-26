# ═══════════════════════════════════════════════════════════════════════════
# File    : app/trust/moderation.py
# Desc    : Regex-based content moderation untuk Find Papers query input.
#
#           Layer ini berbeda dari services/moderation_service.py:
#             trust/moderation.py     → regex only, zero-latency, no API cost
#                                       dipanggil di Find Papers (high volume)
#             services/moderation_service.py → OpenAI Moderation API, cost-aware
#                                       dipanggil di POST /stage-runs dan /chat
#
#           Decision #29 (Blueprint §1.1 imp.): Find Papers topic TIDAK dimoderasi
#           via OpenAI — volume terlalu tinggi dan topik legitimate (kriminalitas,
#           narkoba, kesehatan jiwa) akan menghasilkan false positive tinggi.
#           Regex layer ini (Blueprint §8.1) adalah safety net yang cukup ringan
#           untuk konteks pencarian akademik.
#
#           ModerationResult didefinisikan di sini (satu tempat) dan diimport oleh
#           moderation_service.py — tidak ada duplikasi dataclass (Gap T5-1 fix).
#
# Layer   : Trust
# Deps    : re, dataclasses, app.core.logging
# Step    : STEP 5 — Fase 1
# Ref     : Blueprint §8.1, Decision #29
# ═══════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core.logging import get_logger

logger = get_logger(__name__)


# ── ModerationResult ─────────────────────────────────────────────────────────
# Satu dataclass untuk kedua layer moderation — regex dan OpenAI.
# Gap T5-1 resolution: satu definisi, diimport oleh moderation_service.py.
# Gap T5-3 resolution: field `flagged` ditambahkan (Blueprint §8.1 memakainya).


@dataclass
class ModerationResult:
    """
    Hasil evaluasi konten dari salah satu moderation layer.

    Fields:
        blocked : True jika konten diblokir — request harus dihentikan.
        reason  : Kategori alasan blokir / flag (None jika clean).
                  Tidak diekspos ke user — hanya untuk internal log.
        flagged : True jika konten dicatat tapi TIDAK diblokir.
                  Pipeline tetap berjalan, tapi event di-log.
                  Dipakai oleh regex layer untuk kasus academic integrity.
        scores  : Raw scores dari OpenAI Moderation API (dict kategori → float).
                  None untuk regex layer yang tidak menghasilkan scores numerik.

    Ref: Blueprint §8.1 (regex fields), Decision #29 (scores field)
    """

    blocked: bool
    reason: str | None = None
    flagged: bool = False
    scores: dict | None = None


# ── Regex Patterns ────────────────────────────────────────────────────────────
# Verbatim dari Blueprint §8.1.
#
# BLOCKED_PATTERNS: konten yang jelas tidak pantas dalam konteks akademik.
# Threshold sengaja ketat — tidak over-block topik penelitian legitimate.
# (kriminalitas, narkoba, trauma, konflik sosial sebagai TOPIK RISET tetap OK)
#
# FLAGGED_PATTERNS: konten yang dicatat tapi tidak diblokir.
# Pipeline tetap berjalan — event di-log untuk monitoring akademik integrity.

BLOCKED_PATTERNS: list[str] = [
    # Konten berbahaya: senjata, bahan peledak
    r"\b(cara\s+buat\s+bom|explosive|weapon\s+synthesis)\b",
    # Konten tidak pantas: judi, pornografi
    r"\b(judi|gambling|pornografi|porn)\b",
    # Konten penyalahgunaan sistem: hacking, bypass security
    r"\b(hack|crack|bypass\s+security)\b",
]

FLAGGED_PATTERNS: list[str] = [
    # Academic integrity concern — tidak diblokir, tapi dicatat
    r"\b(plagiat|plagiarism|copy\s+paste\s+skripsi)\b",
]

# Compile regex sekali saat modul di-import (performance optimization)
# re.IGNORECASE — bahasa Indonesia tidak case-sensitive untuk kata-kata ini
_compiled_blocked: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE) for p in BLOCKED_PATTERNS
]
_compiled_flagged: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE) for p in FLAGGED_PATTERNS
]


# ── moderate_query ────────────────────────────────────────────────────────────


def moderate_query(text: str) -> ModerationResult:
    """
    Evaluasi teks query menggunakan regex patterns.

    Dipakai untuk Find Papers query input — ringan, zero-latency, no API cost.
    BUKAN pengganti OpenAI Moderation API di moderation_service.py.

    Logic (sesuai Blueprint §8.1):
      1. Cek BLOCKED_PATTERNS → jika match: return blocked=True, reason="prohibited_content"
      2. Cek FLAGGED_PATTERNS → jika match: log + return blocked=False, flagged=True, reason="academic_integrity"
      3. Default: return blocked=False

    Args:
        text: Teks query yang akan dievaluasi (topik penelitian dari user)

    Returns:
        ModerationResult:
          - blocked=True  → caller harus raise ContentPolicyViolationError
          - flagged=True  → caller boleh lanjut, event dicatat di log
          - blocked=False, flagged=False → clean, lanjutkan

    Note:
        Fungsi ini SINKRON (bukan async) — regex tidak perlu I/O.
        Caller tidak perlu await.

    Ref: Blueprint §8.1
    """
    # ── Step 1: Hard block check ──────────────────────────────────────
    for pattern in _compiled_blocked:
        if pattern.search(text):
            logger.warning(
                "moderate_query_blocked",
                text_prefix=text[:50],
                pattern=pattern.pattern,
            )
            return ModerationResult(
                blocked=True,
                reason="prohibited_content",
            )

    # ── Step 2: Soft flag check ───────────────────────────────────────
    for pattern in _compiled_flagged:
        if pattern.search(text):
            logger.info(
                "moderate_query_flagged",
                text_prefix=text[:50],
                pattern=pattern.pattern,
                reason="academic_integrity",
            )
            return ModerationResult(
                blocked=False,
                flagged=True,
                reason="academic_integrity",
            )

    # ── Step 3: Clean ─────────────────────────────────────────────────
    return ModerationResult(blocked=False)

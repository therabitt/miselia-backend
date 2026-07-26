# ═══════════════════════════════════════════════════════════════════════════
# File    : app/services/moderation_service.py
# Desc    : OpenAI Moderation API — pre-execution gate untuk pipeline dan chat.
#
#           PENTING — Dibuat di Fase 1 tapi belum dipanggil dari endpoint mana pun.
#           Akan diaktifkan di Fase 3 saat POST /stage-runs dan POST /chat
#           diimplementasikan. File ini dibuat sekarang agar:
#             1. Arsitektur trust layer sudah lengkap sejak awal
#             2. STEP 6 (find_papers_service.py) bisa import langsung tanpa delay
#             3. Konsisten dengan Blueprint §2.2 struktur direktori
#
#           PERBEDAAN dari trust/moderation.py:
#             trust/moderation.py          → regex only, zero-latency, Find Papers
#             services/moderation_service.py → OpenAI API, cost-aware, pipeline/chat
#
#           Decision #29: Find Papers TIDAK dimoderasi via OpenAI.
#           moderate_content() HANYA dipanggil di:
#             1. POST /stage-runs  → sebelum Celery task di-enqueue
#                                    Input: input_params.topic
#             2. POST /chat/sessions/{id}/messages → sebelum AI call
#                                    Input: message content user
#
#           Tidak ada feature flag — moderation selalu aktif di production.
#           Ref: Decision #29 "Tidak ada feature flag — moderation selalu aktif."
#
# Layer   : Services / Moderation
# Deps    : openai, app.config, app.core.logging, app.trust.moderation
# Step    : STEP 5 — Fase 1
# Ref     : Blueprint Decision #29, §8.1
# ═══════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from openai import AsyncOpenAI

from app.config import settings
from app.core.logging import get_logger
from app.trust.moderation import ModerationResult

logger = get_logger(__name__)


# ── Thresholds sesuai Decision #29 VERBATIM ───────────────────────────────────
#
# MODERATION_HARD_BLOCK: kategori yang langsung memblokir jika score >= threshold.
#   Pipeline DIHENTIKAN. Return HTTP 400 ContentPolicyViolationError.
#   Threshold 0.7–0.8 dipilih agar tidak over-block topik penelitian legitimate
#   yang menyebut self-harm atau harassment secara akademis (psikologi, kriminologi).
#
# MODERATION_LOG_ONLY: kategori yang HANYA dicatat, pipeline tetap berjalan.
#   Score 0.5–0.6 sebagai soft threshold — perlu dicatat tapi tidak block.

MODERATION_HARD_BLOCK: dict[str, float] = {
    "harassment/threatening": 0.8,
    "self-harm":              0.8,
    "self-harm/intent":       0.7,
    "self-harm/instructions": 0.7,
}

MODERATION_LOG_ONLY: dict[str, float] = {
    "harassment": 0.5,
    "violence":   0.6,
}


# ── OpenAI Client (lazy init) ─────────────────────────────────────────────────
# Gap T5-5 resolution: lazy init konsisten dengan pola _get_redis() di paper_service.
# Tidak diinisialisasi di module level — menghindari startup error jika OPENAI_API_KEY
# belum di-set saat development atau testing.

_openai_client: AsyncOpenAI | None = None


def _get_openai_client() -> AsyncOpenAI:
    """
    Lazy-init AsyncOpenAI client untuk moderation_service.
    Menggunakan settings.OPENAI_API_KEY dari config.py (bukan os.environ langsung).
    """
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _openai_client


# ── moderate_content ──────────────────────────────────────────────────────────


async def moderate_content(text: str, context: str) -> ModerationResult:
    """
    Evaluasi konten menggunakan OpenAI Moderation API.

    Dipanggil sebagai pre-execution gate sebelum pipeline run dan chat message.
    TIDAK dipanggil untuk Find Papers — gunakan moderate_query() dari trust/moderation.py.

    Logic (sesuai Decision #29 VERBATIM):
      1. Hit OpenAI Moderation API dengan input text
      2. Extract category_scores dari response
      3. Loop MODERATION_HARD_BLOCK:
           jika score >= threshold → log warning + return blocked=True
      4. Loop MODERATION_LOG_ONLY:
           jika score >= threshold → log info saja, pipeline tetap lanjut
      5. Return blocked=False (clean)

    Args:
        text: Konten yang akan dievaluasi
              - Pipeline: input_params.topic (50–200 karakter)
              - Chat: message content user
        context: Label sumber pemanggilan untuk logging
                 Nilai valid: 'pipeline_topic' | 'chat_message'

    Returns:
        ModerationResult:
          blocked=True  → caller raise ContentPolicyViolationError (HTTP 400)
          blocked=False → lanjutkan eksekusi

    HTTP Response saat blocked (Decision #29):
        {
            "error": "content_policy_violation",
            "message": "Topik ini tidak bisa diproses. Coba ubah framing pertanyaanmu."
        }
        User TIDAK diberi tahu kategori spesifik yang terdeteksi.

    Gap T5-4 resolution: logger.info/warning menggantikan track_event() PostHog
      yang belum diimplementasikan. Akan ditambahkan saat PostHog diintegrasikan.
    Gap T5-6 resolution: logger = get_logger() (bukan log = get_logger()).

    Ref: Blueprint Decision #29
    """
    client = _get_openai_client()

    # ── Hit OpenAI Moderation API ─────────────────────────────────────
    response = await client.moderations.create(input=text)
    # category_scores adalah Pydantic model — convert ke dict untuk iterasi
    scores: dict[str, float] = response.results[0].category_scores.__dict__

    # ── Hard block check ──────────────────────────────────────────────
    for category, threshold in MODERATION_HARD_BLOCK.items():
        score = scores.get(category, 0.0)
        if score >= threshold:
            logger.warning(
                "content_moderation_blocked",
                context=context,
                category=category,
                score=round(score, 4),
                text_prefix=text[:30],
            )
            # Gap T5-4: logger.warning menggantikan track_event() yang belum ada
            # TODO (Fase 3): tambahkan PostHog track_event("content_moderation_blocked")
            return ModerationResult(
                blocked=True,
                reason=category,
                scores=scores,
            )

    # ── Log-only check ────────────────────────────────────────────────
    for category, threshold in MODERATION_LOG_ONLY.items():
        score = scores.get(category, 0.0)
        if score >= threshold:
            logger.info(
                "content_moderation_flagged_soft",
                context=context,
                category=category,
                score=round(score, 4),
                text_prefix=text[:30],
            )
            # Pipeline tetap lanjut — tidak return di sini

    # ── Clean ─────────────────────────────────────────────────────────
    return ModerationResult(
        blocked=False,
        scores=scores,
    )

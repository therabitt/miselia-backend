# ═══════════════════════════════════════════════════════════════════════════
# File    : app/core/tier_config.py
# Desc    : Konfigurasi tier subscription Miselia — single source of truth
#           untuk semua batas dan fitur per tier.
#
#           TIER_CONFIG adalah Python dict verbatim dari Blueprint §7.1.
#           Digunakan oleh: library_service, project_service, chat_service,
#           pipeline guards, subscription_service.
#
#           LibraryQuotaInfo: dataclass return type check_library_quota().
#           Return type diubah dari bool ke dataclass sesuai Decision #28
#           untuk mendukung partial import (import sebagian jika quota mepet).
#
#           SubscriptionTier enum: digunakan sebagai key TIER_CONFIG dan
#           type annotation di seluruh service layer.
#
# Layer   : Core / TierConfig
# Deps    : stdlib only (dataclasses, enum)
# Step    : STEP 3 — Fase 2
# Ref     : Blueprint §7.1, Decision #2, Decision #11, Decision #12, Decision #28
# ═══════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

# ── Tier Enum ─────────────────────────────────────────────────────────────


class SubscriptionTier(str, Enum):
    """
    Tier subscription Miselia.
    String enum — aman digunakan sebagai DB value dan JSON key.
    str(SubscriptionTier.FREE) == 'free' via __str__ override.
    Ref: Blueprint §7.1
    """

    FREE = "free"
    SARJANA = "sarjana"
    MAGISTER = "magister"
    INSTITUTIONAL = "institutional"

    def __str__(self) -> str:
        return self.value


# ── TierConfig Dataclass ──────────────────────────────────────────────────


@dataclass(frozen=True)
class TierConfig:
    """
    Konfigurasi lengkap satu tier — semua batas fitur dalam satu objek.
    frozen=True: tidak bisa diubah setelah dibuat (immutable config).
    Ref: Blueprint §7.1
    """

    # Project
    max_active_projects: int
    allowed_stage_types: list[str]
    max_papers_per_stage: int
    max_reruns_per_stage: Optional[int]  # None = unlimited

    can_use_systematic_review: bool  # True hanya untuk Magister

    # Chat with Papers
    chat_enabled: bool
    chat_messages_per_session: Optional[int]  # None = unlimited
    chat_sessions_per_month: Optional[int]  # None = unlimited; Free = 3/bulan kalender
    chat_memory_across_sessions: bool
    chat_papers_per_session: int

    # Library
    library_enabled: bool
    library_retention_days: Optional[int]  # None = permanent (Magister)
    max_library_papers: Optional[int]  # None = unlimited (Magister). Decision #28

    # DOCX output
    docx_watermark: bool

    # Pricing (IDR) — None untuk tier non-berbayar atau institutional (custom)
    price_monthly: Optional[int]
    price_biannual: Optional[int]


# ── TIER_CONFIG Dict ──────────────────────────────────────────────────────

TIER_CONFIG: dict[SubscriptionTier, TierConfig] = {
    SubscriptionTier.FREE: TierConfig(
        max_active_projects=1,
        allowed_stage_types=["literature_review"],
        max_papers_per_stage=15,
        max_reruns_per_stage=3,
        can_use_systematic_review=False,
        chat_enabled=True,
        chat_messages_per_session=5,
        chat_sessions_per_month=3,  # 3 sesi per bulan kalender, bukan lifetime
        chat_memory_across_sessions=False,
        chat_papers_per_session=3,
        library_enabled=True,
        library_retention_days=30,
        max_library_papers=50,  # Decision #28
        docx_watermark=True,
        price_monthly=None,
        price_biannual=None,
    ),
    SubscriptionTier.SARJANA: TierConfig(
        max_active_projects=3,
        allowed_stage_types=[
            "literature_review",
            "research_gap",
            "methodology_advisor",
            "hypothesis_variable",
            "proposisi_tema",
            "chapter_outline",
            "bab1_writer",
            "sidang_preparation",
        ],
        max_papers_per_stage=30,
        max_reruns_per_stage=None,  # Unlimited
        can_use_systematic_review=False,
        chat_enabled=True,
        chat_messages_per_session=None,  # Unlimited
        chat_sessions_per_month=None,  # Unlimited
        chat_memory_across_sessions=True,
        chat_papers_per_session=10,
        library_enabled=True,
        library_retention_days=365,
        max_library_papers=500,  # Decision #28
        docx_watermark=False,
        price_monthly=129_000,
        price_biannual=599_000,
    ),
    SubscriptionTier.MAGISTER: TierConfig(
        max_active_projects=10,
        allowed_stage_types=[
            "literature_review",
            "research_gap",
            "methodology_advisor",
            "hypothesis_variable",
            "proposisi_tema",
            "chapter_outline",
            "bab1_writer",
            "systematic_review",  # Magister only — Decision #19
            "sidang_preparation",
        ],
        max_papers_per_stage=50,
        max_reruns_per_stage=None,  # Unlimited
        can_use_systematic_review=True,
        chat_enabled=True,
        chat_messages_per_session=None,  # Unlimited
        chat_sessions_per_month=None,  # Unlimited
        chat_memory_across_sessions=True,
        chat_papers_per_session=20,
        library_enabled=True,
        library_retention_days=None,  # Permanent
        max_library_papers=None,  # Unlimited — Decision #28
        docx_watermark=False,
        price_monthly=249_000,
        price_biannual=1_199_000,
    ),
    SubscriptionTier.INSTITUTIONAL: TierConfig(
        max_active_projects=3,  # Per seat
        allowed_stage_types=[
            "literature_review",
            "research_gap",
            "methodology_advisor",
            "hypothesis_variable",
            "proposisi_tema",
            "chapter_outline",
            "bab1_writer",
            "sidang_preparation",  # P8 tersedia — Decision #20
            # systematic_review tidak tersedia untuk institutional (Magister only)
        ],
        max_papers_per_stage=30,
        max_reruns_per_stage=None,  # Unlimited
        can_use_systematic_review=False,
        chat_enabled=True,
        chat_messages_per_session=None,  # Unlimited
        chat_sessions_per_month=None,  # Unlimited
        chat_memory_across_sessions=True,
        chat_papers_per_session=10,
        library_enabled=True,
        library_retention_days=365,
        max_library_papers=500,  # Per seat — Decision #28
        docx_watermark=False,
        price_monthly=None,  # Custom institutional pricing
        price_biannual=None,
    ),
}


# ── LibraryQuotaInfo ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class LibraryQuotaInfo:
    """
    Informasi kuota library user — return type check_library_quota().

    Return type diubah dari bool ke dataclass (Decision #28) untuk mendukung
    partial import: user bisa import sebagian jika kuota mepet.

    current_count : jumlah paper is_visible=TRUE saat ini
    max_count     : batas tier (None = unlimited)
    remaining     : sisa slot (None = unlimited)
    can_add_more  : True jika masih bisa tambah minimal 1 paper
    """

    current_count: int
    max_count: Optional[int]  # None = unlimited
    remaining: Optional[int]  # None = unlimited
    can_add_more: bool


# ── Helper: tier dari string ──────────────────────────────────────────────


def get_tier_config(tier_str: str) -> TierConfig:
    """
    Return TierConfig dari string tier.
    Fallback ke FREE jika tier_str tidak dikenal (defensive).
    """
    try:
        tier = SubscriptionTier(tier_str)
    except ValueError:
        tier = SubscriptionTier.FREE
    return TIER_CONFIG[tier]

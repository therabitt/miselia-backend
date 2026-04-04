# ===========================================================================
# File    : app/models/database.py
# Desc    : SQLAlchemy ORM models — semua tabel Miselia dalam satu file.
#           PLACEHOLDER — implementasi penuh di STEP 4.
#           File ini dibuat di STEP 3 agar imports tidak crash.
# Layer   : Models / ORM
# Step    : STEP 3 (placeholder) → STEP 4 (implementasi penuh)
# Ref     : Blueprint §6.1–§6.15
# ===========================================================================

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class semua SQLAlchemy models."""
    pass


# === PLACEHOLDER — STEP 4 akan mendefinisikan semua model berikut: ===
# User, InstitutionalAccount, Subscription, PaymentTransaction,
# Project, StageRun, StageOutput, Paper, SearchResult, SearchSession,
# LibraryPaper, ChatSession, ChatMessage,
# InstitutionalSeat, CitationStyleMapping, PromptVersion,
# AnalyticsEvent, FeatureFlag, UserPreferences, ReferralCode

# ═════════════════════════════════════════════════════════════════════════════
# File    : app/models/enums.py
# Desc    : Semua Python enums untuk Miselia.
#           Digunakan oleh ORM models, Pydantic schemas, dan service layer.
#           Nilai string enum harus konsisten dengan CHECK constraints di DB.
# Layer   : Models / Enums
# Step    : STEP 3 — Backend Setup
# Ref     : Blueprint §2.2, §6.2–§6.4, §4.2
# ═════════════════════════════════════════════════════════════════════════════

from enum import Enum


class StageType(str, Enum):
    """Semua tipe pipeline P1–P8. Ref: Blueprint §6.4"""
    LITERATURE_REVIEW   = "literature_review"    # P1 — semua tier
    RESEARCH_GAP        = "research_gap"          # P2 — Sarjana+
    METHODOLOGY_ADVISOR = "methodology_advisor"   # P3 — Sarjana+ (Bulan 2)
    HYPOTHESIS_VARIABLE = "hypothesis_variable"   # P4 kuantitatif (Bulan 2)
    PROPOSISI_TEMA      = "proposisi_tema"         # P4 kualitatif (Bulan 2)
    CHAPTER_OUTLINE     = "chapter_outline"        # P5 — Sarjana+ (Bulan 2)
    BAB1_WRITER         = "bab1_writer"            # P6 — Sarjana+ (Bulan 4+)
    SYSTEMATIC_REVIEW   = "systematic_review"      # P7 — Magister only
    SIDANG_PREPARATION  = "sidang_preparation"     # P8 — semua tier berbayar


class SubscriptionTier(str, Enum):
    """Tier langganan. Ref: Blueprint §7.1"""
    FREE          = "free"
    SARJANA       = "sarjana"
    MAGISTER      = "magister"
    INSTITUTIONAL = "institutional"


class SubscriptionStatus(str, Enum):
    """Status siklus hidup subscription. Ref: Blueprint §6.2, Decision #1"""
    ACTIVE       = "active"
    GRACE_PERIOD = "grace_period"
    EXPIRED      = "expired"


class PlanType(str, Enum):
    """Tipe plan dalam subscription. Ref: Blueprint §6.2, Decision #1"""
    FREE          = "free"
    MONTHLY       = "monthly"
    BIANNUAL      = "biannual"
    INSTITUTIONAL = "institutional"


class BillingPeriod(str, Enum):
    """Periode billing untuk plan berbayar. Ref: Blueprint §2.2"""
    MONTHLY  = "monthly"
    BIANNUAL = "biannual"


class StageStatus(str, Enum):
    """Status eksekusi stage run. Ref: Blueprint §6.4"""
    QUEUED    = "queued"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"


class ReviewType(str, Enum):
    """Tipe review di level project. Decision #19"""
    NARRATIVE   = "narrative"    # P1 — default, semua tier
    SYSTEMATIC  = "systematic"   # P7 — Magister only


class PipelineMode(str, Enum):
    """Mode P4 — ditentukan otomatis dari P3 output. Decision #18"""
    KUANTITATIF = "kuantitatif"
    KUALITATIF  = "kualitatif"
    MIXED       = "mixed"


class LibraryPaperSource(str, Enum):
    """Sumber paper yang disimpan ke Library. Ref: Blueprint §4.2"""
    FIND_PAPERS = "find_papers"
    STAGE_RUN   = "stage_run"
    CSV_IMPORT  = "csv_import"   # Aktif Fase 5 — Decision #28
    BIB_IMPORT  = "bib_import"   # Aktif Tier A — Decision #28
    RIS_IMPORT  = "ris_import"   # Aktif Tier A — Decision #28


class ChatSessionStatus(str, Enum):
    """Status sesi chat. Ref: Blueprint §6.13"""
    ACTIVE        = "active"
    LIMIT_REACHED = "limit_reached"
    CLOSED        = "closed"


class ProjectStatus(str, Enum):
    """Status project. Ref: Blueprint §6.3, Decision #7"""
    ACTIVE   = "active"
    ARCHIVED = "archived"


class EducationLevel(str, Enum):
    """Jenjang pendidikan user. Ref: Blueprint §6.1"""
    S1 = "s1"
    S2 = "s2"
    S3 = "s3"


class ModeSource(str, Enum):
    """Sumber penentuan mode P4. Decision #18"""
    P3_AUTO        = "p3_auto"
    P3_AUTO_MIXED  = "p3_auto_mixed"
    USER_OVERRIDE  = "user_override"

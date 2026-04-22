# ═════════════════════════════════════════════════════════════════════════════
# File    : app/models/database.py
# Desc    : SQLAlchemy ORM models — semua tabel Miselia dalam satu file.
#           Urutan definisi mengikuti dependency FK:
#             InstitutionalAccount → User → Subscription → Project
#             → StageRun → StageOutput → PaymentTransaction
#             → InstitutionalSeat → CitationStyleMapping → PromptVersion
#             → AnalyticsEvent → FeatureFlag
#             (+ UserPreferences, ReferralCode, Paper, SearchSession,
#               LibraryPaper, ImportBatch, ChatSession, ChatMessage,
#               SearchResult — definisi lengkap untuk semua tabel Blueprint)
#
#           Semua model di STEP 4 Fase 0 sesuai migration 001–017.
#           Model pendukung (Paper, Library, Chat) turut didefinisikan
#           agar FK relationships dan imports tidak crash di fase berikutnya.
#
# Layer   : Models / ORM
# Deps    : sqlalchemy>=2.0, asyncpg
# Step    : STEP 4 — Backend: Database ORM Models
# Ref     : Blueprint §6.1–§6.15, §2.2
# ═════════════════════════════════════════════════════════════════════════════

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, relationship

# ── Base ──────────────────────────────────────────────────────────────────


class Base(DeclarativeBase):
    """Base class semua SQLAlchemy ORM models Miselia."""

    pass


# ── Helper: UUID kolom primary key ────────────────────────────────────────


def _uuid_pk() -> Column:
    """Shorthand: UUID primary key dengan default gen_random_uuid()."""
    return Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )


def _now_col() -> Column:
    """Shorthand: TIMESTAMPTZ kolom dengan default NOW()."""
    return Column(
        DateTime(timezone=True),
        default=func.now(),
        server_default=func.now(),
        nullable=False,
    )


def _updated_at_col() -> Column:
    """Shorthand: updated_at TIMESTAMPTZ dengan default dan onupdate NOW()."""
    return Column(
        DateTime(timezone=True),
        default=func.now(),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ═════════════════════════════════════════════════════════════════════════════
# MIGRATION 002: InstitutionalAccount
# Ref: Blueprint §6.9
# Definisi sebelum User karena User FK ke institutional_accounts via Subscription.
# ═════════════════════════════════════════════════════════════════════════════


class InstitutionalAccount(Base):
    """
    Akun institusional (kampus/prodi) yang membeli seat untuk mahasiswanya.
    Ref: Blueprint §6.9, Decision #5
    """

    __tablename__ = "institutional_accounts"

    id = _uuid_pk()
    name = Column(String(255), nullable=False)
    org_code = Column(String(50), unique=True, nullable=False)
    contact_email = Column(String(255), nullable=False)
    seats_purchased = Column(Integer, nullable=False)
    seats_used = Column(Integer, default=0, server_default="0", nullable=False)
    valid_from = Column(DateTime(timezone=True), nullable=False)
    valid_until = Column(DateTime(timezone=True), nullable=False)
    is_active = Column(Boolean, default=True, server_default="true", nullable=False)
    created_at = _now_col()
    updated_at = _updated_at_col()

    # Relationships
    subscriptions = relationship("Subscription", back_populates="institutional_account")
    seats = relationship("InstitutionalSeat", back_populates="institutional_account")

    def __repr__(self) -> str:
        return f"<InstitutionalAccount org_code={self.org_code!r}>"


# ═════════════════════════════════════════════════════════════════════════════
# MIGRATION 001: User
# Ref: Blueprint §6.1
# NOTE: Blueprint §6.1 tidak menyertakan is_admin. Kolom ini ditambahkan karena
# admin endpoints (Blueprint §2.2 admin.py) membutuhkan users.is_admin=True check.
# Tidak ada migration eksplisit di Appendix D → masuk ke 001_create_users_v6.py.
# ═════════════════════════════════════════════════════════════════════════════


class User(Base):
    """
    User Miselia — dibuat saat pertama kali POST /auth/verify berhasil.
    supabase_id = UUID dari Supabase Auth (JWT sub claim).
    Ref: Blueprint §6.1
    """

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "education_level IN ('s1', 's2', 's3')",
            name="ck_users_education_level",
        ),
    )

    id = _uuid_pk()
    supabase_id = Column(UUID(as_uuid=True), unique=True, nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    full_name = Column(String(255), nullable=True)
    university = Column(String(255), nullable=True)
    field_of_study = Column(String(255), nullable=True)
    education_level = Column(String(10), nullable=True)  # 's1'|'s2'|'s3'
    email_verified = Column(Boolean, default=False, server_default="false", nullable=False)
    # [FIX] onboarding_step: 0=belum mulai, 1–3=progress, 4=completed
    # Range 0–4 sesuai SKILL.md §11 dan Blueprint §11.15 (Screen 0–4, 5 screens total)
    # Ref: Blueprint §6.1, §11.15 (onboarding 5 screen)
    onboarding_step = Column(Integer, default=0, server_default="0", nullable=False)
    onboarding_completed_at = Column(DateTime(timezone=True), nullable=True)
    # is_admin: guard untuk admin endpoints — tidak ada di Blueprint §6.1 DDL eksplisit
    # tapi diperlukan oleh admin.py (Blueprint §2.2): "Guard: users.is_admin=True + IP whitelist"
    is_admin = Column(Boolean, default=False, server_default="false", nullable=False)
    created_at = _now_col()
    updated_at = _updated_at_col()

    # Relationships
    subscriptions = relationship("Subscription", back_populates="user")
    projects = relationship("Project", back_populates="user")
    stage_runs = relationship("StageRun", back_populates="user")
    payment_transactions = relationship("PaymentTransaction", back_populates="user")
    institutional_seats = relationship("InstitutionalSeat", back_populates="user")
    library_papers = relationship("LibraryPaper", back_populates="user")
    chat_sessions = relationship("ChatSession", back_populates="user")
    analytics_events = relationship("AnalyticsEvent", back_populates="user")
    preferences = relationship("UserPreferences", back_populates="user", uselist=False)
    referral_codes = relationship("ReferralCode", back_populates="user")
    import_batches = relationship("ImportBatch", back_populates="user")
    search_sessions: Mapped[list["SearchSession"]] = relationship(
        "SearchSession",
        back_populates="user",
        order_by="SearchSession.created_at desc",  # [FIX] SQL-style string, bukan Python expr
    )

    def __repr__(self) -> str:
        return f"<User email={self.email!r}>"


# ═════════════════════════════════════════════════════════════════════════════
# MIGRATION 003: Subscription
# Ref: Blueprint §6.2, Decision #1 (manual renewal), Decision #1 [NEW] (biannual)
# ═════════════════════════════════════════════════════════════════════════════


class Subscription(Base):
    """
    Subscription user — satu user aktif punya satu subscription.
    Lifecycle: active → grace_period → expired (Decision #1).
    Biannual: one-time charge, current_period_end = created_at + 180 hari.
    Ref: Blueprint §6.2
    """

    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint(
            "tier IN ('free', 'sarjana', 'magister', 'institutional')",
            name="ck_subscriptions_tier",
        ),
        CheckConstraint(
            "plan_type IN ('free', 'monthly', 'biannual', 'institutional')",
            name="ck_subscriptions_plan_type",
        ),
        CheckConstraint(
            "status IN ('active', 'grace_period', 'expired')",
            name="ck_subscriptions_status",
        ),
    )

    id = _uuid_pk()
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    tier = Column(String(20), nullable=False)
    plan_type = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False, default="active", server_default="active")
    current_period_start = Column(DateTime(timezone=True), nullable=True)
    current_period_end = Column(DateTime(timezone=True), nullable=True)
    institutional_account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("institutional_accounts.id"),
        nullable=True,
    )
    created_at = _now_col()
    updated_at = _updated_at_col()

    # Relationships
    user = relationship("User", back_populates="subscriptions")
    institutional_account = relationship("InstitutionalAccount", back_populates="subscriptions")
    payment_transactions = relationship("PaymentTransaction", back_populates="subscription")

    def __repr__(self) -> str:
        return f"<Subscription user={self.user_id} tier={self.tier!r} status={self.status!r}>"


# ═════════════════════════════════════════════════════════════════════════════
# MIGRATION 004: PaymentTransaction
# Ref: Blueprint §6.8, Decision #1 (Midtrans Snap)
# ═════════════════════════════════════════════════════════════════════════════


class PaymentTransaction(Base):
    """
    Rekaman transaksi Midtrans. Sumber kebenaran audit trail pembayaran.
    Ref: Blueprint §6.8, §6.15 [I3 FIX] — tidak ada tabel subscription_events terpisah.
    """

    __tablename__ = "payment_transactions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'settlement', 'expire', 'cancel', 'deny', 'refund')",
            name="ck_payment_transactions_status",
        ),
    )

    id = _uuid_pk()
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    subscription_id = Column(UUID(as_uuid=True), ForeignKey("subscriptions.id"), nullable=True)
    order_id = Column(String(255), unique=True, nullable=False)
    amount = Column(Integer, nullable=False)  # dalam IDR (Rupiah)
    currency = Column(String(10), default="IDR", server_default="IDR", nullable=False)
    status = Column(String(20), default="pending", server_default="pending", nullable=False)
    plan_type = Column(String(20), nullable=True)  # monthly|biannual|institutional
    tier = Column(String(20), nullable=True)  # sarjana|magister|institutional
    midtrans_response = Column(JSONB, nullable=True)  # raw Midtrans webhook payload
    snap_token = Column(Text, nullable=True)
    created_at = _now_col()
    updated_at = _updated_at_col()

    # Relationships
    user = relationship("User", back_populates="payment_transactions")
    subscription = relationship("Subscription", back_populates="payment_transactions")

    def __repr__(self) -> str:
        return f"<PaymentTransaction order={self.order_id!r} status={self.status!r}>"


# ═════════════════════════════════════════════════════════════════════════════
# MIGRATION 005: Project
# Ref: Blueprint §6.3, Decision #3 (project-based), Decision #19 (review_type)
# ═════════════════════════════════════════════════════════════════════════════


class Project(Base):
    """
    Unit bisnis sentral — satu topik riset per project.
    review_type final setelah dibuat — menentukan P1 vs P7 entry point.
    Ref: Blueprint §6.3, Decision #3, Decision #19
    """

    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint(
            "review_type IN ('narrative', 'systematic')",
            name="ck_projects_review_type",
        ),
        CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_projects_status",
        ),
        Index("idx_projects_user_id", "user_id"),
        Index("idx_projects_user_status", "user_id", "status"),
    )

    id = _uuid_pk()
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    title = Column(String(500), nullable=False)
    field_of_study = Column(String(255), nullable=True)
    education_level = Column(String(10), nullable=True)
    citation_style = Column(String(20), nullable=True)
    # review_type: 'narrative' (default, P1 entry) atau 'systematic' (Magister only, P7 entry)
    # Nilai ini FINAL setelah project dibuat — Decision #19
    review_type = Column(
        String(20), default="narrative", server_default="narrative", nullable=False
    )
    # status: 'active' | 'archived' — archive terjadi saat downgrade (Decision #7)
    status = Column(String(20), default="active", server_default="active", nullable=False)
    created_at = _now_col()
    updated_at = _updated_at_col()

    # Relationships
    user = relationship("User", back_populates="projects")
    stage_runs = relationship("StageRun", back_populates="project")

    def __repr__(self) -> str:
        return f"<Project title={self.title!r} review_type={self.review_type!r}>"


# ═════════════════════════════════════════════════════════════════════════════
# MIGRATION 006: StageRun
# Ref: Blueprint §6.4, Decision #8 (rerun limit), Decision #14 (source_stage_run_id),
#      Decision #18 (input_params P4 mode), Decision #24 (user_overrides in input_params)
# ═════════════════════════════════════════════════════════════════════════════


class StageRun(Base):
    """
    Satu eksekusi pipeline (P1–P8). Child dari Project.
    source_stage_run_id: snapshot dependency — run mana yang jadi basis (Decision #14).
    input_params: JSONB — {methodology_mode, mode_source, user_overrides, ...} (Decision #18, #24).
    Ref: Blueprint §6.4
    """

    __tablename__ = "stage_runs"
    __table_args__ = (
        CheckConstraint(
            """stage_type IN (
                'literature_review',
                'research_gap',
                'methodology_advisor',
                'hypothesis_variable',
                'proposisi_tema',
                'chapter_outline',
                'bab1_writer',
                'systematic_review',
                'sidang_preparation'
            )""",
            name="ck_stage_runs_stage_type",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="ck_stage_runs_status",
        ),
        # Index untuk re-run count query Free tier — Decision #8
        # Query: SELECT COUNT(*) FROM stage_runs WHERE user_id=? AND project_id=?
        #        AND stage_type=? AND status='completed'
        Index(
            "idx_stage_runs_rerun_check",
            "user_id",
            "project_id",
            "stage_type",
            "status",
            postgresql_where="status = 'completed'",
        ),
        Index("idx_stage_runs_project_status", "project_id", "stage_type", "status"),
        Index(
            "idx_stage_runs_celery_task",
            "celery_task_id",
            postgresql_where="celery_task_id IS NOT NULL",
        ),
    )

    id = _uuid_pk()
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    stage_type = Column(String(50), nullable=False)
    status = Column(String(20), default="queued", server_default="queued", nullable=False)
    topic = Column(Text, nullable=False)
    filters = Column(JSONB, nullable=True)
    # constraints: untuk P3 {sample_size, time_remaining, selected_gap_id}
    #              untuk P7 {pico_framework}
    constraints = Column(JSONB, nullable=True)
    # input_params: field generik per pipeline
    #   P4: {methodology_mode, mode_source}
    #   P2–P8: {user_overrides: {gap_description, research_question, ...}} — Decision #24
    input_params = Column(JSONB, nullable=True)
    citation_style = Column(String(20), nullable=True)
    # source_stage_run_id: FK ke diri sendiri — run mana yang jadi basis pipeline ini
    # Decision #14, Decision #10
    source_stage_run_id = Column(UUID(as_uuid=True), ForeignKey("stage_runs.id"), nullable=True)
    progress_step = Column(Integer, default=0, server_default="0", nullable=False)
    progress_detail = Column(Text, nullable=True)
    idempotency_key = Column(String(255), unique=True, nullable=True)
    celery_task_id = Column(String(255), nullable=True)
    created_at = _now_col()
    completed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = _updated_at_col()

    # Relationships
    project = relationship("Project", back_populates="stage_runs")
    user = relationship("User", back_populates="stage_runs")
    output = relationship("StageOutput", back_populates="stage_run", uselist=False)
    search_results: Mapped[list["SearchResult"]] = relationship(
        "SearchResult", back_populates="stage_run"
    )
    # Self-referential: stage run ini berbasis run mana
    source_stage_run = relationship(
        "StageRun",
        remote_side="StageRun.id",
        foreign_keys=[source_stage_run_id],
    )

    def __repr__(self) -> str:
        return f"<StageRun type={self.stage_type!r} status={self.status!r}>"


# ═════════════════════════════════════════════════════════════════════════════
# MIGRATION 009: StageOutput
# Ref: Blueprint §6.7, [M1 FIX] diagram_path vs diagram_data distinction
# ═════════════════════════════════════════════════════════════════════════════


class StageOutput(Base):
    """
    Output dari satu stage run — one-to-one dengan StageRun.
    docx_path: NULL untuk P8 (PDF output)
    pdf_path: untuk P8
    diagram_path: PNG statis di R2 untuk export user (P4) — [M1 FIX] BERBEDA dari diagram_data
    prisma_path: SVG PRISMA flowchart untuk P7
    diagram_data: JSONB live {nodes, edges} untuk React Flow — ditambahkan via Migration 027 (Fase 6B)
    metadata: JSONB untuk monitoring data — termasuk provider_used (Decision #23)
    Ref: Blueprint §6.7
    """

    __tablename__ = "stage_outputs"

    id = _uuid_pk()
    stage_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("stage_runs.id"),
        unique=True,  # One-to-one dengan StageRun
        nullable=False,
    )
    output_data = Column(JSONB, nullable=False)  # raw AI output JSON
    # Path file di Cloudflare R2
    # Format: outputs/{user_id}/{project_id}/{stage_run_id}/{stage_type}_{YYYY-MM-DD}.{ext}
    # Ref: Blueprint Appendix A R2 naming convention
    docx_path = Column(Text, nullable=True)  # NULL untuk P8
    pdf_path = Column(Text, nullable=True)  # Untuk P8 output
    diagram_path = Column(Text, nullable=True)  # PNG statis P4 (export user)
    prisma_path = Column(Text, nullable=True)  # SVG PRISMA P7
    # diagram_data: AKAN ditambahkan via Migration 027 (Fase 6B) — Decision #26
    # ALTER TABLE stage_outputs ADD COLUMN diagram_data JSONB;
    # Tidak didefinisikan di sini — akan di-add saat Fase 6B
    # [ADD] metadata: monitoring data per run — provider_used, token_counts, latency_ms, etc.
    # Decision #23: provider_used disimpan di sini (bukan di output_data) untuk query-friendly monitoring
    # Contoh: {"provider_used": "anthropic", "model": "claude-haiku-4-5", "latency_ms": 1240}
    monitoring_metadata = Column(JSONB, nullable=True)
    prompt_version_id = Column(UUID(as_uuid=True), ForeignKey("prompt_versions.id"), nullable=True)
    quality_warning = Column(Boolean, default=False, server_default="false", nullable=False)
    quality_warning_reason = Column(Text, nullable=True)
    created_at = _now_col()
    updated_at = _updated_at_col()

    # Relationships
    stage_run = relationship("StageRun", back_populates="output")
    prompt_version = relationship("PromptVersion", back_populates="stage_outputs")

    def __repr__(self) -> str:
        return f"<StageOutput stage_run={self.stage_run_id}>"


# ═════════════════════════════════════════════════════════════════════════════
# MIGRATION 010: InstitutionalSeat
# Ref: Blueprint §6.10
# ═════════════════════════════════════════════════════════════════════════════


class InstitutionalSeat(Base):
    """
    Mapping user ↔ institutional_account — satu row per seat yang ter-assign.
    Ref: Blueprint §6.10, Decision #5
    """

    __tablename__ = "institutional_seats"
    __table_args__ = (
        UniqueConstraint(
            "institutional_account_id",
            "user_id",
            name="uq_institutional_seats_account_user",
        ),
    )

    id = _uuid_pk()
    institutional_account_id = Column(
        UUID(as_uuid=True),
        ForeignKey("institutional_accounts.id"),
        nullable=False,
        index=True,
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    assigned_at = Column(
        DateTime(timezone=True),
        default=func.now(),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    institutional_account = relationship("InstitutionalAccount", back_populates="seats")
    user = relationship("User", back_populates="institutional_seats")

    def __repr__(self) -> str:
        return f"<InstitutionalSeat account={self.institutional_account_id} user={self.user_id}>"


# ═════════════════════════════════════════════════════════════════════════════
# MIGRATION 012: CitationStyleMapping
# Ref: Blueprint §6.15, Decision #9, Appendix F (31 program studi)
# ═════════════════════════════════════════════════════════════════════════════


class CitationStyleMapping(Base):
    """
    Mapping program studi → citation style yang direkomendasikan.
    Seed data: 31 program studi — Blueprint Appendix F.
    Digunakan oleh CitationStyleResolver (Decision #9 priority chain step 4).
    Ref: Blueprint §6.15
    """

    __tablename__ = "citation_style_mappings"
    __table_args__ = (
        CheckConstraint(
            "confidence_level IN ('high', 'medium', 'low')",
            name="ck_citation_style_mappings_confidence",
        ),
    )

    id = _uuid_pk()
    field_of_study = Column(String(255), unique=True, nullable=False)
    recommended_style = Column(String(20), nullable=False)
    confidence_level = Column(String(10), nullable=True)  # 'high'|'medium'|'low'
    notes = Column(Text, nullable=True)
    created_at = _now_col()

    def __repr__(self) -> str:
        return (
            f"<CitationStyleMapping field={self.field_of_study!r} style={self.recommended_style!r}>"
        )


# ═════════════════════════════════════════════════════════════════════════════
# MIGRATION 015: PromptVersion
# Ref: Blueprint §6.15
# Partial unique index: hanya satu is_active=True per (stage_type, prompt_name)
# — dibuat via migration, bukan di sini (SQLAlchemy Index tidak support partial
#   unique index dengan WHERE clause secara deklaratif — harus raw SQL di migration)
# ═════════════════════════════════════════════════════════════════════════════


class PromptVersion(Base):
    """
    Versi prompt per stage dan nama prompt.
    Seed data: 22 prompt entries P1–P8 — Blueprint Appendix C.
    Partial unique index (satu aktif per stage_type+prompt_name) dibuat via migration raw SQL.
    Ref: Blueprint §6.15
    """

    __tablename__ = "prompt_versions"

    id = _uuid_pk()
    stage_type = Column(String(50), nullable=False, index=True)
    prompt_name = Column(String(100), nullable=False)
    version = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    # is_active: hanya satu True per (stage_type, prompt_name)
    # Partial unique index dibuat di migration 015 via raw SQL:
    # CREATE UNIQUE INDEX idx_prompt_versions_one_active
    #     ON prompt_versions(stage_type, prompt_name) WHERE is_active = TRUE;
    is_active = Column(Boolean, default=False, server_default="false", nullable=False)
    created_at = _now_col()

    # Relationships
    stage_outputs = relationship("StageOutput", back_populates="prompt_version")

    def __repr__(self) -> str:
        return (
            f"<PromptVersion stage={self.stage_type!r} name={self.prompt_name!r} v={self.version}>"
        )


# ═════════════════════════════════════════════════════════════════════════════
# MIGRATION 016: AnalyticsEvent (partitioned)
# Ref: Blueprint §6.15, §14.1
# PENTING: Tabel ini PARTITION BY RANGE (created_at).
# SQLAlchemy tidak mendukung deklarasi PARTITION BY secara native.
# ORM model ini hanya digunakan untuk INSERT — DDL partisi dibuat via migration raw SQL.
# ═════════════════════════════════════════════════════════════════════════════


class AnalyticsEvent(Base):
    """
    Event analytics — partitioned by RANGE(created_at) bulanan.
    PERINGATAN: DDL partisi HARUS dibuat via migration raw SQL (tidak via ORM).
    Model ini hanya untuk insert/query — bukan untuk create_all().
    Partisi awal: 2026-03, 2026-04, 2026-05 — dibuat di migration 016.
    Ref: Blueprint §6.15, §14.1
    """

    __tablename__ = "analytics_events"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=func.gen_random_uuid(),
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    session_id = Column(Text, nullable=True)  # Anonymous session ID (Blueprint §14.0)
    event_name = Column(String(100), nullable=False)
    properties = Column(JSONB, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=func.now(),
        server_default=func.now(),
        nullable=False,
        # created_at adalah partition key — HARUS ada di primary key untuk partitioned table
        primary_key=True,
    )

    # Relationships
    user = relationship("User", back_populates="analytics_events")

    def __repr__(self) -> str:
        return f"<AnalyticsEvent event={self.event_name!r}>"


# ═════════════════════════════════════════════════════════════════════════════
# MIGRATION 017: FeatureFlag
# Ref: Blueprint §6.15, Appendix C (19 flags)
# ═════════════════════════════════════════════════════════════════════════════


class FeatureFlag(Base):
    """
    Feature flags — dikontrol via admin dashboard atau seed script.
    Seed data: 19 flags — Blueprint Appendix C.
    Ref: Blueprint §6.15, Appendix C
    """

    __tablename__ = "feature_flags"

    id = _uuid_pk()
    name = Column(String(100), unique=True, nullable=False)
    is_enabled = Column(Boolean, default=False, server_default="false", nullable=False)
    description = Column(Text, nullable=True)
    created_at = _now_col()
    updated_at = _updated_at_col()

    def __repr__(self) -> str:
        return f"<FeatureFlag name={self.name!r} enabled={self.is_enabled}>"


# ═════════════════════════════════════════════════════════════════════════════
# TABEL PENDUKUNG — didefinisikan lengkap agar FK tidak crash di fase berikutnya
# Ref: Blueprint §6.11–§6.15
# ═════════════════════════════════════════════════════════════════════════════

# ── Paper (Migration 007) ─────────────────────────────────────────────────


class Paper(Base):
    """
    Paper akademik dari Semantic Scholar / OpenAlex / import user.
    is_manually_imported: True jika dari csv/bib/ris import (Decision #28).
    quality_signal: JBI/CASP scores untuk P7 SLR (Magister only).
    Ref: Blueprint §6.5 Fase 1 Step 1
    """

    __tablename__ = "papers"

    # [FIX] Ganti raw Column+text() ke _uuid_pk() — konsisten dengan semua model lain
    # dan pastikan Python-side default=uuid.uuid4 ada (sebelumnya None sebelum DB flush)
    id = _uuid_pk()
    # External IDs — unique per source, nullable (tidak semua paper ada di semua source)
    semantic_scholar_id = Column(String(255), unique=True, nullable=True)
    openalex_id = Column(String(255), unique=True, nullable=True)
    # [FIX] garuda_id dipertahankan untuk forward-compatibility — Decision #27: defer SINTA/Garuda
    # integration. Kolom ini TIDAK aktif digunakan sampai Decision #27 di-revisit.
    garuda_id = Column(String(255), unique=True, nullable=True)
    # Core metadata
    title = Column(Text, nullable=False)
    title_hash = Column(String(64), nullable=True, index=True)
    authors = Column(JSONB, nullable=True)
    year = Column(Integer, nullable=True)
    venue = Column(Text, nullable=True)
    citation_count = Column(Integer, default=0, server_default="0", nullable=False)
    abstract = Column(Text, nullable=True)
    abstract_language = Column(String(10), nullable=True)
    full_text = Column(Text, nullable=True)
    sources = Column(JSONB, nullable=True)
    # Access metadata
    doi = Column(Text, nullable=True)
    pdf_url = Column(Text, nullable=True)
    is_open_access = Column(Boolean, default=False, server_default="false", nullable=False)
    # Pipeline-specific
    quality_signal = Column(JSONB, nullable=True)  # P7: JBI/CASP scores
    # is_manually_imported: TRUE = dari import file user — Decision #28
    is_manually_imported = Column(
        Boolean,
        default=False,  # [FIX] tambah Python-side default
        server_default="false",
        nullable=False,
        comment="TRUE = dari import file user (Decision #28)",
    )
    # [FIX] Ganti raw text("NOW()") ke helpers — Paper.updated_at sebelumnya
    # tidak punya onupdate=func.now() sehingga ORM update tidak auto-update kolom ini
    created_at = _now_col()
    updated_at = _updated_at_col()
    # Relationships
    search_results: Mapped[list["SearchResult"]] = relationship(
        "SearchResult", back_populates="paper"
    )
    library_papers = relationship("LibraryPaper", back_populates="paper")

    def __repr__(self) -> str:
        title_preview = (
            (self.title[:40] + "...")
            if self.title and len(self.title) > 40
            else (self.title or "N/A")
        )
        return f"<Paper title={title_preview!r}>"


# ── SearchResult (Migration 008) ─────────────────────────────────────────


class SearchResult(Base):
    """
    Join table antara stage_runs dan papers.
    Melayani DUA use case:
      (1) Pipeline run  → stage_run_id terisi, paper dari P1/P7
      (2) Push-to-project dari Library → stage_run_id = NULL (GAP F1-3)
    UNIQUE via partial index di migration (WHERE stage_run_id IS NOT NULL).
    Ref: Blueprint §6.6, GAP F1-3 resolution, Fase 1 STEP 1
    """

    __tablename__ = "search_results"
    __table_args__ = (
        # UNIQUE (stage_run_id, paper_id) hanya saat stage_run_id IS NOT NULL —
        # dihandle via partial index di migration 008, bukan di ORM level.
        # Index idx_search_results_relevance juga di migration 008.
        Index(
            "idx_search_results_stage_run_id",
            "stage_run_id",
            postgresql_where="stage_run_id IS NOT NULL",
        ),
        Index("idx_search_results_paper_id", "paper_id"),
    )

    # [FIX] Ganti raw Column+text() ke _uuid_pk() — Python-side default=uuid.uuid4 kini ada
    id = _uuid_pk()
    # NULLABLE — NULL untuk library push_to_project (tidak ada pipeline run).
    # Ref: GAP F1-3
    stage_run_id = Column(
        UUID(as_uuid=True),
        ForeignKey("stage_runs.id", ondelete="CASCADE"),
        nullable=True,
    )
    paper_id = Column(
        UUID(as_uuid=True),
        ForeignKey("papers.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Scoring — nullable karena library push tidak melalui scoring pipeline
    relevance_score = Column(Float, nullable=True)
    rank_position = Column(Integer, nullable=True)
    included_in_output = Column(Boolean, default=False, server_default="false", nullable=False)
    # [FIX] Ganti raw text("NOW()") ke _now_col()
    # append-only — no updated_at (SearchResult tidak pernah di-update setelah insert)
    created_at = _now_col()

    # Relationships
    stage_run = relationship("StageRun", back_populates="search_results")
    paper = relationship("Paper", back_populates="search_results")

    def __repr__(self) -> str:
        return f"<SearchResult run={self.stage_run_id} score={self.relevance_score}>"


# ── SearchSession (Migration 018) ────────────────────────────────────────


class SearchSession(Base):
    """
    Rekaman setiap pencarian paper oleh authenticated user.
    Guest request TIDAK disimpan ke DB (Blueprint §3.4).
    Digunakan oleh RecentSearches component di frontend dashboard.
    paper_ids: JSONB list of UUID string (bukan FK array) — snapshot hasil
    pencarian tetap utuh meski paper di-dedup/merge setelahnya.
    Ref: Blueprint §6.11, §3.4, Fase 1 STEP 1
    """

    __tablename__ = "search_sessions"
    __table_args__ = (
        Index("idx_search_sessions_user_id", "user_id"),
        # Composite index untuk query "ambil N terbaru per user" —
        # GET /papers/search-sessions selalu pakai WHERE user_id = ? ORDER BY created_at DESC
        Index("idx_search_sessions_user_created", "user_id", "created_at"),
    )

    # [FIX] Ganti raw Column+text() ke _uuid_pk() — Python-side default=uuid.uuid4 kini ada
    id = _uuid_pk()
    # NOT NULL — guest sessions tidak disimpan
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    query = Column(Text, nullable=False)
    # filters: snapshot FindPapersFilters — {year_from, year_to, document_types, ...}
    filters = Column(JSONB, nullable=True)
    # paper_ids: JSONB list UUID string — sengaja tidak FK, paper bisa dihapus
    # tanpa cascade ke session history
    paper_ids = Column(JSONB, nullable=True)
    result_count = Column(Integer, default=0, server_default="0", nullable=False)
    # [FIX] Ganti raw text("NOW()") ke _now_col()
    # append-only — no updated_at (SearchSession tidak pernah di-update setelah insert)
    created_at = _now_col()
    # Relationships
    user = relationship("User", back_populates="search_sessions")

    def __repr__(self) -> str:
        return f"<SearchSession user={self.user_id} query={self.query[:30]!r}>"


# ── ImportBatch (Migration — Fase 5) ─────────────────────────────────────


class ImportBatch(Base):
    """
    Audit record satu batch import file (CSV/BibTeX/RIS).
    Dibuat saat POST /library/papers/import/confirm berhasil.
    Decision #28, aktif Fase 5 (csv) dan Tier A (bib/ris).
    Ref: Blueprint §6.12a
    """

    __tablename__ = "import_batches"
    __table_args__ = (
        CheckConstraint(
            "file_format IN ('csv', 'bib', 'ris')",
            name="ck_import_batches_file_format",
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'done', 'failed')",
            name="ck_import_batches_status",
        ),
        Index("idx_import_batches_user", "user_id", "created_at"),
        Index(
            "idx_import_batches_status",
            "status",
            postgresql_where="status IN ('pending', 'processing')",
        ),
    )

    id = _uuid_pk()
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    file_format = Column(String(20), nullable=False)  # 'csv'|'bib'|'ris'
    original_filename = Column(Text, nullable=False)
    total_parsed = Column(Integer, default=0, server_default="0", nullable=False)
    imported_count = Column(Integer, default=0, server_default="0", nullable=False)
    skipped_duplicate = Column(Integer, default=0, server_default="0", nullable=False)
    skipped_quota = Column(Integer, default=0, server_default="0", nullable=False)
    incomplete_count = Column(Integer, default=0, server_default="0", nullable=False)
    status = Column(String(20), default="pending", server_default="pending", nullable=False)
    error_message = Column(Text, nullable=True)
    row_results = Column(JSONB, nullable=True)
    column_mapping = Column(JSONB, nullable=True)  # hanya untuk CSV
    created_at = _now_col()
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    user = relationship("User", back_populates="import_batches")
    library_papers = relationship("LibraryPaper", back_populates="import_batch")

    def __repr__(self) -> str:
        return f"<ImportBatch format={self.file_format!r} status={self.status!r}>"


# ── LibraryPaper (Migration 019) ─────────────────────────────────────────


class LibraryPaper(Base):
    """
    Paper yang disimpan user ke Library personal.
    Single source of truth — tidak ada tabel saved_papers (Blueprint §6.15 [C3]).
    Soft delete: is_visible=False saat expires_at tercapai (Decision #2).
    tags: TEXT[] dengan GIN index — dibuat via migration raw SQL.
    Ref: Blueprint §6.12, Decision #2, Decision #28
    """

    __tablename__ = "library_papers"
    __table_args__ = (
        CheckConstraint(
            "source IN ('find_papers', 'stage_run', 'csv_import', 'bib_import', 'ris_import')",
            name="ck_library_papers_source",
        ),
        UniqueConstraint("user_id", "paper_id", name="uq_library_papers_user_paper"),
        # Indexes dibuat via migration raw SQL untuk partial index support:
        # idx_library_papers_visible ON library_papers(user_id, is_visible)
        # idx_library_papers_expires_at ON library_papers(expires_at) WHERE expires_at IS NOT NULL AND is_visible = TRUE
        # idx_library_papers_import_batch ON library_papers(import_batch_id) WHERE import_batch_id IS NOT NULL
        # idx_library_papers_tags USING GIN(tags) WHERE tags IS NOT NULL
    )

    id = _uuid_pk()
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    paper_id = Column(UUID(as_uuid=True), ForeignKey("papers.id"), nullable=False)
    source = Column(String(30), nullable=False)
    source_stage_run_id = Column(UUID(as_uuid=True), ForeignKey("stage_runs.id"), nullable=True)
    import_batch_id = Column(UUID(as_uuid=True), ForeignKey("import_batches.id"), nullable=True)
    notes = Column(Text, nullable=True)  # max 2000 char — enforced di service
    # tags: TEXT[] — GIN index via migration raw SQL. Ref: Blueprint §6.12 [FIX]
    tags = Column(ARRAY(Text), nullable=True)
    is_incomplete = Column(Boolean, default=False, server_default="false", nullable=False)
    # Soft delete fields — Decision #2, Decision #7
    is_visible = Column(Boolean, default=True, server_default="true", nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    expired_at = Column(DateTime(timezone=True), nullable=True)
    added_at = Column(
        DateTime(timezone=True),
        default=func.now(),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    user = relationship("User", back_populates="library_papers")
    paper = relationship("Paper", back_populates="library_papers")
    import_batch = relationship("ImportBatch", back_populates="library_papers")

    def __repr__(self) -> str:
        return f"<LibraryPaper user={self.user_id} paper={self.paper_id}>"


# ── ChatSession (Migration 020) ───────────────────────────────────────────


class ChatSession(Base):
    """
    Sesi Chat with Papers — berisi paper context dan pesan.
    Limit: Free=5 pesan/sesi, 3 sesi/bulan; Sarjana=30 pesan unlimited sesi (Decision #11).
    Ref: Blueprint §6.13, Decision #11
    """

    __tablename__ = "chat_sessions"
    __table_args__ = (
        CheckConstraint(
            "source IN ('find_papers', 'library', 'stage_run')",
            name="ck_chat_sessions_source",
        ),
        CheckConstraint(
            "status IN ('active', 'limit_reached', 'closed')",
            name="ck_chat_sessions_status",
        ),
        Index("idx_chat_sessions_user_id", "user_id"),
    )

    id = _uuid_pk()
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    title = Column(Text, nullable=True)
    paper_ids = Column(JSONB, nullable=False)  # list UUID paper dalam konteks
    source = Column(String(30), nullable=True)  # 'find_papers'|'library'|'stage_run'
    source_ref_id = Column(Text, nullable=True)  # ID sumber (session/stage_run/etc)
    status = Column(String(20), default="active", server_default="active", nullable=False)
    message_count = Column(Integer, default=0, server_default="0", nullable=False)
    created_at = _now_col()
    last_message_at = Column(
        DateTime(timezone=True), default=func.now(), server_default=func.now(), nullable=False
    )
    updated_at = _updated_at_col()

    # Relationships
    user = relationship("User", back_populates="chat_sessions")
    messages = relationship("ChatMessage", back_populates="session")

    def __repr__(self) -> str:
        return f"<ChatSession user={self.user_id} status={self.status!r}>"


# ── ChatMessage (Migration 021) ───────────────────────────────────────────


class ChatMessage(Base):
    """
    Pesan individual dalam satu chat session.
    Ref: Blueprint §6.14
    """

    __tablename__ = "chat_messages"
    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant')",
            name="ck_chat_messages_role",
        ),
        Index("idx_chat_messages_session_id", "chat_session_id"),
    )

    id = _uuid_pk()
    chat_session_id = Column(UUID(as_uuid=True), ForeignKey("chat_sessions.id"), nullable=False)
    role = Column(String(20), nullable=False)  # 'user'|'assistant'
    content = Column(Text, nullable=False)
    created_at = _now_col()

    # Relationships
    session = relationship("ChatSession", back_populates="messages")

    def __repr__(self) -> str:
        return f"<ChatMessage role={self.role!r} len={len(self.content)}>"


# ── UserPreferences (Migration 011) ──────────────────────────────────────


class UserPreferences(Base):
    """
    Preferensi user — citation style, bahasa UI, notifikasi email.
    One-to-one dengan User.
    Ref: Blueprint §6.15
    """

    __tablename__ = "user_preferences"

    id = _uuid_pk()
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False)
    preferred_citation_style = Column(String(20), nullable=True)
    ui_language = Column(String(10), default="id", server_default="id", nullable=False)
    email_notifications = Column(Boolean, default=True, server_default="true", nullable=False)
    created_at = _now_col()
    updated_at = _updated_at_col()

    # Relationships
    user = relationship("User", back_populates="preferences")

    def __repr__(self) -> str:
        return f"<UserPreferences user={self.user_id}>"


# ── ReferralCode (Migration 014) ─────────────────────────────────────────


class ReferralCode(Base):
    """
    Kode referral user — format MSL-XXXXXX.
    Feature flag: referral_system_enabled (aktif Fase 6A).
    Ref: Blueprint §6.15, §13.3
    """

    __tablename__ = "referral_codes"

    id = _uuid_pk()
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    code = Column(String(20), unique=True, nullable=False)
    uses_count = Column(Integer, default=0, server_default="0", nullable=False)
    max_uses = Column(Integer, default=10, server_default="10", nullable=False)
    reward_type = Column(String(30), nullable=True)
    is_active = Column(Boolean, default=True, server_default="true", nullable=False)
    created_at = _now_col()
    updated_at = _updated_at_col()

    # Relationships
    user = relationship("User", back_populates="referral_codes")

    def __repr__(self) -> str:
        return f"<ReferralCode code={self.code!r} uses={self.uses_count}>"

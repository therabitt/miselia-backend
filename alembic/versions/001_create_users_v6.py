# ═════════════════════════════════════════════════════════════════════════════
# File    : alembic/versions/001_create_users_v6.py
# Desc    : Buat tabel users — pondasi auth Miselia.
#           Tambahan is_admin (tidak eksplisit di Blueprint §6.1 DDL tapi
#           diperlukan oleh admin endpoint guard — Blueprint §2.2 admin.py).
# Revision: 001
# Fase    : Fase 0
# Ref     : Blueprint §6.1, Appendix D
# ═════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        # PK
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        # Auth
        sa.Column("supabase_id", postgresql.UUID(as_uuid=True), unique=True, nullable=False),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        # Profile
        sa.Column("full_name", sa.String(255), nullable=True),
        sa.Column("university", sa.String(255), nullable=True),
        sa.Column("field_of_study", sa.String(255), nullable=True),
        sa.Column("education_level", sa.String(10), nullable=True),
        sa.Column("email_verified", sa.Boolean(), server_default="false", nullable=False),
        # Onboarding state — Blueprint §6.1
        # 0=belum mulai, 1–4=progress screen, 5=completed
        sa.Column("onboarding_step", sa.Integer(), server_default="0", nullable=False),
        sa.Column("onboarding_completed_at", sa.DateTime(timezone=True), nullable=True),
        # Admin flag — untuk guard admin endpoints (Blueprint §2.2 admin.py)
        sa.Column("is_admin", sa.Boolean(), server_default="false", nullable=False),
        # Timestamps
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        # CHECK constraints
        sa.CheckConstraint(
            "education_level IN ('s1', 's2', 's3')",
            name="ck_users_education_level",
        ),
    )

    # Indexes — Blueprint Appendix E
    op.create_index("idx_users_supabase_id", "users", ["supabase_id"])
    op.create_index("idx_users_email", "users", ["email"])


def downgrade() -> None:
    op.drop_index("idx_users_email", table_name="users")
    op.drop_index("idx_users_supabase_id", table_name="users")
    op.drop_table("users")

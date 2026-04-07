# ═════════════════════════════════════════════════════════════════════════════
# File    : alembic/versions/003_create_subscriptions.py
# Desc    : Buat tabel subscriptions — siklus hidup langganan user.
#           Lifecycle: active → grace_period → expired (Decision #1).
#           plan_type 'biannual': one-time Midtrans, period_end +180 hari.
# Revision: 003
# Fase    : Fase 0
# Ref     : Blueprint §6.2, Decision #1 [NEW], Appendix D
# ═════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "subscriptions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", name="fk_subscriptions_user_id"),
            nullable=False,
        ),
        # tier: kategori user — menentukan fitur yang tersedia (Blueprint §7.1)
        sa.Column("tier", sa.String(20), nullable=False),
        # plan_type: tipe pembayaran — 'biannual' = Rp 599K one-time, +180 hari
        sa.Column("plan_type", sa.String(20), nullable=False),
        # status: lifecycle subscription (Decision #1)
        sa.Column(
            "status",
            sa.String(20),
            server_default="active",
            nullable=False,
        ),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "institutional_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "institutional_accounts.id",
                name="fk_subscriptions_institutional_account_id",
            ),
            nullable=True,
        ),
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
            "tier IN ('free', 'sarjana', 'magister', 'institutional')",
            name="ck_subscriptions_tier",
        ),
        sa.CheckConstraint(
            "plan_type IN ('free', 'monthly', 'biannual', 'institutional')",
            name="ck_subscriptions_plan_type",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'grace_period', 'expired')",
            name="ck_subscriptions_status",
        ),
    )

    # Indexes — Blueprint Appendix E
    op.create_index("idx_subscriptions_user_id", "subscriptions", ["user_id"])
    op.create_index("idx_subscriptions_status", "subscriptions", ["status"])
    op.create_index("idx_subscriptions_period_end", "subscriptions", ["current_period_end"])


def downgrade() -> None:
    op.drop_index("idx_subscriptions_period_end", table_name="subscriptions")
    op.drop_index("idx_subscriptions_status", table_name="subscriptions")
    op.drop_index("idx_subscriptions_user_id", table_name="subscriptions")
    op.drop_table("subscriptions")

# ═════════════════════════════════════════════════════════════════════════════
# File    : alembic/versions/004_create_payment_transactions_v6.py
# Desc    : Buat tabel payment_transactions — rekaman transaksi Midtrans Snap.
#           Single source of truth audit trail pembayaran (Blueprint §6.15 [I3 FIX]).
#           Tidak ada tabel subscription_events terpisah.
# Revision: 004
# Fase    : Fase 0
# Ref     : Blueprint §6.8, Decision #1, §6.15 [I3 FIX], Appendix D
# ═════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "payment_transactions",
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
            sa.ForeignKey("users.id", name="fk_payment_transactions_user_id"),
            nullable=False,
        ),
        sa.Column(
            "subscription_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "subscriptions.id",
                name="fk_payment_transactions_subscription_id",
            ),
            nullable=True,
        ),
        sa.Column("order_id", sa.String(255), unique=True, nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),  # IDR (Rupiah)
        sa.Column("currency", sa.String(10), server_default="IDR", nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            server_default="pending",
            nullable=False,
        ),
        # plan_type & tier: snapshot saat transaksi untuk audit
        sa.Column("plan_type", sa.String(20), nullable=True),
        sa.Column("tier", sa.String(20), nullable=True),
        # raw Midtrans webhook payload — untuk reconciliation
        sa.Column("midtrans_response", postgresql.JSONB(), nullable=True),
        sa.Column("snap_token", sa.Text(), nullable=True),
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
        # CHECK constraint — status sesuai Midtrans lifecycle
        sa.CheckConstraint(
            "status IN ('pending', 'settlement', 'expire', 'cancel', 'deny', 'refund')",
            name="ck_payment_transactions_status",
        ),
    )

    # Index untuk lookup per user
    op.create_index("idx_payment_transactions_user_id", "payment_transactions", ["user_id"])


def downgrade() -> None:
    op.drop_index("idx_payment_transactions_user_id", table_name="payment_transactions")
    op.drop_table("payment_transactions")

# ═════════════════════════════════════════════════════════════════════════════
# File    : alembic/versions/002_create_institutional_accounts.py
# Desc    : Buat tabel institutional_accounts — akun kampus/prodi.
#           Dibuat sebelum subscriptions karena subscriptions punya FK ke sini.
# Revision: 002
# Fase    : Fase 0
# Ref     : Blueprint §6.9, Decision #5, Appendix D
# ═════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "institutional_accounts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("org_code", sa.String(50), unique=True, nullable=False),
        sa.Column("contact_email", sa.String(255), nullable=False),
        sa.Column("seats_purchased", sa.Integer(), nullable=False),
        sa.Column("seats_used", sa.Integer(), server_default="0", nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
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
    )


def downgrade() -> None:
    op.drop_table("institutional_accounts")

# ═════════════════════════════════════════════════════════════════════════════
# File    : alembic/versions/010_create_institutional_seats.py
# Desc    : Buat tabel institutional_seats — mapping user ke institutional_account.
#           Satu row per seat yang ter-assign.
#           Gap chain: skip 011 (user_preferences — dibuat Fase 2).
# Revision: 010
# Fase    : Fase 0
# Ref     : Blueprint §6.10, Decision #5, Appendix D
# ═════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "010"
down_revision: str | None = "009"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "institutional_seats",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "institutional_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "institutional_accounts.id",
                name="fk_institutional_seats_account_id",
            ),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", name="fk_institutional_seats_user_id"),
            nullable=False,
        ),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        # UNIQUE constraint: satu user hanya bisa punya satu seat per institutional_account
        sa.UniqueConstraint(
            "institutional_account_id",
            "user_id",
            name="uq_institutional_seats_account_user",
        ),
    )

    # Indexes untuk lookup per account dan per user
    op.create_index(
        "idx_institutional_seats_account_id",
        "institutional_seats",
        ["institutional_account_id"],
    )
    op.create_index(
        "idx_institutional_seats_user_id",
        "institutional_seats",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_institutional_seats_user_id", table_name="institutional_seats")
    op.drop_index("idx_institutional_seats_account_id", table_name="institutional_seats")
    op.drop_table("institutional_seats")

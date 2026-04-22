# ═════════════════════════════════════════════════════════════════════════════
# File    : alembic/versions/017_create_feature_flags_v6.py
# Desc    : Buat tabel feature_flags — kontrol feature per environment.
#           Seed data: 19 flags (Blueprint Appendix C — source of truth).
#           Catatan: angka 20/21 di PMD dan Appendix D adalah inkonsistensi
#           revisi. Appendix C adalah angka yang benar: 19 flags.
# Revision: 017
# Fase    : Fase 0
# Ref     : Blueprint §6.15, Appendix C, Appendix D
# ═════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "017"
down_revision: str | None = "016"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "feature_flags",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), unique=True, nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
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

    # Index untuk lookup cepat by name (dipakai setiap request ke endpoint yang
    # diguarded feature flag — Blueprint §2.2)
    op.create_index("idx_feature_flags_name", "feature_flags", ["name"])


def downgrade() -> None:
    op.drop_index("idx_feature_flags_name", table_name="feature_flags")
    op.drop_table("feature_flags")

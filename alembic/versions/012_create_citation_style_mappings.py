# ═════════════════════════════════════════════════════════════════════════════
# File    : alembic/versions/012_create_citation_style_mappings.py
# Desc    : Buat tabel citation_style_mappings — mapping prodi → citation style.
#           Seed data: 31 program studi (Blueprint Appendix F).
#           Digunakan CitationStyleResolver priority chain step 4 (Decision #9).
#
#           Gap chain: down_revision = "010" (skip 011 — user_preferences Fase 2).
#           Saat Fase 2 membuat 011, down_revision di sini diupdate ke "011".
#
# Revision: 012
# Fase    : Fase 0
# Ref     : Blueprint §6.15, Decision #9, Appendix D, Appendix F
# ═════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "012"
down_revision: str | None = "010"  # Gap: 011 dibuat Fase 2
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "citation_style_mappings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        # UNIQUE: satu field_of_study hanya punya satu rekomendasi
        sa.Column("field_of_study", sa.String(255), unique=True, nullable=False),
        # recommended_style: 'apa7' | 'ieee' | 'vancouver' | 'mla9' | 'chicago'
        sa.Column("recommended_style", sa.String(20), nullable=False),
        # confidence_level: digunakan CitationStyleResolver — hanya 'high' dan 'medium'
        # yang digunakan sebagai auto-detect (Decision #9 priority chain step 4)
        sa.Column("confidence_level", sa.String(10), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        # CHECK constraint — hanya 3 nilai confidence
        sa.CheckConstraint(
            "confidence_level IN ('high', 'medium', 'low')",
            name="ck_citation_style_mappings_confidence",
        ),
    )

    # Index untuk lookup cepat dari CitationStyleResolver
    op.create_index(
        "idx_citation_style_mappings_field",
        "citation_style_mappings",
        ["field_of_study"],
    )


def downgrade() -> None:
    op.drop_index("idx_citation_style_mappings_field", table_name="citation_style_mappings")
    op.drop_table("citation_style_mappings")

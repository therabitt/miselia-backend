# ═════════════════════════════════════════════════════════════════════════════
# File    : alembic/versions/015_create_prompt_versions_v6.py
# Desc    : Buat tabel prompt_versions — versi prompt per stage.
#           Seed data: 22 prompt entries P1–P8 (Blueprint Appendix C).
#
#           PENTING: Setelah membuat tabel ini, tambahkan FK constraint
#           fk_stage_outputs_prompt_version_id ke tabel stage_outputs.
#           FK ini tidak bisa dibuat di migration 009 karena tabel ini
#           belum exist saat itu.
#
#           Partial unique index: hanya satu is_active=TRUE per
#           (stage_type, prompt_name) — dibuat via raw SQL karena
#           SQLAlchemy tidak support partial unique index secara deklaratif.
#
#           Gap chain: down_revision = "013" (skip 014 — referral_codes Fase 6A).
#           Saat Fase 6A membuat 014, down_revision di sini diupdate ke "014".
#
# Revision: 015
# Fase    : Fase 0
# Ref     : Blueprint §6.15, Appendix D, Appendix C
# ═════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "015"
down_revision: str | None = "013"   # Gap: 014 dibuat Fase 6A
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # ── Buat tabel prompt_versions ────────────────────────────────────────
    op.create_table(
        "prompt_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("stage_type", sa.String(50), nullable=False),
        sa.Column("prompt_name", sa.String(100), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        # is_active: hanya satu TRUE per (stage_type, prompt_name)
        # — dijaga oleh partial unique index di bawah
        sa.Column("is_active", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )

    # Index standar untuk lookup per stage_type
    op.create_index("idx_prompt_versions_stage_type", "prompt_versions", ["stage_type"])

    # Partial UNIQUE index: satu versi aktif per (stage_type, prompt_name)
    # Mencegah multiple active prompts → non-deterministic prompt selection
    # Harus raw SQL — SQLAlchemy create_index tidak support partial unique index
    op.execute("""
        CREATE UNIQUE INDEX idx_prompt_versions_one_active
        ON prompt_versions(stage_type, prompt_name)
        WHERE is_active = TRUE
    """)

    # ── Tambahkan FK constraint ke stage_outputs.prompt_version_id ────────
    # FK ini tidak bisa dibuat di migration 009 karena tabel prompt_versions
    # belum exist saat itu. Sekarang tabel sudah ada, FK ditambahkan di sini.
    op.create_foreign_key(
        constraint_name="fk_stage_outputs_prompt_version_id",
        source_table="stage_outputs",
        referent_table="prompt_versions",
        local_cols=["prompt_version_id"],
        remote_cols=["id"],
        ondelete="SET NULL",    # Jika prompt version dihapus, set ke NULL (jangan cascade)
    )


def downgrade() -> None:
    # Hapus FK dari stage_outputs dulu sebelum drop tabel prompt_versions
    op.drop_constraint(
        "fk_stage_outputs_prompt_version_id",
        table_name="stage_outputs",
        type_="foreignkey",
    )
    op.execute("DROP INDEX IF EXISTS idx_prompt_versions_one_active")
    op.drop_index("idx_prompt_versions_stage_type", table_name="prompt_versions")
    op.drop_table("prompt_versions")

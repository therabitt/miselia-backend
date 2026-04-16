# ═════════════════════════════════════════════════════════════════════════════
# File    : alembic/versions/009_create_stage_outputs_v6.py
# Desc    : Buat tabel stage_outputs — one-to-one dengan stage_runs.
#           CATATAN FK: prompt_version_id dibuat TANPA FK constraint karena
#           tabel prompt_versions belum ada (dibuat di migration 015).
#           FK constraint fk_stage_outputs_prompt_version_id ditambahkan
#           oleh migration 015 via op.create_foreign_key().
#
#           Gap chain: down_revision = "006" (skip 007, 008 — dibuat Fase 1).
#           Saat Fase 1 membuat 007/008, down_revision di sini diupdate ke "008".
#
# Revision: 009
# Fase    : Fase 0
# Ref     : Blueprint §6.7, [M1 FIX] diagram_path vs diagram_data, Appendix D
# ═════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "009"
down_revision: str | None = "006"   # [GAP F1-1] Chain fix: 007 & 008 dibuat Fase 1
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "stage_outputs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        # One-to-one dengan stage_runs (UNIQUE constraint)
        sa.Column(
            "stage_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stage_runs.id", name="fk_stage_outputs_stage_run_id"),
            unique=True,
            nullable=False,
        ),
        # Raw AI output JSON — selalu ada
        sa.Column("output_data", postgresql.JSONB(), nullable=False),
        # File paths di Cloudflare R2
        # Format: outputs/{user_id}/{project_id}/{stage_run_id}/{stage_type}_{YYYY-MM-DD}.{ext}
        # Ref: Blueprint Appendix A R2 naming convention
        sa.Column("docx_path", sa.Text(), nullable=True),      # NULL untuk P8
        sa.Column("pdf_path", sa.Text(), nullable=True),        # Untuk P8
        # diagram_path: PNG statis P4 (export user) — BERBEDA dari diagram_data
        # [M1 FIX] diagram_data (JSONB live React Flow nodes/edges) ditambahkan Migration 027 (Fase 6B)
        sa.Column("diagram_path", sa.Text(), nullable=True),
        # prisma_path: SVG PRISMA flowchart P7 — di-embed ke DOCX via cairosvg
        sa.Column("prisma_path", sa.Text(), nullable=True),
        # monitoring_metadata: JSONB untuk data monitoring per run — provider_used, token_counts, dll.
        # Decision #23: provider_used disimpan di sini (bukan di output_data) untuk query-friendly monitoring
        # Contoh: {"provider_used": "anthropic", "model": "claude-haiku-4-5", "latency_ms": 1240}
        sa.Column("monitoring_metadata", postgresql.JSONB(), nullable=True),
        # prompt_version_id: FK ditambahkan nanti oleh migration 015
        # karena tabel prompt_versions belum exist saat ini
        sa.Column(
            "prompt_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            comment="FK ke prompt_versions ditambahkan oleh migration 015",
        ),
        sa.Column("quality_warning", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("quality_warning_reason", sa.Text(), nullable=True),
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

    # Index untuk lookup per stage_run (tambahan dari UNIQUE constraint)
    op.create_index("idx_stage_outputs_stage_run_id", "stage_outputs", ["stage_run_id"])
    # Index untuk lookup per prompt_version (untuk analytics prompt performance)
    op.create_index(
        "idx_stage_outputs_prompt_version",
        "stage_outputs",
        ["prompt_version_id"],
        postgresql_where=sa.text("prompt_version_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_stage_outputs_prompt_version", table_name="stage_outputs")
    op.drop_index("idx_stage_outputs_stage_run_id", table_name="stage_outputs")
    op.drop_table("stage_outputs")

# ═════════════════════════════════════════════════════════════════════════════
# File    : alembic/versions/008_create_search_results_v6.py
# Desc    : Buat tabel search_results — join table antara stage_runs dan papers.
#
#           KRITIS — Gap F1-3 resolution:
#             stage_run_id dibuat NULLABLE (bukan NOT NULL seperti Blueprint §6.6 DDL).
#             Alasan: search_results melayani DUA use case:
#               (1) Pipeline run → stage_run_id terisi (P1/P7 fetch papers)
#               (2) Push-to-project dari Library → stage_run_id = NULL
#                   (library_service.push_to_project() tanpa pipeline run)
#
#           UNIQUE constraint partial:
#             UNIQUE (stage_run_id, paper_id) HANYA saat stage_run_id IS NOT NULL.
#             PostgreSQL: NULL tidak dievaluasi dalam UNIQUE constraint — jadi
#             partial index WHERE stage_run_id IS NOT NULL diperlukan untuk
#             mencegah duplikasi dalam konteks pipeline yang sama.
#             Baris dengan stage_run_id=NULL (library push) boleh duplikat paper_id
#             selama ada di project/konteks berbeda.
#
# Revision: 008
# Fase    : Fase 1
# Ref     : Blueprint §6.6, Gap F1-3 (stage_run_id NULLABLE), Fase 1 STEP 1
#           library_service.py comment "INSERT ke search_results dengan stage_run_id=NULL"
# ═════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "008"
down_revision: str | None = "007"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "search_results",
        # ── Primary key ──────────────────────────────────────────────────
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        # ── Foreign keys ─────────────────────────────────────────────────
        # stage_run_id: NULLABLE — Gap F1-3 resolution.
        # NULL = digunakan untuk library push_to_project (tanpa pipeline run).
        # ON DELETE CASCADE: jika stage_run dihapus, search_results ikut hilang.
        sa.Column(
            "stage_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "stage_runs.id",
                name="fk_search_results_stage_run_id",
                ondelete="CASCADE",
            ),
            nullable=True,  # NULLABLE — Gap F1-3
        ),
        # paper_id: NOT NULL — selalu harus ada referensi ke paper.
        # ON DELETE CASCADE: jika paper global dihapus, search_results ikut hilang.
        sa.Column(
            "paper_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "papers.id",
                name="fk_search_results_paper_id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        # ── Scoring ──────────────────────────────────────────────────────
        # relevance_score / rank_position: nullable karena library push
        # tidak melalui scoring pipeline (tidak ada query untuk dibandingkan)
        sa.Column("relevance_score", sa.Float(), nullable=True),
        sa.Column("rank_position", sa.Integer(), nullable=True),
        # included_in_output: TRUE jika paper ini masuk ke DOCX output pipeline
        sa.Column(
            "included_in_output",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        # ── Timestamp ────────────────────────────────────────────────────
        # append-only — tidak ada updated_at (search_results tidak di-update setelah insert)
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )

    # ── Standard indexes ─────────────────────────────────────────────────
    # idx_search_results_paper_id: untuk lookup "semua stage run yang punya paper X"
    op.create_index("idx_search_results_paper_id", "search_results", ["paper_id"])

    # ── Partial indexes via raw SQL ───────────────────────────────────────
    # idx_search_results_stage_run_id: filter rows dengan stage_run_id terisi
    # Partial index untuk efisiensi — skip baris library push (stage_run_id=NULL)
    op.execute(
        """
        CREATE INDEX idx_search_results_stage_run_id
        ON search_results(stage_run_id)
        WHERE stage_run_id IS NOT NULL
    """
    )

    # UNIQUE partial index — Gap F1-3 resolution:
    # Mencegah paper yang sama muncul dua kali dalam satu pipeline run.
    # NULL tidak dievaluasi oleh UNIQUE — partial WHERE clause diperlukan.
    # Baris library push (stage_run_id=NULL) tidak terpengaruh oleh index ini.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_search_results_stage_paper
        ON search_results(stage_run_id, paper_id)
        WHERE stage_run_id IS NOT NULL
    """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_search_results_stage_paper")
    op.execute("DROP INDEX IF EXISTS idx_search_results_stage_run_id")
    op.drop_index("idx_search_results_paper_id", table_name="search_results")
    op.drop_table("search_results")

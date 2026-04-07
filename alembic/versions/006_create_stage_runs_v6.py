# ═════════════════════════════════════════════════════════════════════════════
# File    : alembic/versions/006_create_stage_runs_v6.py
# Desc    : Buat tabel stage_runs — satu eksekusi pipeline (P1–P8).
#           Mencakup semua stage types, source_stage_run_id (Decision #14),
#           input_params JSONB (Decision #18, #24), dan idempotency key.
# Revision: 006
# Fase    : Fase 0
# Ref     : Blueprint §6.4, Decision #8, #10, #14, #18, #24, Appendix D
# ═════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "006"
down_revision: str | None = "005"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "stage_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", name="fk_stage_runs_project_id"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", name="fk_stage_runs_user_id"),
            nullable=False,
        ),
        # stage_type: semua P1–P8 (Blueprint §6.4)
        sa.Column("stage_type", sa.String(50), nullable=False),
        # status: lifecycle eksekusi Celery task
        sa.Column(
            "status",
            sa.String(20),
            server_default="queued",
            nullable=False,
        ),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("filters", postgresql.JSONB(), nullable=True),
        # constraints: P3={sample_size, time_remaining, selected_gap_id}, P7={pico_framework}
        sa.Column("constraints", postgresql.JSONB(), nullable=True),
        # input_params: generik per pipeline
        #   P4: {methodology_mode, mode_source} — Decision #18
        #   P2–P8: {user_overrides: {...}} — Decision #24 Confirmation Gate
        sa.Column("input_params", postgresql.JSONB(), nullable=True),
        sa.Column("citation_style", sa.String(20), nullable=True),
        # source_stage_run_id: snapshot dependency — run mana yang jadi basis
        # Self-referential FK (Decision #14, Decision #10)
        sa.Column(
            "source_stage_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stage_runs.id", name="fk_stage_runs_source_stage_run_id"),
            nullable=True,
        ),
        sa.Column("progress_step", sa.Integer(), server_default="0", nullable=False),
        sa.Column("progress_detail", sa.Text(), nullable=True),
        # idempotency_key: cegah duplicate submit dari frontend (Decision #8)
        sa.Column("idempotency_key", sa.String(255), unique=True, nullable=True),
        sa.Column("celery_task_id", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        # CHECK constraints
        sa.CheckConstraint(
            """stage_type IN (
                'literature_review',
                'research_gap',
                'methodology_advisor',
                'hypothesis_variable',
                'proposisi_tema',
                'chapter_outline',
                'bab1_writer',
                'systematic_review',
                'sidang_preparation'
            )""",
            name="ck_stage_runs_stage_type",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="ck_stage_runs_status",
        ),
    )

    # Standard indexes — Blueprint Appendix E
    op.create_index("idx_stage_runs_project_id", "stage_runs", ["project_id"])
    op.create_index("idx_stage_runs_user_id", "stage_runs", ["user_id"])
    op.create_index("idx_stage_runs_status", "stage_runs", ["status"])
    op.create_index("idx_stage_runs_stage_type", "stage_runs", ["stage_type"])
    op.create_index("idx_stage_runs_source_run", "stage_runs", ["source_stage_run_id"])

    # Partial indexes — harus pakai raw SQL (Alembic tidak support WHERE di create_index)
    # idx_stage_runs_rerun_check: untuk query re-run limit Free tier (Decision #8)
    # Query: SELECT COUNT(*) FROM stage_runs WHERE user_id=? AND project_id=? AND stage_type=? AND status='completed'
    op.execute("""
        CREATE INDEX idx_stage_runs_rerun_check
        ON stage_runs(user_id, project_id, stage_type, status)
        WHERE status = 'completed'
    """)

    # idx_stage_runs_project_status: untuk project overview dan staleness check
    op.execute("""
        CREATE INDEX idx_stage_runs_project_status
        ON stage_runs(project_id, stage_type, status)
    """)

    # idx_stage_runs_celery_task: untuk orphaned task cleanup job (Blueprint §2.2 tasks.py)
    op.execute("""
        CREATE INDEX idx_stage_runs_celery_task
        ON stage_runs(celery_task_id)
        WHERE celery_task_id IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_stage_runs_celery_task")
    op.execute("DROP INDEX IF EXISTS idx_stage_runs_project_status")
    op.execute("DROP INDEX IF EXISTS idx_stage_runs_rerun_check")
    op.drop_index("idx_stage_runs_source_run", table_name="stage_runs")
    op.drop_index("idx_stage_runs_stage_type", table_name="stage_runs")
    op.drop_index("idx_stage_runs_status", table_name="stage_runs")
    op.drop_index("idx_stage_runs_user_id", table_name="stage_runs")
    op.drop_index("idx_stage_runs_project_id", table_name="stage_runs")
    op.drop_table("stage_runs")

# ═════════════════════════════════════════════════════════════════════════════
# File    : alembic/versions/005_create_projects_v6.py
# Desc    : Buat tabel projects — unit bisnis sentral Miselia.
#           review_type FINAL setelah dibuat — menentukan P1 vs P7 entry point.
#           'systematic' hanya untuk Magister (Decision #19).
# Revision: 005
# Fase    : Fase 0
# Ref     : Blueprint §6.3, Decision #3, Decision #19, Appendix D
# ═════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "005"
down_revision: str | None = "004"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "projects",
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
            sa.ForeignKey("users.id", name="fk_projects_user_id"),
            nullable=False,
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("field_of_study", sa.String(255), nullable=True),
        sa.Column("education_level", sa.String(10), nullable=True),
        sa.Column("citation_style", sa.String(20), nullable=True),
        # review_type: 'narrative' (default, P1 entry) | 'systematic' (Magister, P7 entry)
        # FINAL setelah project dibuat — Decision #19
        sa.Column(
            "review_type",
            sa.String(20),
            server_default="narrative",
            nullable=False,
        ),
        # status: 'active' | 'archived' — Decision #7
        sa.Column(
            "status",
            sa.String(20),
            server_default="active",
            nullable=False,
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
            "review_type IN ('narrative', 'systematic')",
            name="ck_projects_review_type",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_projects_status",
        ),
    )

    # Indexes — Blueprint Appendix E
    op.create_index("idx_projects_user_id", "projects", ["user_id"])
    op.create_index("idx_projects_status", "projects", ["status"])
    op.create_index("idx_projects_review_type", "projects", ["review_type"])


def downgrade() -> None:
    op.drop_index("idx_projects_review_type", table_name="projects")
    op.drop_index("idx_projects_status", table_name="projects")
    op.drop_index("idx_projects_user_id", table_name="projects")
    op.drop_table("projects")

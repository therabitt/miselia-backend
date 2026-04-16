# ═════════════════════════════════════════════════════════════════════════════
# File    : alembic/versions/023_add_triggers_updated_at.py
# Desc    : Buat trigger function set_updated_at() dan attach ke semua tabel
#           Fase 0 yang memiliki kolom updated_at.
#
#           Tabel Fase 0 dengan updated_at (8 tabel):
#             users, institutional_accounts, subscriptions,
#             payment_transactions, projects, stage_runs,
#             stage_outputs, feature_flags
#
#           Tabel Fase 0 TANPA updated_at (tidak perlu trigger):
#             institutional_seats (hanya assigned_at)
#             citation_style_mappings (hanya created_at)
#             prompt_versions (hanya created_at)
#             analytics_events (hanya created_at — partitioned table)
#
#           Tabel Fase 1+ akan mendapat trigger saat tabel dibuat.
#
# Revision: 023
# Fase    : Fase 0
# Ref     : Blueprint Appendix D
# ═════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from alembic import op

revision: str = "023"
down_revision: str | None = "022"
branch_labels: str | None = None
depends_on: str | None = None

# Tabel Fase 0 yang memiliki kolom updated_at
TABLES_WITH_UPDATED_AT: list[str] = [
    "users",
    "institutional_accounts",
    "subscriptions",
    "payment_transactions",
    "projects",
    "stage_runs",
    "stage_outputs",
    "feature_flags",
]


def upgrade() -> None:
    # ── Buat trigger function ─────────────────────────────────────────────
    # Satu function digunakan oleh semua trigger — lebih efisien dari satu
    # function per tabel.
    op.execute("""
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)

    # ── Attach trigger ke setiap tabel ────────────────────────────────────
    for table in TABLES_WITH_UPDATED_AT:
        op.execute(f"""
            CREATE TRIGGER trg_{table}_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW
            EXECUTE FUNCTION set_updated_at()
        """)


def downgrade() -> None:
    # Drop triggers dulu, kemudian drop function
    for table in TABLES_WITH_UPDATED_AT:
        op.execute(f"""
            DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table}
        """)

    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")

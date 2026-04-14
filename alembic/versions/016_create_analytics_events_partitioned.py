# ═════════════════════════════════════════════════════════════════════════════
# File    : alembic/versions/016_create_analytics_events_partitioned.py
# Desc    : Buat tabel analytics_events — partitioned by RANGE(created_at).
#
#           PENTING: PostgreSQL PARTITION BY RANGE tidak didukung SQLAlchemy
#           create_table(). Seluruh DDL di migration ini menggunakan raw SQL
#           via op.execute().
#
#           Struktur:
#           - Parent table: analytics_events (tidak menyimpan data langsung)
#           - Partisi awal: 2026-03, 2026-04, 2026-05
#           - Partisi berikutnya dibuat otomatis oleh Celery beat job
#             `create_monthly_partition` (setiap tanggal 1 pukul 00:05 WIB)
#
#           Query AKAN GAGAL jika tidak ada partisi matching. Selalu buat
#           partisi proaktif minimal 1 bulan ke depan (Blueprint §6.15).
#
#           Primary key: (id, created_at) — PostgreSQL partitioned table
#           mengharuskan partition key ada di primary key.
#
# Revision: 016
# Fase    : Fase 0
# Ref     : Blueprint §6.15, §14.1, Appendix D
# ═════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from alembic import op

revision: str = "016"
down_revision: str | None = "015"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # ── Parent table (partitioned) ────────────────────────────────────────
    # Tidak bisa menggunakan op.create_table() — harus raw SQL
    # Primary key: (id, created_at) karena PostgreSQL mensyaratkan partition key
    # harus ada di primary key atau unique constraint untuk partitioned tables
    op.execute("""
        CREATE TABLE analytics_events (
            id          UUID NOT NULL DEFAULT gen_random_uuid(),
            user_id     UUID REFERENCES users(id),
            session_id  TEXT,
            event_name  VARCHAR(100) NOT NULL,
            properties  JSONB,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (id, created_at)
        ) PARTITION BY RANGE (created_at)
    """)

    # ── Partisi awal: 3 bulan ke depan ────────────────────────────────────
    # Blueprint §6.15: "buat minimal 3 bulan ke depan saat launch"
    # Query FAIL jika tidak ada partisi matching — jangan skip ini
    op.execute("""
        CREATE TABLE analytics_events_2026_03
        PARTITION OF analytics_events
        FOR VALUES FROM ('2026-03-01') TO ('2026-04-01')
    """)

    op.execute("""
        CREATE TABLE analytics_events_2026_04
        PARTITION OF analytics_events
        FOR VALUES FROM ('2026-04-01') TO ('2026-05-01')
    """)

    op.execute("""
        CREATE TABLE analytics_events_2026_05
        PARTITION OF analytics_events
        FOR VALUES FROM ('2026-05-01') TO ('2026-06-01')
    """)

    # ── Indexes ────────────────────────────────────────────────────────────
    # Index pada parent table — PostgreSQL otomatis propagate ke semua partisi
    # Ref: Blueprint Appendix E
    op.execute("""
        CREATE INDEX idx_analytics_events_user_id
        ON analytics_events(user_id)
    """)

    op.execute("""
        CREATE INDEX idx_analytics_events_event_name
        ON analytics_events(event_name)
    """)

    op.execute("""
        CREATE INDEX idx_analytics_events_created_at
        ON analytics_events(created_at DESC)
    """)


def downgrade() -> None:
    # Drop indexes dulu, kemudian drop table (cascade ke partisi otomatis)
    op.execute("DROP INDEX IF EXISTS idx_analytics_events_created_at")
    op.execute("DROP INDEX IF EXISTS idx_analytics_events_event_name")
    op.execute("DROP INDEX IF EXISTS idx_analytics_events_user_id")

    # DROP TABLE CASCADE otomatis menghapus semua partisi
    op.execute("DROP TABLE IF EXISTS analytics_events CASCADE")

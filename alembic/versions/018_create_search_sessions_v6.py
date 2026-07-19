# ═════════════════════════════════════════════════════════════════════════════
# File    : alembic/versions/018_create_search_sessions_v6.py
# Desc    : Buat tabel search_sessions — menyimpan riwayat pencarian paper
#           oleh authenticated user.
#
#           PENTING (Blueprint §3.4, Decision #13):
#             Guest request TIDAK disimpan ke tabel ini.
#             Tabel ini hanya untuk authenticated user (user_id NOT NULL).
#             Insert dilakukan oleh find_papers_service.save_search_session()
#             hanya jika user is not None.
#
#           Kolom paper_ids menyimpan JSONB list[str] UUID — bukan FK array.
#           Ini disengaja agar session history tetap utuh meski paper global
#           di-dedup/merge/hapus setelahnya (snapshot semantics).
#
#           Tabel ini append-only — tidak ada updated_at.
#
# Revision: 018
# Fase    : Fase 1
# Ref     : Blueprint §6.11, §3.4, Decision #13 (guest sessions tidak disimpan)
#           Fase 1 STEP 1, find_papers_service.save_search_session()
# ═════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "018"
down_revision: str | None = "017"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "search_sessions",
        # ── Primary key ──────────────────────────────────────────────────
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        # ── Foreign key ───────────────────────────────────────────────────
        # NOT NULL — guest sessions tidak disimpan (Blueprint §3.4)
        # ON DELETE CASCADE: jika user dihapus, search history ikut hilang (GDPR compliance)
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "users.id",
                name="fk_search_sessions_user_id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        # ── Query & filters snapshot ──────────────────────────────────────
        sa.Column("query", sa.Text(), nullable=False),
        # filters: JSONB snapshot FindPapersFilters — {year_from, year_to,
        # document_types, min_citations, language}. NULL jika tidak ada filter.
        sa.Column("filters", postgresql.JSONB(), nullable=True),
        # paper_ids: JSONB list[str] UUID — snapshot ID paper hasil pencarian
        # Tidak menggunakan FK array agar session history tetap utuh
        # meski paper di-merge/dedup setelahnya
        sa.Column("paper_ids", postgresql.JSONB(), nullable=True),
        # result_count: int — jumlah paper yang dikembalikan ke user
        # Disimpan agar bisa ditampilkan di RecentSearches tanpa re-query
        sa.Column("result_count", sa.Integer(), server_default="0", nullable=False),
        # ── Timestamp ────────────────────────────────────────────────────
        # append-only — tidak ada updated_at (search_sessions tidak di-update)
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )

    # ── Indexes ───────────────────────────────────────────────────────────
    # idx_search_sessions_user_id: dasar lookup per user
    op.create_index("idx_search_sessions_user_id", "search_sessions", ["user_id"])

    # idx_search_sessions_user_created: composite — digunakan oleh
    # GET /papers/search-sessions yang selalu pakai WHERE user_id = ?
    # ORDER BY created_at DESC LIMIT 20
    op.execute("""
        CREATE INDEX idx_search_sessions_user_created
        ON search_sessions(user_id, created_at DESC)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_search_sessions_user_created")
    op.drop_index("idx_search_sessions_user_id", table_name="search_sessions")
    op.drop_table("search_sessions")

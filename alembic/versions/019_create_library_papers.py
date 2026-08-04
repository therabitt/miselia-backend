# ═══════════════════════════════════════════════════════════════════════════
# File    : alembic/versions/019_create_library_papers.py
# Desc    : Buat tabel library_papers — paper yang disimpan user ke Library.
#
#           Schema lengkap sesuai Blueprint §6.12 — mencakup kolom soft delete
#           (is_visible, expires_at, expired_at) dan is_incomplete sehingga migration 026
#           menjadi no-op (tidak perlu ALTER TABLE terpisah).
#
#           Kolom kritis:
#           - notes TEXT: catatan pribadi user, max 2000 char (divalidasi service)
#           - tags TEXT[]: tag bebas, max 10 item, GIN index untuk filter
#           - is_visible BOOLEAN: soft delete flag (FALSE = hidden dari UI)
#           - expires_at TIMESTAMPTZ: NULL untuk Sarjana/Magister, NOW()+30d untuk Free
#           - expired_at TIMESTAMPTZ: set saat is_visible → FALSE (window 90-hari restore)
#           - is_incomplete BOOLEAN: paper tanpa abstract, badge "Tanpa abstract" (Decision #28)
#
#           Kolom import_batch_id TIDAK ada di migration ini.
#           Kolom ini ditambahkan di migration 028 (Decision #28, Fase 5) karena
#           memerlukan tabel import_batches yang baru dibuat di 028.
#           Source CHECK constraint di migration ini mencakup: 'find_papers' dan 'stage_run'
#           (028 akan ALTER dan tambah csv/bib/ris seiring penambahan import_batch_id).
#
# Revision: 019
# Fase    : Fase 2
# Ref     : Blueprint §6.12, Decision #2 (soft delete + 90-day restore)
# ═══════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "019"
down_revision: str | None = "018"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "library_papers",
        sa.Column(
            "id",
            sa.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "paper_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("papers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Source paper masuk ke Library — Fase 2 hanya find_papers + stage_run.
        # csv_import, bib_import, ris_import ditambahkan di migration 028 (Decision #28).
        sa.Column(
            "source",
            sa.String(30),
            sa.CheckConstraint(
                "source IN ('find_papers', 'stage_run')",
                name="ck_library_papers_source",
            ),
            nullable=False,
        ),
        # FK ke stage_runs — hanya terisi jika source = 'stage_run'
        sa.Column(
            "source_stage_run_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("stage_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Catatan pribadi user. Max 2000 karakter — divalidasi di service layer.
        # Plain text, preserve newlines di UI. NULL = belum ada catatan.
        sa.Column("notes", sa.Text, nullable=True),
        # Tag bebas (free-form). TEXT[] untuk query alami dengan @> GIN operator.
        # Normalisasi: lowercase + trim sebelum simpan (service layer).
        # Max 10 item, setiap tag max 30 char — divalidasi di service layer.
        # NULL = belum ada tag.
        sa.Column("tags", postgresql.ARRAY(sa.Text), nullable=True),
        # ── Soft Delete Fields (Blueprint §6.12, Decision #2) ──────────────
        # TRUE = paper aktif dan terlihat user
        # FALSE = paper expired/disembunyikan (soft deleted)
        # Paper dikembalikan ke TRUE otomatis jika user upgrade dalam 90 hari sejak expires_at
        sa.Column(
            "is_visible", sa.Boolean, nullable=False, server_default=sa.text("TRUE")
        ),
        # NULL untuk Sarjana/Magister/Institutional (tidak pernah expired).
        # Set ke added_at + 30 hari untuk Free tier saat paper ditambahkan.
        # Di-extend ke current_period_end baru jika user upgrade sebelum expires_at.
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        # Set saat is_visible diubah ke FALSE — digunakan untuk hitung window 90-hari restore.
        # NULL selama is_visible = TRUE.
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
        # TRUE jika paper diimpor tanpa abstract (field abstract kosong di file sumber).
        # Ditampilkan sebagai badge "Tanpa abstract" di LibraryPaperCard.
        # Decision #28 — dimasukkan di 019 (bukan 028) karena standalone boolean tanpa FK.
        sa.Column(
            "is_incomplete",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        # Satu user tidak bisa simpan paper yang sama dua kali
        sa.UniqueConstraint("user_id", "paper_id", name="uq_library_papers_user_paper"),
    )

    # ── Indexes ──────────────────────────────────────────────────────────────

    # Query library papers by visibility — query paling sering (GET /library/papers)
    op.create_index(
        "idx_library_papers_visible",
        "library_papers",
        ["user_id", "is_visible"],
    )

    # Query papers yang akan expire — digunakan notify_library_expiry job
    # Partial index: hanya untuk paper yang masih visible dan punya expiry
    op.execute(
        """
        CREATE INDEX idx_library_papers_expires_at
        ON library_papers(expires_at)
        WHERE expires_at IS NOT NULL AND is_visible = TRUE
        """
    )

    # GIN index untuk filter by tag — mendukung @> operator query
    # GET /library/papers?tags[]=ml → WHERE tags @> ARRAY['ml']
    op.execute(
        """
        CREATE INDEX idx_library_papers_tags
        ON library_papers USING GIN(tags)
        WHERE tags IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_library_papers_tags")
    op.execute("DROP INDEX IF EXISTS idx_library_papers_expires_at")
    op.drop_index("idx_library_papers_visible", table_name="library_papers")
    op.drop_table("library_papers")

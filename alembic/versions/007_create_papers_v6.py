# ═════════════════════════════════════════════════════════════════════════════
# File    : alembic/versions/007_create_papers_v6.py
# Desc    : Buat tabel papers — shared paper database dari Semantic Scholar
#           dan OpenAlex. Digunakan oleh Find Papers, Pipeline P1, P7,
#           Library, dan Chat with Papers.
#
#           Kolom kunci:
#             - semantic_scholar_id / openalex_id: external IDs (nullable, unique)
#             - garuda_id: reserved untuk Decision #27 (defer, belum aktif)
#             - title_hash: SHA-256(normalize(title)+year) untuk dedup fallback
#             - authors: JSONB list[str] — snapshot saat fetch
#             - sources: JSONB {semantic_scholar: {...}, openalex: {...}}
#             - quality_signal: JSONB untuk JBI/CASP scores (P7 Magister, Fase 4)
#             - is_manually_imported: TRUE jika dari csv/bib/ris import (Decision #28)
#
#
#           Gap F1-2 resolution: trigger updated_at untuk tabel papers
#           di-attach oleh migration 023 (single source of truth untuk semua
#           trigger). Migration 007 TIDAK memanggil set_updated_at() langsung
#           karena fungsi tersebut belum ada saat migration 007 berjalan.
#           Lihat migration 023: TABLES_WITH_UPDATED_AT sudah mencakup 'papers'.
#
# Revision: 007
# Fase    : Fase 1
# Ref     : Blueprint §6.5, Decision #27 (garuda_id reserved), Decision #28
#           (is_manually_imported), Gap F1-2 (trigger via migration 023)
#           Appendix D, Fase 1 STEP 1
# ═════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "007"
down_revision: str | None = "006"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "papers",
        # ── Primary key ──────────────────────────────────────────────────
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        # ── External IDs — nullable, unique per source ───────────────────
        # Tidak semua paper ada di semua source — nullable adalah sengaja.
        sa.Column("semantic_scholar_id", sa.String(255), unique=True, nullable=True),
        sa.Column("openalex_id", sa.String(255), unique=True, nullable=True),
        # garuda_id: reserved untuk Decision #27 — integrasi SINTA/Garuda
        # defer ke post-full-product. Kolom ini TIDAK aktif digunakan sampai
        # Decision #27 di-revisit (partnership/API resmi Kemendikbud).
        sa.Column("garuda_id", sa.String(255), unique=True, nullable=True),
        # ── Core metadata ────────────────────────────────────────────────
        sa.Column("title", sa.Text(), nullable=False),
        # title_hash: SHA-256(normalize(title) + str(year)) — fallback dedup
        # ketika DOI tidak ada. normalize = lowercase → strip → remove punctuation
        # → collapse spaces. Computed oleh paper_service.py, bukan DB trigger.
        sa.Column("title_hash", sa.String(64), nullable=True),
        # authors: JSONB list[str] — ["Budi Santoso", "Ani Wijaya"]
        # Snapshot saat fetch — tidak di-update secara otomatis
        sa.Column("authors", postgresql.JSONB(), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("venue", sa.Text(), nullable=True),
        sa.Column("citation_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("abstract", sa.Text(), nullable=True),
        # abstract_language: 'id' | 'en' | None — dideteksi saat fetch
        sa.Column("abstract_language", sa.String(10), nullable=True),
        sa.Column("full_text", sa.Text(), nullable=True),
        # sources: JSONB — raw metadata per source untuk debugging
        # Contoh: {"semantic_scholar": {"paperId": "...", "tldr": "..."}}
        sa.Column("sources", postgresql.JSONB(), nullable=True),
        # ── Access metadata ──────────────────────────────────────────────
        sa.Column("doi", sa.Text(), nullable=True),
        sa.Column("pdf_url", sa.Text(), nullable=True),
        sa.Column("is_open_access", sa.Boolean(), server_default="false", nullable=False),
        # ── Pipeline-specific ────────────────────────────────────────────
        # quality_signal: JBI/CASP assessment scores untuk P7 SLR (Magister only, Fase 4)
        # Format: {"jbi_score": 8, "jbi_max": 11, "casp_score": 7, "assessed_by": "p7_run_id"}
        sa.Column("quality_signal", postgresql.JSONB(), nullable=True),
        # is_manually_imported: TRUE = dari import file user (csv/bib/ris) — Decision #28
        # Di-set TRUE oleh upsert_paper() saat confirm_import(). Menandai bahwa
        # metadata mungkin belum ter-validasi via external API enrichment.
        sa.Column(
            "is_manually_imported",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        # ── Timestamps ───────────────────────────────────────────────────
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

    # ── Standard indexes ─────────────────────────────────────────────────
    # idx_papers_title_hash: digunakan oleh dedup_and_merge() saat DOI tidak ada
    op.create_index("idx_papers_title_hash", "papers", ["title_hash"])
    # idx_papers_doi: digunakan oleh dedup_and_merge() primary DOI lookup
    op.create_index("idx_papers_doi", "papers", ["doi"])
    # idx_papers_year: untuk filter hasil pencarian by year range
    op.create_index("idx_papers_year", "papers", ["year"])

    # ── updated_at trigger (Gap F1-2 resolution) ─────────────────────────
    # TIDAK dibuat di sini — set_updated_at() belum ada saat migration 007 berjalan.
    # Trigger trg_papers_updated_at dibuat oleh migration 023 (TABLES_WITH_UPDATED_AT).
    # Ini adalah single source of truth yang benar untuk semua trigger updated_at.


def downgrade() -> None:
    # Trigger trg_papers_updated_at di-drop oleh migration 023 downgrade.
    op.drop_index("idx_papers_year", table_name="papers")
    op.drop_index("idx_papers_doi", table_name="papers")
    op.drop_index("idx_papers_title_hash", table_name="papers")
    op.drop_table("papers")

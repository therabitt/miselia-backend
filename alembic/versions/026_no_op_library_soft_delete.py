# ═══════════════════════════════════════════════════════════════════════════
# File    : alembic/versions/026_no_op_library_soft_delete.py
# Desc    : NO-OP — migration ini tidak membuat atau mengubah apapun.
#
#           LATAR BELAKANG:
#           Blueprint Appendix D mencantumkan "026_add_soft_delete_to_library_papers.py"
#           dengan isi ALTER TABLE untuk menambah kolom:
#             - is_visible BOOLEAN DEFAULT TRUE
#             - expires_at TIMESTAMPTZ
#             - expired_at TIMESTAMPTZ
#           dan dua index:
#             - idx_library_papers_visible
#             - idx_library_papers_expires_at (partial)
#
#           RESOLUSI (Blueprint PMD §Fase 2 Database):
#           "Migration 026 hanya perlu jika schema library_papers awal tidak lengkap —
#           jika dibuat sesuai §6.12 dari awal, migration 026 bisa di-skip."
#
#           Migration 019 (dibuat Fase 2 STEP 1) sudah mencakup semua kolom dan index
#           tersebut langsung di DDL CREATE TABLE — sesuai §6.12 penuh.
#           Oleh karena itu 026 menjadi no-op.
#
#           File ini dipertahankan untuk menjaga konsistensi Alembic chain (Appendix D).
#           Melewatkan nomor urut akan menyebabkan kebingungan di audit dan
#           down_revision chain untuk migration berikutnya (027, 028).
#
# Revision: 026
# Fase    : Fase 2
# Ref     : Blueprint §6.12, Appendix D, PMD Fase 2 §C Database
# ═══════════════════════════════════════════════════════════════════════════

from __future__ import annotations

revision: str = "026"
down_revision: str | None = "024"
# [NOTE] Blueprint Appendix D menempatkan 026 setelah 025 (add_provider_used_to_stage_outputs).
# Migration 025 adalah Fase 3 (ALTER TABLE stage_outputs) — belum dibuat.
# down_revision diset ke "024" untuk saat ini; akan dikoreksi saat 025 dibuat di Fase 3.
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # NO-OP: is_visible, expires_at, expired_at sudah ada di migration 019.
    # Lihat komentar header untuk latar belakang lengkap.
    pass


def downgrade() -> None:
    # NO-OP: tidak ada yang di-reverse.
    pass

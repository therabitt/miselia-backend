# ═════════════════════════════════════════════════════════════════════════════
# File    : alembic/versions/013_no_op_saved_papers_deprecated.py
# Desc    : NO-OP — migration ini tidak membuat tabel apapun.
#
#           LATAR BELAKANG:
#           Blueprint Appendix D mencantumkan "013_create_saved_papers.py"
#           sebagai bagian migration order. Namun Blueprint §6.15 [C3]
#           secara eksplisit menyatakan:
#             "DIHAPUS: saved_papers — duplikasi dengan library_papers.
#              library_papers adalah single source of truth.
#              Jangan buat saved_papers."
#
#           Konflik ini terjadi karena revisi Blueprint tidak konsisten —
#           entry 013 di Appendix D belum dihapus meski tabelnya sudah
#           digantikan oleh migration 019 (library_papers).
#
#           RESOLUSI: No-op ini dibuat untuk menjaga nomor urut migration
#           tetap konsisten. Tidak ada DDL yang dijalankan.
#           Ref: Konflik teridentifikasi dan dikonfirmasi developer —
#           "saved_papers digantikan library_papers (migration 019)."
#
# Revision: 013
# Fase    : Fase 0 (no-op)
# Ref     : Blueprint §6.15 [C3], Appendix D, Developer note G2
# ═════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

revision: str = "013"
down_revision: str | None = "012"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # NO-OP: saved_papers tidak dibuat — tergantikan oleh migration 019 library_papers.
    # Lihat Blueprint §6.15 [C3] dan komentar file header di atas.
    pass


def downgrade() -> None:
    # NO-OP: tidak ada DDL yang perlu di-reverse.
    pass

# ═══════════════════════════════════════════════════════════════════════════
# File    : alembic/versions/011_create_user_preferences.py
# Desc    : Buat tabel user_preferences — menyimpan UI preferences user
#           seperti citation style, bahasa, dan email notification setting.
#           Terpisah dari tabel users agar schema users tetap ringkas.
#
#           Catatan chain:
#           Migration ini mengisi slot 011 yang sudah dipersiapkan sejak Fase 0.
#           Setelah migration ini dibuat, down_revision di 012 harus diupdate
#           dari "010" ke "011" (dilakukan bersamaan di STEP 1 Fase 2).
#
# Revision: 011
# Fase    : Fase 2
# Ref     : Blueprint §6.11, §11.15 (onboarding Screen 3 — citation style)
# ═══════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "011"
down_revision: str | None = "010"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "user_preferences",
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
            unique=True,
        ),
        # Gaya sitasi default pilihan user — override dari auto-detect prodi
        # NULL = belum di-set (sistem akan gunakan auto-detect atau APA7 fallback)
        # Ref: Blueprint §6.11, Decision #9 (citation style resolution order)
        sa.Column("preferred_citation_style", sa.String(20), nullable=True),
        # Bahasa antarmuka — default Bahasa Indonesia
        sa.Column("ui_language", sa.String(10), nullable=False, server_default="id"),
        # Notifikasi email — aktif secara default
        sa.Column(
            "email_notifications", sa.Boolean, nullable=False, server_default="true"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # Index untuk lookup user_preferences by user_id (UNIQUE enforces single row per user)
    op.create_index(
        "idx_user_preferences_user_id",
        "user_preferences",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_user_preferences_user_id", table_name="user_preferences")
    op.drop_table("user_preferences")

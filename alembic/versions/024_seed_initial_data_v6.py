# ═════════════════════════════════════════════════════════════════════════════
# File    : alembic/versions/024_seed_initial_data_v6.py
# Desc    : Seed initial data dan apply Row Level Security (RLS) policies.
#
#           Operasi yang dilakukan:
#           PART A — Seed data via scripts/seed_db.py:
#             - 22 prompt entries P1–P8 ke tabel prompt_versions
#             - 19 feature flags ke tabel feature_flags
#             - 31 citation style mappings ke tabel citation_style_mappings
#
#           PART B — Row Level Security (RLS) policies:
#             Infrastructure as Code approach — RLS di-version control via
#             Alembic sehingga konsisten di semua environment.
#             Tabel yang di-protect: users, subscriptions, projects,
#             stage_runs, stage_outputs, payment_transactions,
#             institutional_seats
#             Tabel global (tanpa RLS user-level): citation_style_mappings,
#             prompt_versions, feature_flags, analytics_events
#
#           CATATAN: seed_db.py harus ada dan bisa diimport sebelum
#           migration ini dijalankan.
#
# Revision: 024
# Fase    : Fase 0
# Ref     : Blueprint Appendix C, Appendix D, Appendix F, PMD Fase 0 DoD
# ═════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import sys
import os
from alembic import op

revision: str = "024"
down_revision: str | None = "023"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # ═══════════════════════════════════════════════════════════════════════
    # PART A — Seed initial data
    # ═══════════════════════════════════════════════════════════════════════
    # Import seed functions dari scripts/seed_db.py
    # Path resolution: alembic dijalankan dari root miselia-backend/
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
    from scripts.seed_db import (
        seed_prompt_versions,
        seed_feature_flags,
        seed_citation_style_mappings,
    )

    # Dapatkan raw connection dari alembic migration context
    # untuk dipass ke seed functions
    bind = op.get_bind()
    seed_prompt_versions(bind)
    seed_feature_flags(bind)
    seed_citation_style_mappings(bind)

    # ═══════════════════════════════════════════════════════════════════════
    # PART B — Row Level Security (RLS) Policies
    # Infrastructure as Code: semua RLS di-manage via Alembic
    # Ref: Supabase Auth — user JWT berisi auth.uid() = supabase_id
    # ═══════════════════════════════════════════════════════════════════════

    # ── Enable RLS pada semua tabel user-facing ───────────────────────────
    user_facing_tables = [
        "users",
        "subscriptions",
        "projects",
        "stage_runs",
        "stage_outputs",
        "payment_transactions",
        "institutional_seats",
    ]
    for table in user_facing_tables:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")

    # ── Tabel: users ──────────────────────────────────────────────────────
    # User hanya bisa membaca dan mengupdate data diri sendiri.
    # Service role (backend FastAPI) bisa akses semua via service_role key.
    op.execute("""
        CREATE POLICY users_select_own ON users
        FOR SELECT
        TO authenticated
        USING (supabase_id = auth.uid())
    """)

    op.execute("""
        CREATE POLICY users_update_own ON users
        FOR UPDATE
        TO authenticated
        USING (supabase_id = auth.uid())
        WITH CHECK (supabase_id = auth.uid())
    """)

    # INSERT ke users dilakukan hanya oleh service_role (backend saat POST /auth/verify)
    # Tidak ada policy INSERT untuk authenticated — backend menggunakan service_role key
    op.execute("""
        CREATE POLICY users_insert_service ON users
        FOR INSERT
        TO service_role
        WITH CHECK (true)
    """)

    # ── Tabel: subscriptions ─────────────────────────────────────────────
    # User hanya bisa membaca subscription diri sendiri.
    # CREATE/UPDATE subscription hanya via service_role (backend payment webhook).
    op.execute("""
        CREATE POLICY subscriptions_select_own ON subscriptions
        FOR SELECT
        TO authenticated
        USING (
            user_id IN (
                SELECT id FROM users WHERE supabase_id = auth.uid()
            )
        )
    """)

    op.execute("""
        CREATE POLICY subscriptions_all_service ON subscriptions
        FOR ALL
        TO service_role
        USING (true)
        WITH CHECK (true)
    """)

    # ── Tabel: projects ───────────────────────────────────────────────────
    # User hanya bisa CRUD project miliknya sendiri.
    op.execute("""
        CREATE POLICY projects_select_own ON projects
        FOR SELECT
        TO authenticated
        USING (
            user_id IN (
                SELECT id FROM users WHERE supabase_id = auth.uid()
            )
        )
    """)

    op.execute("""
        CREATE POLICY projects_insert_own ON projects
        FOR INSERT
        TO authenticated
        WITH CHECK (
            user_id IN (
                SELECT id FROM users WHERE supabase_id = auth.uid()
            )
        )
    """)

    op.execute("""
        CREATE POLICY projects_update_own ON projects
        FOR UPDATE
        TO authenticated
        USING (
            user_id IN (
                SELECT id FROM users WHERE supabase_id = auth.uid()
            )
        )
        WITH CHECK (
            user_id IN (
                SELECT id FROM users WHERE supabase_id = auth.uid()
            )
        )
    """)

    # DELETE projects tidak diizinkan — hanya archive via PATCH status='archived'
    # Tidak ada DELETE policy untuk authenticated user

    op.execute("""
        CREATE POLICY projects_all_service ON projects
        FOR ALL
        TO service_role
        USING (true)
        WITH CHECK (true)
    """)

    # ── Tabel: stage_runs ─────────────────────────────────────────────────
    # User hanya bisa membaca stage_runs miliknya.
    # INSERT/UPDATE dilakukan via service_role (backend Celery worker).
    op.execute("""
        CREATE POLICY stage_runs_select_own ON stage_runs
        FOR SELECT
        TO authenticated
        USING (
            user_id IN (
                SELECT id FROM users WHERE supabase_id = auth.uid()
            )
        )
    """)

    op.execute("""
        CREATE POLICY stage_runs_insert_own ON stage_runs
        FOR INSERT
        TO authenticated
        WITH CHECK (
            user_id IN (
                SELECT id FROM users WHERE supabase_id = auth.uid()
            )
        )
    """)

    # UPDATE dan status change hanya via service_role (Celery worker update progress/status)
    op.execute("""
        CREATE POLICY stage_runs_all_service ON stage_runs
        FOR ALL
        TO service_role
        USING (true)
        WITH CHECK (true)
    """)

    # ── Tabel: stage_outputs ──────────────────────────────────────────────
    # User bisa SELECT output untuk stage_run miliknya.
    # INSERT/UPDATE hanya via service_role (Celery worker menyimpan output).
    op.execute("""
        CREATE POLICY stage_outputs_select_own ON stage_outputs
        FOR SELECT
        TO authenticated
        USING (
            stage_run_id IN (
                SELECT id FROM stage_runs
                WHERE user_id IN (
                    SELECT id FROM users WHERE supabase_id = auth.uid()
                )
            )
        )
    """)

    op.execute("""
        CREATE POLICY stage_outputs_all_service ON stage_outputs
        FOR ALL
        TO service_role
        USING (true)
        WITH CHECK (true)
    """)

    # ── Tabel: payment_transactions ───────────────────────────────────────
    # User hanya bisa SELECT transaksi miliknya (untuk history pembayaran).
    # INSERT/UPDATE hanya via service_role (backend payment webhook handler).
    op.execute("""
        CREATE POLICY payment_transactions_select_own ON payment_transactions
        FOR SELECT
        TO authenticated
        USING (
            user_id IN (
                SELECT id FROM users WHERE supabase_id = auth.uid()
            )
        )
    """)

    op.execute("""
        CREATE POLICY payment_transactions_all_service ON payment_transactions
        FOR ALL
        TO service_role
        USING (true)
        WITH CHECK (true)
    """)

    # ── Tabel: institutional_seats ────────────────────────────────────────
    # User bisa SELECT seat yang assigned ke dirinya.
    # INSERT/UPDATE/DELETE hanya via service_role (admin).
    op.execute("""
        CREATE POLICY institutional_seats_select_own ON institutional_seats
        FOR SELECT
        TO authenticated
        USING (
            user_id IN (
                SELECT id FROM users WHERE supabase_id = auth.uid()
            )
        )
    """)

    op.execute("""
        CREATE POLICY institutional_seats_all_service ON institutional_seats
        FOR ALL
        TO service_role
        USING (true)
        WITH CHECK (true)
    """)

    # ── Tabel global (read-only, tanpa RLS user-level) ────────────────────
    # citation_style_mappings, prompt_versions, feature_flags:
    # Semua authenticated user bisa SELECT.
    # INSERT/UPDATE hanya via service_role (seed + admin).
    # Tidak perlu ENABLE RLS untuk tabel ini karena tidak ada data user-spesifik.
    # Backend mengaksesnya via service_role key — tidak ada kebocoran data.

    # ── analytics_events ──────────────────────────────────────────────────
    # Partitioned table — RLS lebih kompleks karena partisi inherit policy parent.
    # User TIDAK boleh SELECT analytics_events (data internal monitoring).
    # INSERT dilakukan via service_role (backend event tracking).
    # TIDAK di-enable RLS untuk analytics_events — backend selalu pakai service_role.


def downgrade() -> None:
    # ── Drop RLS policies ─────────────────────────────────────────────────
    rls_policies = [
        ("users",                   "users_select_own"),
        ("users",                   "users_update_own"),
        ("users",                   "users_insert_service"),
        ("subscriptions",           "subscriptions_select_own"),
        ("subscriptions",           "subscriptions_all_service"),
        ("projects",                "projects_select_own"),
        ("projects",                "projects_insert_own"),
        ("projects",                "projects_update_own"),
        ("projects",                "projects_all_service"),
        ("stage_runs",              "stage_runs_select_own"),
        ("stage_runs",              "stage_runs_insert_own"),
        ("stage_runs",              "stage_runs_all_service"),
        ("stage_outputs",           "stage_outputs_select_own"),
        ("stage_outputs",           "stage_outputs_all_service"),
        ("payment_transactions",    "payment_transactions_select_own"),
        ("payment_transactions",    "payment_transactions_all_service"),
        ("institutional_seats",     "institutional_seats_select_own"),
        ("institutional_seats",     "institutional_seats_all_service"),
    ]

    for table, policy in rls_policies:
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")

    # ── Disable RLS ───────────────────────────────────────────────────────
    user_facing_tables = [
        "users",
        "subscriptions",
        "projects",
        "stage_runs",
        "stage_outputs",
        "payment_transactions",
        "institutional_seats",
    ]
    for table in user_facing_tables:
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    # ── Seed rollback: hapus semua seed data ──────────────────────────────
    # Hanya hapus data yang diinsert oleh seed (bukan user-generated data)
    op.execute("DELETE FROM prompt_versions WHERE version = 1")
    op.execute("DELETE FROM feature_flags")
    op.execute("DELETE FROM citation_style_mappings")

# ═════════════════════════════════════════════════════════════════════════════
# File    : alembic/versions/022_phase0_indexes_marker.py
# Desc    : FASE 0 INDEX MARKER — tidak ada DDL baru di migration ini.
#
#           Semua index untuk tabel Fase 0 sudah dibuat di migration individu:
#             001: idx_users_supabase_id, idx_users_email
#             003: idx_subscriptions_user_id, idx_subscriptions_status,
#                  idx_subscriptions_period_end
#             005: idx_projects_user_id, idx_projects_status,
#                  idx_projects_review_type
#             006: idx_stage_runs_project_id, idx_stage_runs_user_id,
#                  idx_stage_runs_status, idx_stage_runs_stage_type,
#                  idx_stage_runs_source_run,
#                  idx_stage_runs_rerun_check (partial),
#                  idx_stage_runs_project_status (partial),
#                  idx_stage_runs_celery_task (partial)
#             009: idx_stage_outputs_stage_run_id,
#                  idx_stage_outputs_prompt_version (partial)
#             010: idx_institutional_seats_account_id,
#                  idx_institutional_seats_user_id
#             012: idx_citation_style_mappings_field
#             015: idx_prompt_versions_stage_type,
#                  idx_prompt_versions_one_active (partial unique)
#             016: idx_analytics_events_user_id,
#                  idx_analytics_events_event_name,
#                  idx_analytics_events_created_at
#             017: idx_feature_flags_name
#
#           Index untuk tabel Fase 1+ (papers, search_sessions, library_papers,
#           chat_sessions, chat_messages) akan dibuat bersama tabel tersebut.
#           Lihat Blueprint Appendix E untuk daftar lengkap.
#
#           Migration ini berfungsi sebagai PENANDA bahwa Fase 0 selesai
#           dan seluruh index foundation sudah terpasang.
#
# Revision: 022
# Fase    : Fase 0
# Ref     : Blueprint Appendix D, Appendix E
# ═════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

revision: str = "022"
down_revision: str | None = "017"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Tidak ada DDL — semua index Fase 0 sudah dibuat di migration individu.
    # File ini adalah penanda selesainya Fase 0 index phase.
    # Lihat komentar di header file untuk daftar lengkap index yang sudah ada.
    pass


def downgrade() -> None:
    # Tidak ada DDL — nothing to reverse.
    pass

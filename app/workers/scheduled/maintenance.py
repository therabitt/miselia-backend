# ═══════════════════════════════════════════════════════════════════════════
# File    : app/workers/scheduled/maintenance.py
# Desc    : Scheduled tasks untuk database dan storage maintenance.
#           SKELETON — implementasi di Fase 2–5.
#
#           Tasks:
#             cleanup_expired_library_papers() — daily 02:00 WIB
#               Hard delete LibraryPaper Free tier yang expired > 90 hari
#               (is_visible=false dan expired_at > 90 hari lalu)
#               Ref: Blueprint §2.2, Decision #2
#
#             create_monthly_partition()       — tgl 1, 00:05 WIB
#               Buat partisi analytics_events bulan berikutnya
#               KRITIS: query FAIL tanpa partisi matching (Blueprint §6.15)
#               Ref: Blueprint §6.15, §2.2
#
#             cleanup_expired_chat_sessions()  — schedule TBD
#               Hapus ChatSession Free tier yang sudah tidak aktif
#               Ref: Blueprint §2.2
#
#             mark_stale_stage_cards()         — schedule TBD
#               Update staleness flag di stage_runs (Decision #22)
#               Ref: Blueprint §2.2, Decision #22
#
#             archive_old_analytics_events()   — schedule TBD
#               Event > 90 hari di-archive atau di-aggregate
#               Ref: Blueprint §2.2
#
# Layer   : Workers / Scheduled
# Step    : STEP 7 (skeleton) → Fase 2–5 (implementasi)
# Ref     : Blueprint §2.2, Decision #2, §6.15
# ═══════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from app.core.logging import get_logger
from app.workers.celery_app import celery_app

log = get_logger(__name__)


@celery_app.task(name="app.workers.scheduled.maintenance.cleanup_expired_library_papers")
def cleanup_expired_library_papers() -> None:
    """
    Hard delete LibraryPaper Free tier: expired_at > 90 hari, is_visible=False.
    Schedule: 19:00 UTC (02:00 WIB) — Blueprint §2.2
    TODO Fase 2: Implementasi setelah library_papers tabel aktif.
    """
    log.info("cleanup_expired_library_papers placeholder")


@celery_app.task(name="app.workers.scheduled.maintenance.create_monthly_partition")
def create_monthly_partition() -> None:
    """
    Buat partisi analytics_events untuk bulan berikutnya.
    Schedule: 17:05 UTC tanggal 1 (00:05 WIB) — Blueprint §6.15
    KRITIS: analytics_events INSERT FAIL tanpa partisi yang sesuai.
    TODO Fase 0 / Fase 1: Implementasi segera — partisi Fase 0 sudah dibuat
    di migration 016, job ini akan membuat partisi bulan berikutnya.
    """
    log.info("create_monthly_partition placeholder")


@celery_app.task(name="app.workers.scheduled.maintenance.cleanup_expired_chat_sessions")
def cleanup_expired_chat_sessions() -> None:
    """
    Hapus ChatSession Free tier yang tidak aktif.
    Schedule: TBD — Blueprint §2.2
    TODO Fase 5: Implementasi setelah chat_sessions tabel aktif.
    """
    log.info("cleanup_expired_chat_sessions placeholder")


@celery_app.task(name="app.workers.scheduled.maintenance.mark_stale_stage_cards")
def mark_stale_stage_cards() -> None:
    """
    Update staleness flag di stage_runs untuk UI badge ⚠️ (Decision #22).
    Schedule: TBD — Blueprint §2.2
    TODO Fase 3: Implementasi setelah pipeline executor berjalan.
    """
    log.info("mark_stale_stage_cards placeholder")


@celery_app.task(name="app.workers.scheduled.maintenance.archive_old_analytics_events")
def archive_old_analytics_events() -> None:
    """
    Archive atau aggregate analytics_events > 90 hari.
    Schedule: TBD — Blueprint §2.2
    TODO Fase 5–6: Implementasi setelah analytics volume signifikan.
    """
    log.info("archive_old_analytics_events placeholder")

# ═══════════════════════════════════════════════════════════════════════════
# File    : app/workers/scheduled/maintenance.py
# Desc    : Scheduled tasks untuk database dan storage maintenance.
#
#           Tasks yang sudah diimplementasi (Fase 2):
#             cleanup_expired_library_papers() — daily 02:00 WIB (19:00 UTC)
#               Phase 1: Soft delete — is_visible=FALSE untuk paper yang
#                         melewati expires_at (masih is_visible=TRUE)
#               Phase 2: Hard delete — hapus permanen paper yang sudah
#                         90 hari sejak expired_at (bisa restore window habis)
#               Dua transaksi terpisah: Phase 1 tidak tergantung Phase 2.
#               Ref: Blueprint §12.3, Decision #2
#
#           Tasks skeleton (implementasi fase berikutnya):
#             create_monthly_partition()       — tgl 1, 00:05 WIB
#               KRITIS: analytics_events INSERT FAIL tanpa partisi matching
#               Ref: Blueprint §6.15
#
#             cleanup_expired_chat_sessions()  — schedule TBD
#               Hapus ChatSession Free tier yang tidak aktif
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
#           Pattern Celery + async SQLAlchemy (GAP 1 resolution):
#             Celery tasks sync → asyncio.run(_inner_async())
#             _inner_async(): gunakan AsyncSessionLocal() standalone
#             tanpa FastAPI Depends context.
#
# Layer   : Workers / Scheduled
# Step    : STEP 5 — Fase 2 (cleanup_expired_library_papers)
#           STEP 7 (Fase 1 skeleton) → Fase 3–5 (tasks lainnya)
# Ref     : Blueprint §12.3, §2.2, Decision #2, §6.15
# ═══════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, delete, update

from app.core.logging import get_logger
from app.dependencies import AsyncSessionLocal
from app.models.database import LibraryPaper
from app.workers.celery_app import celery_app

log = get_logger(__name__)

# ── Konstanta ─────────────────────────────────────────────────────────────

_HARD_DELETE_WINDOW_DAYS = 90  # Decision #2: window restore 90 hari sejak expired_at


# ── cleanup_expired_library_papers ────────────────────────────────────────


@celery_app.task(name="app.workers.scheduled.maintenance.cleanup_expired_library_papers")
def cleanup_expired_library_papers() -> None:
    """
    Daily maintenance job: 02:00 WIB (19:00 UTC). Dua fase:

    Phase 1 — Soft delete:
        SET is_visible=FALSE, expired_at=NOW(), updated_at=NOW()
        WHERE is_visible=TRUE AND expires_at IS NOT NULL AND expires_at < NOW()
        → Menyembunyikan paper yang sudah melewati expires_at dari UI user.

    Phase 2 — Hard delete (permanen):
        DELETE FROM library_papers
        WHERE is_visible=FALSE AND expired_at IS NOT NULL
        AND expired_at < NOW() - 90 hari
        → Menghapus row yang sudah di luar window restore 90 hari.

    Dua transaksi terpisah — kegagalan Phase 2 tidak membatalkan Phase 1.

    Ref: Blueprint §12.3, Decision #2
    Schedule: crontab(hour='19', minute='0') di celery_app.py (= 02:00 WIB)
    """
    asyncio.run(_cleanup_expired_library_papers_async())


async def _cleanup_expired_library_papers_async() -> None:
    """
    Implementasi async dari cleanup_expired_library_papers.
    Dipanggil oleh asyncio.run() dari Celery task.
    """
    now = datetime.now(UTC)
    hard_delete_cutoff = now - timedelta(days=_HARD_DELETE_WINDOW_DAYS)

    # ── Phase 1: Soft delete ──────────────────────────────────────────────
    # Paper yang melewati expires_at tapi masih is_visible=TRUE
    # → Disembunyikan dari UI (is_visible=FALSE)
    # → expired_at di-set ke NOW() untuk mulai hitung window 90 hari restore
    soft_deleted_count = 0
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                update(LibraryPaper)
                .where(
                    and_(
                        LibraryPaper.is_visible.is_(True),
                        LibraryPaper.expires_at.isnot(None),
                        LibraryPaper.expires_at < now,
                    )
                )
                .values(
                    is_visible=False,
                    expired_at=now,
                )
                .execution_options(synchronize_session=False)
            )
            await db.commit()
            soft_deleted_count = result.rowcount

        log.info(
            "cleanup_expired_library_papers: phase 1 complete",
            soft_deleted=soft_deleted_count,
            now_utc=now.isoformat(),
        )
    except Exception:
        log.exception("cleanup_expired_library_papers: phase 1 FAILED")
        # Lanjut ke Phase 2 meski Phase 1 gagal — tidak perlu abort

    # ── Phase 2: Hard delete ──────────────────────────────────────────────
    # Paper yang is_visible=FALSE DAN expired_at > 90 hari lalu
    # → Dihapus permanen dari database
    # → User sudah tidak bisa restore meski upgrade setelah 90 hari
    hard_deleted_count = 0
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                delete(LibraryPaper)
                .where(
                    and_(
                        LibraryPaper.is_visible.is_(False),
                        LibraryPaper.expired_at.isnot(None),
                        LibraryPaper.expired_at < hard_delete_cutoff,
                    )
                )
                .execution_options(synchronize_session=False)
            )
            await db.commit()
            hard_deleted_count = result.rowcount

        log.info(
            "cleanup_expired_library_papers: phase 2 complete",
            hard_deleted=hard_deleted_count,
            cutoff_utc=hard_delete_cutoff.isoformat(),
        )
    except Exception:
        log.exception("cleanup_expired_library_papers: phase 2 FAILED")

    log.info(
        "cleanup_expired_library_papers: finished",
        soft_deleted=soft_deleted_count,
        hard_deleted=hard_deleted_count,
    )


# ── create_monthly_partition ──────────────────────────────────────────────


@celery_app.task(name="app.workers.scheduled.maintenance.create_monthly_partition")
def create_monthly_partition() -> None:
    """
    Buat partisi analytics_events untuk bulan berikutnya.
    Schedule: 17:05 UTC tanggal 1 (00:05 WIB) — Blueprint §6.15
    KRITIS: analytics_events INSERT FAIL tanpa partisi yang sesuai.
    TODO Fase 0 / Fase 1: Implementasi segera — partisi Fase 0 sudah dibuat
    di migration 016, job ini akan membuat partisi bulan berikutnya.
    """
    log.info("create_monthly_partition placeholder — implementasi Fase 3")


# ── cleanup_expired_chat_sessions ─────────────────────────────────────────


@celery_app.task(name="app.workers.scheduled.maintenance.cleanup_expired_chat_sessions")
def cleanup_expired_chat_sessions() -> None:
    """
    Hapus ChatSession Free tier yang tidak aktif.
    Schedule: TBD — Blueprint §2.2
    TODO Fase 5: Implementasi setelah chat_sessions tabel aktif.
    """
    log.info("cleanup_expired_chat_sessions placeholder — implementasi Fase 5")


# ── mark_stale_stage_cards ────────────────────────────────────────────────


@celery_app.task(name="app.workers.scheduled.maintenance.mark_stale_stage_cards")
def mark_stale_stage_cards() -> None:
    """
    Update staleness flag di stage_runs untuk UI badge ⚠️ (Decision #22).
    Schedule: TBD — Blueprint §2.2
    TODO Fase 3: Implementasi setelah pipeline executor berjalan.
    """
    log.info("mark_stale_stage_cards placeholder — implementasi Fase 3")


# ── archive_old_analytics_events ──────────────────────────────────────────


@celery_app.task(name="app.workers.scheduled.maintenance.archive_old_analytics_events")
def archive_old_analytics_events() -> None:
    """
    Archive atau aggregate analytics_events > 90 hari.
    Schedule: TBD — Blueprint §2.2
    TODO Fase 5–6: Implementasi setelah analytics volume signifikan.
    """
    log.info("archive_old_analytics_events placeholder — implementasi Fase 5-6")

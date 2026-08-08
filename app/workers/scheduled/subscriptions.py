# ═══════════════════════════════════════════════════════════════════════════
# File    : app/workers/scheduled/subscriptions.py
# Desc    : Scheduled tasks untuk subscription lifecycle management.
#
#           Tasks yang sudah diimplementasi (Fase 2):
#             notify_library_expiry() — daily 09:00 WIB (02:00 UTC)
#               Query library paper Free tier yang akan expired dalam 7 hari.
#               Fase 2: log structured (placeholder — email via Resend di Fase 3)
#               Fase 3: panggil email_service.send_library_expiry_reminder()
#               Ref: Blueprint §2.2, §12.3, Decision #2
#
#           Tasks skeleton (implementasi Fase 3):
#             process_subscription_expiry()  — */15 * * * * (Decision #1)
#               active → grace_period → expired + downgrade_to_free()
#               Safety buffer 15 menit (Decision #1 [NEW])
#
#             send_renewal_notifications()   — daily 08:00 WIB
#               Kirim email H-7, H-3, H-0, H+1, H+3 (Decision #1)
#               Tidak dikirim ke institutional plan
#
#           Pattern Celery + async SQLAlchemy:
#             Celery tasks sync → asyncio.run(_inner_async())
#             Gunakan AsyncSessionLocal() standalone.
#
# Layer   : Workers / Scheduled
# Step    : STEP 5 — Fase 2 (notify_library_expiry)
#           STEP 7 (Fase 1 skeleton) → Fase 3 (tasks lainnya)
# Ref     : Blueprint §2.2, §12.3, Decision #1, Decision #2, Section 20
# ═══════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, select

from app.core.logging import get_logger
from app.dependencies import AsyncSessionLocal
from app.models.database import LibraryPaper
from app.workers.celery_app import celery_app

log = get_logger(__name__)

# ── Konstanta ─────────────────────────────────────────────────────────────

_EXPIRY_REMINDER_WINDOW_DAYS = 7  # H-7: kirim email 7 hari sebelum expired


# ── notify_library_expiry ─────────────────────────────────────────────────


@celery_app.task(name="app.workers.scheduled.subscriptions.notify_library_expiry")
def notify_library_expiry() -> None:
    """
    Daily job: 09:00 WIB (02:00 UTC).

    Cari library paper Free tier yang akan expired dalam 7 hari ke depan
    dan kirim notifikasi H-7 ke user bersangkutan.

    Fase 2 (saat ini):
        - Query users + papers yang expires dalam 7 hari
        - Log structured sebagai placeholder (email belum aktif)
        - TODO Fase 3: Ganti log dengan email_service.send_library_expiry_reminder()

    Fase 3 (target):
        - Integrasikan dengan email_service.py (Resend API, Blueprint Section 20)
        - Deduplikasi: satu email per user meski punya banyak paper yang akan expired
        - Track notification_sent_at di library_papers untuk mencegah duplikasi

    Logic:
        expires_at >= NOW()
        AND expires_at < NOW() + 7 hari
        AND is_visible = TRUE  (paper masih aktif)

    Ref: Blueprint §2.2, Decision #2, Section 20 (email template library expiry)
    Schedule: crontab(hour='2', minute='0') di celery_app.py (= 09:00 WIB)
    """
    asyncio.run(_notify_library_expiry_async())


async def _notify_library_expiry_async() -> None:
    """
    Implementasi async dari notify_library_expiry.
    Dipanggil oleh asyncio.run() dari Celery task.
    """
    now = datetime.now(UTC)
    window_end = now + timedelta(days=_EXPIRY_REMINDER_WINDOW_DAYS)

    try:
        async with AsyncSessionLocal() as db:
            # Query library papers yang akan expired dalam 7 hari
            # is_visible=TRUE → paper masih aktif (belum soft-deleted)
            # expires_at antara NOW() dan NOW()+7 hari
            result = await db.execute(
                select(LibraryPaper)
                .where(
                    and_(
                        LibraryPaper.is_visible.is_(True),
                        LibraryPaper.expires_at.isnot(None),
                        LibraryPaper.expires_at >= now,
                        LibraryPaper.expires_at < window_end,
                    )
                )
                .order_by(LibraryPaper.user_id, LibraryPaper.expires_at)
            )
            papers = result.scalars().all()

        if not papers:
            log.info(
                "notify_library_expiry: no papers expiring in 7 days",
                window_start_utc=now.isoformat(),
                window_end_utc=window_end.isoformat(),
            )
            return

        # Group papers per user untuk deduplikasi notifikasi
        # (satu notifikasi per user, meski punya banyak paper yang akan expired)
        user_papers: dict[str, list[LibraryPaper]] = {}
        for paper in papers:
            uid = str(paper.user_id)
            if uid not in user_papers:
                user_papers[uid] = []
            user_papers[uid].append(paper)

        notified_count = 0
        for user_id, user_paper_list in user_papers.items():
            min_expires_at = min(p.expires_at for p in user_paper_list)

            # TODO Fase 3: Ganti log di bawah dengan:
            #   await email_service.send_library_expiry_reminder(
            #       user_id=user_id,
            #       paper_count=len(user_paper_list),
            #       earliest_expires_at=min_expires_at,
            #   )
            # Ref: Blueprint Section 20 — email template library expiry H-7

            log.info(
                "notify_library_expiry: [PLACEHOLDER] would send H-7 email",
                user_id=user_id,
                paper_count=len(user_paper_list),
                earliest_expires_at=min_expires_at.isoformat() if min_expires_at else None,
            )
            notified_count += 1

        log.info(
            "notify_library_expiry: finished",
            papers_expiring=len(papers),
            users_to_notify=notified_count,
            window_days=_EXPIRY_REMINDER_WINDOW_DAYS,
        )

    except Exception:
        log.exception("notify_library_expiry: FAILED")


# ── process_subscription_expiry ───────────────────────────────────────────


@celery_app.task(name="app.workers.scheduled.subscriptions.process_subscription_expiry")
def process_subscription_expiry() -> None:
    """
    Cek dan proses subscription yang sudah melewati current_period_end.
    Schedule: */15 * * * * — Decision #1
    Safety buffer 15 menit antara cron dan action (Decision #1 [NEW]).
    TODO Fase 3: Implementasi idempotent UPDATE query + downgrade_to_free().
    """
    log.info("process_subscription_expiry placeholder — implementasi Fase 3")


# ── send_renewal_notifications ────────────────────────────────────────────


@celery_app.task(name="app.workers.scheduled.subscriptions.send_renewal_notifications")
def send_renewal_notifications() -> None:
    """
    Kirim email renewal reminder H-7, H-3, H-0, H+1, H+3.
    Schedule: 0 1 * * * (08:00 WIB) — Decision #1, Section 20
    TODO Fase 3: Implementasi query + Resend email via email_service.py.
    """
    log.info("send_renewal_notifications placeholder — implementasi Fase 3")

# ═══════════════════════════════════════════════════════════════════════════
# File    : app/workers/scheduled/subscriptions.py
# Desc    : Scheduled tasks untuk subscription lifecycle management.
#           SKELETON — implementasi di Fase 3.
#
#           Tasks:
#             process_subscription_expiry()  — */15 * * * * (Decision #1)
#               active → grace_period (saat current_period_end tercapai)
#               grace_period → expired (3 hari setelah period_end)
#               Trigger downgrade_to_free() saat expired
#               Safety buffer 15 menit (Decision #1 [NEW])
#
#             send_renewal_notifications()   — daily 08:00 WIB
#               Kirim email H-7, H-3, H-0, H+1, H+3 (Decision #1)
#               Tidak dikirim ke institutional plan
#
#             notify_library_expiry()        — daily 09:00 WIB
#               Kirim email H-7 sebelum library paper Free tier expired
#               Job: notify_library_expiry (Blueprint §2.2)
#
# Layer   : Workers / Scheduled
# Step    : STEP 7 (skeleton) → Fase 3 (implementasi)
# Ref     : Blueprint §2.2, Decision #1, Section 20 (email templates)
# ═══════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from app.core.logging import get_logger
from app.workers.celery_app import celery_app

log = get_logger(__name__)


@celery_app.task(name="app.workers.scheduled.subscriptions.process_subscription_expiry")
def process_subscription_expiry() -> None:
    """
    Cek dan proses subscription yang sudah melewati current_period_end.
    Schedule: */15 * * * * — Decision #1
    TODO Fase 3: Implementasi idempotent UPDATE query + downgrade_to_free().
    """
    log.info("process_subscription_expiry placeholder")


@celery_app.task(name="app.workers.scheduled.subscriptions.send_renewal_notifications")
def send_renewal_notifications() -> None:
    """
    Kirim email renewal reminder H-7, H-3, H-0, H+1, H+3.
    Schedule: 0 1 * * * (08:00 WIB) — Decision #1, Section 20
    TODO Fase 3: Implementasi query + Resend email via email_service.py.
    """
    log.info("send_renewal_notifications placeholder")


@celery_app.task(name="app.workers.scheduled.subscriptions.notify_library_expiry")
def notify_library_expiry() -> None:
    """
    Kirim email H-7 sebelum library paper Free tier expired.
    Schedule: 0 2 * * * (09:00 WIB) — Blueprint §2.2
    TODO Fase 2: Implementasi setelah library_papers tabel aktif.
    """
    log.info("notify_library_expiry placeholder")

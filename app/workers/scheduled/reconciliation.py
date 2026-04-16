# ═══════════════════════════════════════════════════════════════════════════
# File    : app/workers/scheduled/reconciliation.py
# Desc    : Scheduled tasks untuk reconciliation dan cleanup.
#           SKELETON — implementasi di Fase 3–4.
#
#           Tasks:
#             cleanup_orphaned_stage_runs()  — */30 * * * *
#               Tandai stage_run status='running' dengan updated_at > 10 menit
#               sebagai 'failed' dengan error_message='Task timeout/crash'
#               Ref: Blueprint §2.2 (Orphaned task recovery)
#
#             check_pending_payments()       — 0 */2 * * *
#               Verifikasi ulang payment dengan status pending > 1 jam
#               via Midtrans Get Status API
#
# Layer   : Workers / Scheduled
# Step    : STEP 7 (skeleton) → Fase 3–4 (implementasi)
# Ref     : Blueprint §2.2, Decision #1
# ═══════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from app.core.logging import get_logger
from app.workers.celery_app import celery_app

log = get_logger(__name__)


@celery_app.task(name="app.workers.scheduled.reconciliation.cleanup_orphaned_stage_runs")
def cleanup_orphaned_stage_runs() -> None:
    """
    Cleanup stage_run yang running > 10 menit → set failed.
    Schedule: */30 * * * * — Blueprint §2.2
    TODO Fase 4: Implementasi UPDATE query dengan threshold 10 menit.
    """
    log.info("cleanup_orphaned_stage_runs placeholder")


@celery_app.task(name="app.workers.scheduled.reconciliation.check_pending_payments")
def check_pending_payments() -> None:
    """
    Verifikasi ulang payment status='pending' > 1 jam via Midtrans API.
    Schedule: 0 */2 * * * — Blueprint §2.2
    TODO Fase 3: Implementasi Midtrans Get Status call + reconcile.
    """
    log.info("check_pending_payments placeholder")

# ═══════════════════════════════════════════════════════════════════════════
# File    : app/workers/scheduled/prompt_report.py
# Desc    : Scheduled tasks untuk prompt performance reporting.
#           SKELETON — implementasi di Fase 4.
#
#           Tasks:
#             weekly_prompt_performance_report() — Minggu 02:00 WIB
#               QA score per prompt, token usage, output quality metrics
#               Ref: Blueprint §2.2 prompt_report.py
#
# Layer   : Workers / Scheduled
# Step    : STEP 7 (skeleton) → Fase 4 (implementasi)
# Ref     : Blueprint §2.2
# ═══════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from app.core.logging import get_logger
from app.workers.celery_app import celery_app

log = get_logger(__name__)


@celery_app.task(name="app.workers.scheduled.prompt_report.weekly_prompt_performance_report")
def weekly_prompt_performance_report() -> None:
    """
    Laporan performa prompt mingguan: QA score, token usage, quality metrics.
    Schedule: 19:00 UTC Sabtu (02:00 WIB Minggu) — Blueprint §2.2
    TODO Fase 4: Implementasi setelah pipeline executor berjalan.
    """
    log.info("weekly_prompt_performance_report placeholder")

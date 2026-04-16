# ═══════════════════════════════════════════════════════════════════════════
# File    : app/workers/tasks.py
# Desc    : Celery task definitions — dispatch pipeline runs P1–P8.
#           SKELETON — implementasi pipeline executor di Fase 3–4.
#
#           Setiap pipeline task:
#             - Mengambil stage_run dari DB
#             - Mengupdate status: queued → running → completed/failed
#             - Dispatch ke pipeline class yang sesuai
#           Ref: Blueprint §2.2 tasks.py, §9.x pipeline specs
#
# Layer   : Workers / Tasks
# Step    : STEP 7 (skeleton) → Fase 3–4 (implementasi)
# Ref     : Blueprint §2.2, §9.x, Decision #23 (AI fallback)
# ═══════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from app.core.logging import get_logger
from app.workers.celery_app import celery_app

log = get_logger(__name__)

# ── Pipeline tasks — implementasi di Fase 3–4 ─────────────────────────────

@celery_app.task(
    name="app.workers.tasks.run_literature_review",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    soft_time_limit=300,
    time_limit=360,
)
def run_literature_review(self: object, stage_run_id: str) -> None:
    """P1: Literature Review pipeline executor. TODO Fase 3."""
    log.info("run_literature_review placeholder", stage_run_id=stage_run_id)


@celery_app.task(
    name="app.workers.tasks.run_research_gap",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    soft_time_limit=300,
    time_limit=360,
)
def run_research_gap(self: object, stage_run_id: str) -> None:
    """P2: Research Gap & Novelty pipeline executor. TODO Fase 3."""
    log.info("run_research_gap placeholder", stage_run_id=stage_run_id)


@celery_app.task(
    name="app.workers.tasks.run_methodology",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    soft_time_limit=300,
    time_limit=360,
)
def run_methodology(self: object, stage_run_id: str) -> None:
    """P3: Methodology Advisor pipeline executor. TODO Fase 6A."""
    log.info("run_methodology placeholder", stage_run_id=stage_run_id)


@celery_app.task(
    name="app.workers.tasks.run_hypothesis",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    soft_time_limit=300,
    time_limit=360,
)
def run_hypothesis(self: object, stage_run_id: str) -> None:
    """P4: Hypothesis/Proposisi pipeline executor (dual mode). TODO Fase 6A."""
    log.info("run_hypothesis placeholder", stage_run_id=stage_run_id)


@celery_app.task(
    name="app.workers.tasks.run_chapter_outline",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    soft_time_limit=300,
    time_limit=360,
)
def run_chapter_outline(self: object, stage_run_id: str) -> None:
    """P5: Chapter Outline pipeline executor. TODO Fase 6A."""
    log.info("run_chapter_outline placeholder", stage_run_id=stage_run_id)


@celery_app.task(
    name="app.workers.tasks.run_bab1_writer",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    soft_time_limit=300,
    time_limit=360,
)
def run_bab1_writer(self: object, stage_run_id: str) -> None:
    """P6: Bab 1 Writer pipeline executor. TODO Fase Tier B."""
    log.info("run_bab1_writer placeholder", stage_run_id=stage_run_id)


@celery_app.task(
    name="app.workers.tasks.run_systematic_review",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    soft_time_limit=300,
    time_limit=360,
    queue="pipeline_heavy",  # Queue terpisah — Blueprint §18.4
)
def run_systematic_review(self: object, stage_run_id: str) -> None:
    """P7: SLR (Magister only) pipeline executor. TODO Fase Tier B. Queue: pipeline_heavy."""
    log.info("run_systematic_review placeholder", stage_run_id=stage_run_id)


@celery_app.task(
    name="app.workers.tasks.run_sidang_prep",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    soft_time_limit=300,
    time_limit=360,
)
def run_sidang_prep(self: object, stage_run_id: str) -> None:
    """P8: Sidang Preparation pipeline executor. TODO Fase Tier B."""
    log.info("run_sidang_prep placeholder", stage_run_id=stage_run_id)


@celery_app.task(
    name="app.workers.tasks.process_chat_message",
    bind=True,
    max_retries=1,
    default_retry_delay=5,
    soft_time_limit=60,
    time_limit=90,
    queue="chat_realtime",
)
def process_chat_message(self: object, session_id: str, message_id: str) -> None:
    """Chat with Papers message processor. TODO Fase 5."""
    log.info("process_chat_message placeholder", session_id=session_id)

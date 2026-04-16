# ═══════════════════════════════════════════════════════════════════════════
# File    : app/workers/celery_app.py
# Desc    : Celery application instance — broker Redis, result backend Redis.
#           Beat schedule lengkap sesuai Blueprint §2.2 dan Decision #1.
#           Queue routing sesuai Blueprint §18.4.
#
#           Cron schedule (semua dalam UTC, WIB = UTC+7):
#             process_subscription_expiry : */15 * * * *   (Decision #1)
#             send_renewal_notifications  : 0 1 * * *      (08:00 WIB)
#             notify_library_expiry       : 0 2 * * *      (09:00 WIB)
#             hard_delete_expired_papers  : 19 19 * * *    (02:00 WIB)
#             cleanup_orphaned_stage_runs : */30 * * * *   (setiap 30 menit)
#             create_monthly_partition    : 5 17 1 * *     (00:05 WIB, tgl 1)
#             check_pending_payments      : 0 */2 * * *    (setiap 2 jam)
#             daily_intelligence          : 30 18 * * *    (01:30 WIB)
#             weekly_prompt_report        : 0 19 * * 0     (02:00 WIB, Minggu)
#
# Layer   : Workers / Celery
# Deps    : celery, redis, app.config
# Step    : STEP 7 — Health Check & Celery Skeleton
# Ref     : Blueprint §2.2, §18.4, Decision #1, §6.15 (create_monthly_partition)
# ═══════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab
from kombu import Exchange, Queue

from app.config import settings

# ── Celery instance ───────────────────────────────────────────────────────

celery_app = Celery(
    "miselia",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.workers.tasks",
        "app.workers.scheduled.subscriptions",
        "app.workers.scheduled.reconciliation",
        "app.workers.scheduled.intelligence",
        "app.workers.scheduled.prompt_report",
        "app.workers.scheduled.citation_review",
        "app.workers.scheduled.maintenance",
    ],
)

# ── Konfigurasi ───────────────────────────────────────────────────────────

celery_app.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,

    # Task behavior
    task_acks_late=True,           # Ack setelah task selesai, bukan saat diterima
    task_reject_on_worker_lost=True,  # Re-queue jika worker crash saat proses
    task_soft_time_limit=300,      # 5 menit — SoftTimeLimitExceeded
    task_time_limit=360,           # 6 menit — force kill (Blueprint §2.2 base.py)
    worker_prefetch_multiplier=1,  # 1 task per worker untuk menghindari starvation

    # Result backend
    result_expires=3600,           # Hasil task expired setelah 1 jam

    # Broker
    broker_connection_retry_on_startup=True,
    broker_transport_options={
        "visibility_timeout": 43200,  # 12 jam
    },
)

# ── Queue definitions — Blueprint §18.4 ──────────────────────────────────

default_exchange = Exchange("default", type="direct")

celery_app.conf.task_queues = (
    # Pipeline tasks — P1–P6, P8 (normal priority)
    Queue("pipeline_normal", default_exchange, routing_key="pipeline_normal"),
    # P7 SLR — queue terpisah agar tidak memblokir pipeline lain (Blueprint §18.4)
    Queue("pipeline_heavy", default_exchange, routing_key="pipeline_heavy"),
    # Chat — latency-sensitive, prioritas tinggi
    Queue("chat_realtime", default_exchange, routing_key="chat_realtime"),
    # Maintenance jobs — low priority, single worker
    Queue("maintenance", default_exchange, routing_key="maintenance"),
)

celery_app.conf.task_default_queue = "pipeline_normal"
celery_app.conf.task_default_exchange = "default"
celery_app.conf.task_default_routing_key = "pipeline_normal"

# ── Task routing — Blueprint §18.4 ───────────────────────────────────────

celery_app.conf.task_routes = {
    # P7 SLR — queue terpisah
    "app.workers.tasks.run_systematic_review":       {"queue": "pipeline_heavy"},
    # P1–P6, P8 — queue normal
    "app.workers.tasks.run_literature_review":       {"queue": "pipeline_normal"},
    "app.workers.tasks.run_research_gap":            {"queue": "pipeline_normal"},
    "app.workers.tasks.run_methodology":             {"queue": "pipeline_normal"},
    "app.workers.tasks.run_hypothesis":              {"queue": "pipeline_normal"},
    "app.workers.tasks.run_chapter_outline":         {"queue": "pipeline_normal"},
    "app.workers.tasks.run_bab1_writer":             {"queue": "pipeline_normal"},
    "app.workers.tasks.run_sidang_prep":             {"queue": "pipeline_normal"},
    # Chat — queue realtime
    "app.workers.tasks.process_chat_message":        {"queue": "chat_realtime"},
    # Scheduled jobs — maintenance queue
    "app.workers.scheduled.subscriptions.*":         {"queue": "maintenance"},
    "app.workers.scheduled.reconciliation.*":        {"queue": "maintenance"},
    "app.workers.scheduled.intelligence.*":          {"queue": "maintenance"},
    "app.workers.scheduled.prompt_report.*":         {"queue": "maintenance"},
    "app.workers.scheduled.citation_review.*":       {"queue": "maintenance"},
    "app.workers.scheduled.maintenance.*":           {"queue": "maintenance"},
}

# ── Beat Schedule — Semua scheduled jobs ─────────────────────────────────
# Semua waktu dalam UTC (WIB = UTC+7, jadi WIB jam X = UTC jam X-7)

celery_app.conf.beat_schedule = {
    # ── Subscription lifecycle — Decision #1 ─────────────────────────────
    # Setiap 15 menit — cek active → grace_period transition
    "process-subscription-expiry": {
        "task": "app.workers.scheduled.subscriptions.process_subscription_expiry",
        "schedule": crontab(minute="*/15"),
        "options": {"queue": "maintenance"},
    },
    # Daily 08:00 WIB (01:00 UTC) — kirim email H-7, H-3, H-0, H+1, H+3
    "send-renewal-notifications": {
        "task": "app.workers.scheduled.subscriptions.send_renewal_notifications",
        "schedule": crontab(hour=1, minute=0),
        "options": {"queue": "maintenance"},
    },
    # Daily 09:00 WIB (02:00 UTC) — kirim email H-7 sebelum library paper Free expired
    "notify-library-expiry": {
        "task": "app.workers.scheduled.subscriptions.notify_library_expiry",
        "schedule": crontab(hour=2, minute=0),
        "options": {"queue": "maintenance"},
    },

    # ── Reconciliation & Cleanup ──────────────────────────────────────────
    # Setiap 30 menit — cleanup stage_runs status='running' > 10 menit
    "cleanup-orphaned-stage-runs": {
        "task": "app.workers.scheduled.reconciliation.cleanup_orphaned_stage_runs",
        "schedule": crontab(minute="*/30"),
        "options": {"queue": "maintenance"},
    },
    # Setiap 2 jam — verifikasi ulang payment pending > 1 jam
    "check-pending-payments": {
        "task": "app.workers.scheduled.reconciliation.check_pending_payments",
        "schedule": crontab(minute=0, hour="*/2"),
        "options": {"queue": "maintenance"},
    },

    # ── Library Maintenance ───────────────────────────────────────────────
    # Daily 02:00 WIB (19:00 UTC hari sebelumnya) — hard delete paper expired > 90 hari
    # Ref: Blueprint §2.2 maintenance.py (cleanup_expired_library_papers)
    "hard-delete-expired-papers": {
        "task": "app.workers.scheduled.maintenance.cleanup_expired_library_papers",
        "schedule": crontab(hour=19, minute=0),
        "options": {"queue": "maintenance"},
    },

    # ── Analytics & Partitions ────────────────────────────────────────────
    # Setiap tanggal 1 pukul 00:05 WIB (17:05 UTC, hari sebelumnya) — buat partisi bulan baru
    # KRITIS: analytics_events query FAIL jika tidak ada partisi matching (Blueprint §6.15)
    "create-monthly-partition": {
        "task": "app.workers.scheduled.maintenance.create_monthly_partition",
        "schedule": crontab(hour=17, minute=5, day_of_month=1),
        "options": {"queue": "maintenance"},
    },

    # ── Intelligence & Reporting ──────────────────────────────────────────
    # Daily 01:30 WIB (18:30 UTC hari sebelumnya) — agregasi metrics harian
    "daily-intelligence-aggregation": {
        "task": "app.workers.scheduled.intelligence.daily_intelligence_aggregation",
        "schedule": crontab(hour=18, minute=30),
        "options": {"queue": "maintenance"},
    },
    # Setiap Minggu 02:00 WIB (Minggu, 19:00 UTC Sabtu) — laporan performa prompt
    "weekly-prompt-report": {
        "task": "app.workers.scheduled.prompt_report.weekly_prompt_performance_report",
        "schedule": crontab(hour=19, minute=0, day_of_week=6),  # 6 = Sabtu UTC = Minggu WIB
        "options": {"queue": "maintenance"},
    },
}

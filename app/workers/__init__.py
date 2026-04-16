# ═══════════════════════════════════════════════════════════════════════════
# File    : app/workers/__init__.py
# Desc    : Workers package init — ekspos celery_app untuk digunakan
#           oleh Celery CLI: celery -A app.workers worker
# Layer   : Workers
# Step    : STEP 7 — Health Check & Celery Skeleton
# Ref     : Blueprint §2.2
# ═══════════════════════════════════════════════════════════════════════════

from app.workers.celery_app import celery_app

__all__ = ["celery_app"]

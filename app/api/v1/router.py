# ═══════════════════════════════════════════════════════════════════════════
# File    : app/api/v1/router.py
# Desc    : Master router v1 — include semua sub-router dengan prefix /api/v1.
#           Sub-router masih skeleton di STEP 3, endpoint diisi di STEP berikutnya.
# Layer   : API / Router
# Step    : STEP 3 — Backend Setup
# Ref     : Blueprint §2.2
# ═══════════════════════════════════════════════════════════════════════════

from fastapi import APIRouter

from app.api.v1 import (
    admin,
    auth,
    chat,
    find_papers,
    health,
    institutional,
    library,
    payments,
    projects,
    stage_outputs,
    stage_runs,
    subscriptions,
    users,
)

api_router = APIRouter()

api_router.include_router(health.router,        prefix="/health",        tags=["health"])
api_router.include_router(auth.router,          prefix="/auth",          tags=["auth"])
api_router.include_router(users.router,         prefix="/users",         tags=["users"])
api_router.include_router(projects.router,      prefix="/projects",      tags=["projects"])
api_router.include_router(stage_runs.router,    prefix="/stage-runs",    tags=["stage-runs"])
api_router.include_router(stage_outputs.router, prefix="/stage-outputs", tags=["stage-outputs"])
api_router.include_router(find_papers.router,   prefix="/find-papers",   tags=["find-papers"])
api_router.include_router(library.router,       prefix="/library",       tags=["library"])
api_router.include_router(chat.router,          prefix="/chat",          tags=["chat"])
api_router.include_router(subscriptions.router, prefix="/subscriptions", tags=["subscriptions"])
api_router.include_router(payments.router,      prefix="/payments",      tags=["payments"])
api_router.include_router(institutional.router, prefix="/institutional",  tags=["institutional"])
api_router.include_router(admin.router,         prefix="/admin",         tags=["admin"])

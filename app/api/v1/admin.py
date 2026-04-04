# ═══════════════════════════════════════════════════════════════════════════
# File    : app/api/v1/admin.py
# Desc    : Admin endpoints — stats + subscription management.
#           Guard: is_admin=True + IP whitelist.
#           SKELETON — implementasi di Fase 5.
# Layer   : API / Admin
# Step    : STEP 3 (skeleton)
# Ref     : Blueprint §2.2
# ═══════════════════════════════════════════════════════════════════════════

from fastapi import APIRouter

router = APIRouter()

# TODO Fase 5: GET /admin/stats, GET /admin/subscriptions

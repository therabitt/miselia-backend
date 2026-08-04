# ═══════════════════════════════════════════════════════════════════════════
# File    : app/api/v1/auth.py
# Desc    : Auth endpoints — POST /api/v1/auth/verify.
#
#           POST /auth/verify:
#             Menerima Bearer JWT dari frontend (Supabase Auth).
#             Verifikasi JWT via JWKS → upsert user di DB → return profil user.
#             Dipanggil setiap kali frontend mendapatkan session baru dari Supabase.
#             Idempotent: aman dipanggil berulang kali untuk user yang sama.
#
#           Response berisi:
#             - user: profil lengkap (id, email, onboarding_step, dll)
#             - is_new_user: True jika baru pertama kali login
#
#           Tidak ada rate limit di endpoint ini karena:
#             - Hanya bisa dipanggil dengan JWT valid (Supabase sudah rate-limit auth)
#             - JWT verification sendiri sudah berbiaya komputasi (JWKS ECDSA verify)
#
# Layer   : API / Auth
# Deps    : fastapi, app.dependencies, app.services.user_service, app.models.schemas
# Step    : STEP 2 — Fase 2
# Ref     : Blueprint §2.2, §3.1, §11.15
# ═══════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import uuid as _uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import extract_token_from_header, verify_jwt
from app.core.exceptions import UnauthorizedError
from app.core.logging import get_logger
from app.dependencies import get_db
from app.models.database import User
from app.models.schemas import AuthVerifyResponse
from app.services import user_service

log = get_logger(__name__)
router = APIRouter()


@router.post(
    "/verify",
    response_model=AuthVerifyResponse,
    summary="Verify JWT dan upsert user",
    description=(
        "Verifikasi Bearer JWT dari Supabase Auth. "
        "Jika user belum ada di DB: buat user baru + UserPreferences default. "
        "Return profil user + flag is_new_user untuk menentukan redirect."
    ),
)
async def auth_verify(
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> AuthVerifyResponse:
    """
    POST /api/v1/auth/verify

    Flow:
      1. Ekstrak dan verifikasi Bearer JWT.
      2. upsert_user_from_jwt() → INSERT baru atau GET existing.
      3. Return user profile + is_new_user flag.

    Frontend menggunakan is_new_user + onboarding_step untuk routing:
      - is_new_user=True OR onboarding_step < 4 → redirect ke /onboarding
      - onboarding_step = 4 → redirect ke /dashboard
    """
    token = extract_token_from_header(authorization)
    if not token:
        raise UnauthorizedError(message="Authorization header tidak ditemukan.")

    # Verifikasi JWT via JWKS (cached, TTL 1 jam)
    claims = await verify_jwt(token)

    # Simpan state sebelum upsert untuk deteksi is_new_user
    supabase_id = claims.get("sub")

    existing_check = await db.execute(
        select(User.id).where(User.supabase_id == _uuid.UUID(supabase_id))
    )
    was_existing = existing_check.scalar_one_or_none() is not None

    # Upsert user (idempotent)
    user = await user_service.upsert_user_from_jwt(claims, db)

    is_new_user = not was_existing

    log.info(
        "auth_verify called",
        user_id=str(user.id),
        is_new_user=is_new_user,
        onboarding_step=user.onboarding_step,
    )

    return AuthVerifyResponse(
        user_id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        university=user.university,
        field_of_study=user.field_of_study,
        education_level=user.education_level,
        email_verified=user.email_verified,
        onboarding_step=user.onboarding_step,
        is_new_user=is_new_user,
    )

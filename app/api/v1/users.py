# ═══════════════════════════════════════════════════════════════════════════
# File    : app/api/v1/users.py
# Desc    : User endpoints — profil, onboarding, universitas, preferences.
#
#           Endpoints:
#             GET  /users/me               — profil user terautentikasi
#             PATCH /users/me              — update profil + onboarding step
#             GET  /users/universities     — daftar universitas (untuk autocomplete)
#             GET  /users/preferences      — preferensi user (citation style, dll)
#             PATCH /users/preferences     — update preferensi
#
#           Semua endpoint memerlukan autentikasi (Bearer JWT).
#           GET /users/universities tidak perlu auth (public read).
#
#           Rate limiting:
#             PATCH /users/me: 30 req/jam per user (mencegah spam onboarding update)
#             Endpoint lain: tidak ada rate limit (read-only atau low frequency)
#
# Layer   : API / Users
# Deps    : fastapi, app.dependencies, app.services.user_service, app.models.schemas
# Step    : STEP 2 — Fase 2
# Ref     : Blueprint §2.2, §6.1, §6.11, §11.15
# ═══════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.rate_limit import check_rate_limit
from app.dependencies import get_current_user, get_db
from app.models.schemas import (
    UniversityListResponse,
    UserPreferencesResponse,
    UserPreferencesUpdate,
    UserProfileResponse,
    UserUpdateRequest,
)
from app.services import user_service

log = get_logger(__name__)
router = APIRouter()


# ── GET /users/me ─────────────────────────────────────────────────────────


@router.get(
    "/me",
    response_model=UserProfileResponse,
    summary="Profil user terautentikasi",
)
async def get_me(
    current_user: Any = Depends(get_current_user),
) -> UserProfileResponse:
    """
    GET /api/v1/users/me

    Return profil lengkap user yang sedang login.
    Tidak perlu query DB lagi — current_user sudah diload oleh get_current_user dependency.
    """
    user = current_user
    log.debug("get_me called", user_id=str(user.id))

    return UserProfileResponse(
        id=str(user.id),
        email=user.email,
        full_name=user.full_name,
        university=user.university,
        field_of_study=user.field_of_study,
        education_level=user.education_level,
        email_verified=user.email_verified,
        onboarding_step=user.onboarding_step,
        onboarding_completed_at=(
            user.onboarding_completed_at.isoformat()
            if user.onboarding_completed_at
            else None
        ),
        created_at=user.created_at.isoformat(),
    )


# ── PATCH /users/me ───────────────────────────────────────────────────────


@router.patch(
    "/me",
    response_model=UserProfileResponse,
    summary="Update profil user",
)
async def update_me(
    body: UserUpdateRequest,
    request: Request,
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserProfileResponse:
    """
    PATCH /api/v1/users/me

    Update profil user — semua field optional.
    Field yang tidak dikirim tidak akan berubah (partial update).

    Rate limit: 30 req/jam per user.
    """
    user = current_user
    await check_rate_limit("auth_users_patch", str(user.id))

    updated_user = await user_service.update_user(
        user=user,
        db=db,
        full_name=body.full_name,
        university=body.university,
        field_of_study=body.field_of_study,
        education_level=body.education_level,
        onboarding_step=body.onboarding_step,
    )

    log.info(
        "user profile updated",
        user_id=str(updated_user.id),
        onboarding_step=updated_user.onboarding_step,
    )

    return UserProfileResponse(
        id=str(updated_user.id),
        email=updated_user.email,
        full_name=updated_user.full_name,
        university=updated_user.university,
        field_of_study=updated_user.field_of_study,
        education_level=updated_user.education_level,
        email_verified=updated_user.email_verified,
        onboarding_step=updated_user.onboarding_step,
        onboarding_completed_at=(
            updated_user.onboarding_completed_at.isoformat()
            if updated_user.onboarding_completed_at
            else None
        ),
        created_at=updated_user.created_at.isoformat(),
    )


# ── GET /users/universities ───────────────────────────────────────────────


@router.get(
    "/universities",
    response_model=UniversityListResponse,
    summary="Daftar universitas untuk autocomplete",
)
async def get_universities(
    q: Optional[str] = Query(
        default=None,
        description="Query pencarian nama/alias/kota universitas (case-insensitive substring).",
        max_length=100,
    ),
    limit: int = Query(
        default=20,
        ge=1,
        le=50,
        description="Jumlah maksimum hasil. Default 20, maksimum 50.",
    ),
) -> UniversityListResponse:
    """
    GET /api/v1/users/universities?q=bandung&limit=20

    Return daftar universitas dari universities.json.
    Endpoint publik — tidak memerlukan autentikasi.
    Cocok untuk autocomplete pada Screen 0 onboarding.
    """
    universities = user_service.get_universities(query=q, limit=limit)
    return UniversityListResponse(universities=universities, total=len(universities))


# ── GET /users/preferences ────────────────────────────────────────────────


@router.get(
    "/preferences",
    response_model=UserPreferencesResponse,
    summary="Preferensi user",
)
async def get_preferences(
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserPreferencesResponse:
    """
    GET /api/v1/users/preferences

    Return UserPreferences user yang sedang login.
    """
    user = current_user
    prefs = await user_service.get_user_preferences(user, db)

    return UserPreferencesResponse(
        preferred_citation_style=prefs.preferred_citation_style,
        ui_language=prefs.ui_language,
        email_notifications=prefs.email_notifications,
        updated_at=prefs.updated_at.isoformat() if prefs.updated_at else None,
    )


# ── PATCH /users/preferences ──────────────────────────────────────────────


@router.patch(
    "/preferences",
    response_model=UserPreferencesResponse,
    summary="Update preferensi user",
)
async def update_preferences(
    body: UserPreferencesUpdate,
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserPreferencesResponse:
    """
    PATCH /api/v1/users/preferences

    Update UserPreferences — semua field optional (partial update).
    preferred_citation_style: set ke string untuk override, atau kirim tanpa field untuk skip.

    Digunakan:
      - Onboarding Screen 3: user konfirmasi/ubah citation style
      - Settings page: user ubah bahasa UI atau notifikasi email
    """
    user = current_user
    prefs = await user_service.update_user_preferences(
        user=user,
        db=db,
        preferred_citation_style=body.preferred_citation_style,
        ui_language=body.ui_language,
        email_notifications=body.email_notifications,
    )

    log.info(
        "user preferences updated",
        user_id=str(user.id),
        citation_style=prefs.preferred_citation_style,
    )

    return UserPreferencesResponse(
        preferred_citation_style=prefs.preferred_citation_style,
        ui_language=prefs.ui_language,
        email_notifications=prefs.email_notifications,
        updated_at=prefs.updated_at.isoformat() if prefs.updated_at else None,
    )

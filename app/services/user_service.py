# ═══════════════════════════════════════════════════════════════════════════
# File    : app/services/user_service.py
# Desc    : User service — business logic untuk Auth & User endpoints Fase 2.
#
#           Fungsi utama:
#             upsert_user_from_jwt()   — create/get User dari JWT claims.
#                                        Juga buat UserPreferences row jika belum ada.
#             get_user_by_id()         — ambil User + preferences (eager load).
#             update_user()            — PATCH /users/me (profil + onboarding step).
#             get_universities()       — baca universities.json + fuzzy search.
#             get_user_preferences()   — ambil UserPreferences satu user.
#             update_user_preferences() — PATCH /users/preferences.
#
#           Separation of concerns:
#             - Service layer: semua DB query dan business rule
#             - Endpoint layer: hanya HTTP concern (request parsing, response format)
#
#           Catatan onboarding_step:
#             0 = belum mulai (baru login)
#             1 = nama selesai (Screen 0 done)
#             2 = jenjang selesai (Screen 1 done)
#             3 = prodi selesai (Screen 2 done)
#             4 = onboarding selesai (Screen 3 + 4 done)
#             Ref: Blueprint §11.15, §6.1
#
# Layer   : Services / User
# Deps    : sqlalchemy, app.models.database, app.core.logging
# Step    : STEP 2 — Fase 2
# Ref     : Blueprint §2.2, §6.1, §6.11, §11.15
# ═══════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import UnauthorizedError
from app.core.logging import get_logger
from app.models.database import User, UserPreferences

log = get_logger(__name__)

# ── Universities dataset ──────────────────────────────────────────────────

_UNIVERSITIES_PATH = Path(__file__).resolve().parent.parent / "data" / "universities.json"
_universities_cache: list[dict] | None = None


def _load_universities() -> list[dict]:
    """Load universities.json sekali ke memory (cached)."""
    global _universities_cache
    if _universities_cache is None:
        with open(_UNIVERSITIES_PATH, encoding="utf-8") as f:
            _universities_cache = json.load(f)
    return _universities_cache


# ── Upsert User dari JWT ──────────────────────────────────────────────────


async def upsert_user_from_jwt(
    claims: dict[str, Any],
    db: AsyncSession,
) -> User:
    """
    INSERT atau GET user berdasarkan Supabase JWT claims.

    Flow:
      1. Ekstrak supabase_id (sub) dan email dari claims.
      2. SELECT user WHERE supabase_id = claims.sub.
      3. Jika tidak ada: INSERT user baru + INSERT user_preferences default.
      4. Jika ada: update email_verified jika claims menunjukkan verified.
      5. Return user dengan preferences di-load.

    Digunakan di POST /auth/verify — dipanggil setiap kali frontend exchange token.
    Idempotent: safe untuk dipanggil berkali-kali (UPSERT semantics).

    Raises:
        UnauthorizedError: jika claims tidak mengandung sub atau email.
    """
    supabase_id_str = claims.get("sub")
    email = claims.get("email")

    if not supabase_id_str:
        raise UnauthorizedError(message="JWT tidak mengandung user ID (sub).")
    if not email:
        raise UnauthorizedError(message="JWT tidak mengandung email.")

    try:
        supabase_id = uuid.UUID(supabase_id_str)
    except ValueError as exc:
        raise UnauthorizedError(message="Format supabase_id tidak valid.") from exc

    # Cek apakah user sudah ada
    result = await db.execute(
        select(User)
        .options(selectinload(User.preferences))
        .where(User.supabase_id == supabase_id)
    )
    user = result.scalar_one_or_none()

    # Extract email_verified dari JWT claims
    # Supabase menyertakan email_confirmed_at jika email sudah diverifikasi
    email_verified = bool(
        claims.get("email_confirmed_at")
        or claims.get("email_verified")
        or claims.get("user_metadata", {}).get("email_verified")
    )

    if user is None:
        # User baru — INSERT
        log.info("Creating new user from JWT", email=email, supabase_id=supabase_id_str)
        user = User(
            supabase_id=supabase_id,
            email=email,
            email_verified=email_verified,
            onboarding_step=0,
        )
        db.add(user)
        await db.flush()  # Flush untuk mendapatkan user.id sebelum INSERT preferences

        # Buat UserPreferences default (one-to-one)
        prefs = UserPreferences(
            user_id=user.id,
            preferred_citation_style=None,
            ui_language="id",
            email_notifications=True,
        )
        db.add(prefs)
        await db.commit()

        # Reload dengan preferences
        await db.refresh(user)
        result2 = await db.execute(
            select(User)
            .options(selectinload(User.preferences))
            .where(User.id == user.id)
        )
        user = result2.scalar_one()
        log.info("New user created", user_id=str(user.id))

    else:
        # User sudah ada — update email_verified jika berubah
        updated = False
        if email_verified and not user.email_verified:
            user.email_verified = True
            updated = True
        if updated:
            await db.commit()
            await db.refresh(user)

    return user


# ── Get User ──────────────────────────────────────────────────────────────


async def get_user_by_id(
    user_id: uuid.UUID,
    db: AsyncSession,
) -> Optional[User]:
    """
    Ambil User berdasarkan internal UUID.
    Eager load preferences untuk menghindari N+1.
    """
    result = await db.execute(
        select(User)
        .options(selectinload(User.preferences))
        .where(User.id == user_id)
    )
    return result.scalar_one_or_none()


# ── Update User (PATCH /users/me) ─────────────────────────────────────────


async def update_user(
    user: User,
    db: AsyncSession,
    full_name: Optional[str] = None,
    university: Optional[str] = None,
    field_of_study: Optional[str] = None,
    education_level: Optional[str] = None,
    onboarding_step: Optional[int] = None,
) -> User:
    """
    Update profil user — semua field optional, hanya yang dikirim yang di-update.

    Validasi:
      - education_level harus 's1', 's2', atau 's3' jika dikirim.
      - onboarding_step harus 0–4 jika dikirim.
      - onboarding_completed_at di-set ke NOW() saat onboarding_step mencapai 4.

    Return user yang sudah diupdate.
    """
    if education_level is not None and education_level not in ("s1", "s2", "s3"):
        from app.core.exceptions import MiseliaBaseError

        class ValidationError(MiseliaBaseError):
            status_code = 422
            error_code = "validation_error"
            message = "education_level harus 's1', 's2', atau 's3'."

        raise ValidationError()

    if onboarding_step is not None and not (0 <= onboarding_step <= 4):
        from app.core.exceptions import MiseliaBaseError

        class ValidationError(MiseliaBaseError):
            status_code = 422
            error_code = "validation_error"
            message = "onboarding_step harus antara 0 dan 4."

        raise ValidationError()

    changed = False

    if full_name is not None:
        user.full_name = full_name.strip() or None
        changed = True

    if university is not None:
        user.university = university.strip() or None
        changed = True

    if field_of_study is not None:
        user.field_of_study = field_of_study.strip() or None
        changed = True

    if education_level is not None:
        user.education_level = education_level
        changed = True

    if onboarding_step is not None:
        user.onboarding_step = onboarding_step
        # Tandai onboarding selesai saat step = 4
        if onboarding_step == 4 and user.onboarding_completed_at is None:
            user.onboarding_completed_at = datetime.now(UTC)
        changed = True

    if changed:
        await db.commit()
        await db.refresh(user)

    return user


# ── Universities search ───────────────────────────────────────────────────


def get_universities(
    query: Optional[str] = None,
    limit: int = 20,
) -> list[dict]:
    """
    Return daftar universitas dari universities.json.

    Jika query diberikan: filter berdasarkan name atau aliases (case-insensitive substring).
    Jika tidak ada query: return semua dengan limit.

    Response format sesuai UniversityResult schema:
      { id, name, city, province, type, citation_style }
    """
    universities = _load_universities()

    if query and query.strip():
        q = query.strip().lower()
        filtered = [
            u for u in universities
            if q in u["name"].lower()
            or any(q in alias.lower() for alias in u.get("aliases", []))
            or q in u.get("city", "").lower()
        ]
    else:
        filtered = universities

    # Strip aliases dari response — tidak perlu di-expose ke frontend
    result = [
        {
            "id": u["id"],
            "name": u["name"],
            "city": u["city"],
            "province": u["province"],
            "type": u["type"],
            "citation_style": u["citation_style"],
        }
        for u in filtered[:limit]
    ]
    return result


# ── User Preferences ──────────────────────────────────────────────────────

_VALID_CITATION_STYLES = frozenset(
    ["apa7", "ieee", "vancouver", "chicago", "harvard", "mla", "turabian"]
)
_VALID_UI_LANGUAGES = frozenset(["id", "en"])


async def get_user_preferences(
    user: User,
    db: AsyncSession,
) -> UserPreferences:
    """
    Ambil UserPreferences untuk user.

    Jika belum ada (data migration atau race condition), buat baru.
    Ini adalah safety net — normalnya baris sudah ada sejak upsert_user_from_jwt().
    """
    result = await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == user.id)
    )
    prefs = result.scalar_one_or_none()

    if prefs is None:
        log.warning(
            "UserPreferences missing for user — creating default",
            user_id=str(user.id),
        )
        prefs = UserPreferences(
            user_id=user.id,
            preferred_citation_style=None,
            ui_language="id",
            email_notifications=True,
        )
        db.add(prefs)
        await db.commit()
        await db.refresh(prefs)

    return prefs


async def update_user_preferences(
    user: User,
    db: AsyncSession,
    preferred_citation_style: Optional[str] = None,
    ui_language: Optional[str] = None,
    email_notifications: Optional[bool] = None,
) -> UserPreferences:
    """
    Update UserPreferences — semua field optional.

    Validasi:
      - preferred_citation_style: harus nilai valid atau None (reset ke auto-detect).
      - ui_language: hanya 'id' atau 'en'.

    Jika preferred_citation_style = None: reset ke auto-detect (field di-null-kan).
    """
    if preferred_citation_style is not None and preferred_citation_style not in _VALID_CITATION_STYLES:
        from app.core.exceptions import MiseliaBaseError

        class ValidationError(MiseliaBaseError):
            status_code = 422
            error_code = "validation_error"
            message = f"citation_style tidak valid. Pilihan: {', '.join(sorted(_VALID_CITATION_STYLES))}"

        raise ValidationError()

    if ui_language is not None and ui_language not in _VALID_UI_LANGUAGES:
        from app.core.exceptions import MiseliaBaseError

        class ValidationError(MiseliaBaseError):
            status_code = 422
            error_code = "validation_error"
            message = "ui_language harus 'id' atau 'en'."

        raise ValidationError()

    prefs = await get_user_preferences(user, db)

    changed = False

    # None dikirim eksplisit = reset ke auto-detect
    # Bedakan None (tidak dikirim) vs None (reset) lewat sentinel di schema layer
    if preferred_citation_style is not None:
        prefs.preferred_citation_style = preferred_citation_style
        changed = True

    if ui_language is not None:
        prefs.ui_language = ui_language
        changed = True

    if email_notifications is not None:
        prefs.email_notifications = email_notifications
        changed = True

    if changed:
        await db.commit()
        await db.refresh(prefs)

    return prefs

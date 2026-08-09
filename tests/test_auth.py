# ═══════════════════════════════════════════════════════════════════════════
# File    : tests/test_auth.py
# Desc    : Test suite untuk Auth dan User endpoints — 6 test cases.
#
#           Cakupan:
#             a01 — POST /auth/verify: new user → is_new_user=True, user di DB
#             a02 — POST /auth/verify: existing user → is_new_user=False
#             a03 — POST /auth/verify: no token → 401
#             a04 — GET /users/me: profil terautentikasi → 200 field lengkap
#             a05 — PATCH /users/me: update profil sukses → 200 terupdate
#             a06 — PATCH /users/me: education_level invalid → 422
#
#           STRATEGI:
#             - POST /auth/verify: mock verify_jwt (AsyncMock) — no Supabase JWKS request
#             - GET/PATCH /users/me: override get_current_user dependency → test_user
#             - DB real melalui db_session fixture (PostgreSQL, per-test SAVEPOINT rollback)
#             - PATCH /users/me memanggil check_rate_limit → mock sebagai AsyncMock
#               (tidak ada Redis di test environment)
#
# Layer   : Tests / Auth
# Deps    : pytest, pytest-asyncio, httpx, unittest.mock
# Step    : STEP 7 — Fase 2
# Ref     : Blueprint §2.2, §3.1, §11.15, §6.1
# ═══════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.main import app
from app.models.database import User, UserPreferences

# ── Konstanta test ────────────────────────────────────────────────────────

_SUPABASE_ID_NEW = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
_SUPABASE_ID_EXISTING = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"  # sama dengan test_user
_NEW_USER_EMAIL = "newuser@miselia.id"
_EXISTING_USER_EMAIL = "test@miselia.id"  # sama dengan test_user

_AUTH_VERIFY_URL = "/api/v1/auth/verify"
_USERS_ME_URL = "/api/v1/users/me"


# ── Fixture: authenticated client (override get_current_user) ─────────────


@pytest_asyncio.fixture
async def authed_client(
    test_client: AsyncClient,
    test_user: Any,
) -> AsyncGenerator[AsyncClient, None]:
    """
    AsyncClient dengan get_current_user override → test_user.
    Digunakan untuk endpoint yang memerlukan autentikasi (a04, a05, a06).
    """
    app.dependency_overrides[get_current_user] = lambda: test_user
    yield test_client
    app.dependency_overrides.pop(get_current_user, None)


# ═══════════════════════════════════════════════════════════════════════════
# a01 — POST /auth/verify: new user → is_new_user=True
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_a01_auth_verify_new_user(
    test_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """
    a01: POST /auth/verify dengan JWT user baru.

    Expected:
    - 200 OK
    - is_new_user=True
    - user_id tersimpan di DB (bisa di-query)
    - UserPreferences row dibuat secara otomatis

    Mock: verify_jwt return claims untuk user baru (supabase_id belum ada di DB)
    Ref: Blueprint §3.1 — upsert_user_from_jwt()
    """
    new_claims = {
        "sub": _SUPABASE_ID_NEW,
        "email": _NEW_USER_EMAIL,
        "role": "authenticated",
        "email_confirmed_at": "2026-08-09T00:00:00Z",
    }

    with patch("app.api.v1.auth.verify_jwt", new_callable=AsyncMock) as mock_jwt:
        mock_jwt.return_value = new_claims

        resp = await test_client.post(
            _AUTH_VERIFY_URL,
            headers={"Authorization": "Bearer mock-token-new-user"},
        )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    body = resp.json()
    assert body["is_new_user"] is True
    assert body["email"] == _NEW_USER_EMAIL
    assert body["onboarding_step"] == 0  # new user selalu mulai dari 0

    # Verifikasi user tersimpan di DB
    new_supabase_id = uuid.UUID(_SUPABASE_ID_NEW)
    result = await db_session.execute(select(User).where(User.supabase_id == new_supabase_id))
    db_user = result.scalar_one_or_none()
    assert db_user is not None, "User baru harus tersimpan di DB"
    assert db_user.email == _NEW_USER_EMAIL

    # Verifikasi UserPreferences dibuat
    prefs_result = await db_session.execute(
        select(UserPreferences).where(UserPreferences.user_id == db_user.id)
    )
    prefs = prefs_result.scalar_one_or_none()
    assert prefs is not None, "UserPreferences harus dibuat untuk user baru"
    assert prefs.ui_language == "id"  # default language


# ═══════════════════════════════════════════════════════════════════════════
# a02 — POST /auth/verify: existing user → is_new_user=False
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_a02_auth_verify_existing_user(
    test_client: AsyncClient,
    test_user: Any,  # pastikan test_user sudah di DB sebelum verify
) -> None:
    """
    a02: POST /auth/verify dengan JWT user yang sudah ada di DB.

    Expected:
    - 200 OK
    - is_new_user=False
    - user_id = test_user.id

    Mock: verify_jwt return claims untuk test_user (supabase_id sudah di DB via test_user)
    Ref: Blueprint §3.1 — idempotent upsert
    """
    existing_claims = {
        "sub": _SUPABASE_ID_EXISTING,  # sama dengan test_user.supabase_id
        "email": _EXISTING_USER_EMAIL,
        "role": "authenticated",
        "email_confirmed_at": "2026-08-09T00:00:00Z",
    }

    with patch("app.api.v1.auth.verify_jwt", new_callable=AsyncMock) as mock_jwt:
        mock_jwt.return_value = existing_claims

        resp = await test_client.post(
            _AUTH_VERIFY_URL,
            headers={"Authorization": "Bearer mock-token-existing"},
        )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    body = resp.json()
    assert body["is_new_user"] is False
    assert body["email"] == _EXISTING_USER_EMAIL
    assert body["user_id"] == str(test_user.id)


# ═══════════════════════════════════════════════════════════════════════════
# a03 — POST /auth/verify: no token → 401
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_a03_auth_verify_no_token(
    test_client: AsyncClient,
) -> None:
    """
    a03: POST /auth/verify tanpa Authorization header → 401 Unauthorized.

    Expected:
    - 401 Unauthorized

    Tidak perlu mock verify_jwt — endpoint reject sebelum memanggil verify_jwt.
    Ref: Blueprint §3.1 — extract_token_from_header returns None → 401
    """
    resp = await test_client.post(_AUTH_VERIFY_URL)

    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"

    body = resp.json()
    assert "detail" in body


# ═══════════════════════════════════════════════════════════════════════════
# a04 — GET /users/me: profil terautentikasi → 200 field lengkap
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_a04_get_user_profile(
    authed_client: AsyncClient,
    test_user: Any,
) -> None:
    """
    a04: GET /users/me dengan user terautentikasi.

    Expected:
    - 200 OK
    - Body mengandung: id, email, full_name, university, field_of_study,
      education_level, email_verified, onboarding_step, created_at

    Ref: Blueprint §6.1 — UserProfileResponse fields
    """
    resp = await authed_client.get(_USERS_ME_URL)

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    body = resp.json()
    assert body["id"] == str(test_user.id)
    assert body["email"] == test_user.email
    assert body["full_name"] == test_user.full_name
    assert body["university"] == test_user.university
    assert body["field_of_study"] == test_user.field_of_study
    assert body["education_level"] == test_user.education_level
    assert body["email_verified"] == test_user.email_verified
    assert "onboarding_step" in body
    assert "created_at" in body


# ═══════════════════════════════════════════════════════════════════════════
# a05 — PATCH /users/me: update profil sukses → 200 field terupdate
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_a05_patch_user_profile(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    test_user: Any,
) -> None:
    """
    a05: PATCH /users/me dengan payload update valid.

    Payload:
      full_name = "Budi Santoso"
      education_level = "s2"
      onboarding_step = 2

    Expected:
    - 200 OK
    - Body mengandung nilai yang terupdate
    - DB row terupdate

    Mock: check_rate_limit (tidak ada Redis di test environment)
    Ref: Blueprint §6.1, §11.15
    """
    payload = {
        "full_name": "Budi Santoso",
        "education_level": "s2",
        "onboarding_step": 2,
    }

    with patch("app.api.v1.users.check_rate_limit", new_callable=AsyncMock) as mock_rl:
        mock_rl.return_value = None

        resp = await authed_client.patch(_USERS_ME_URL, json=payload)

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    body = resp.json()
    assert body["full_name"] == "Budi Santoso"
    assert body["education_level"] == "s2"
    assert body["onboarding_step"] == 2

    # Verifikasi update di DB
    await db_session.refresh(test_user)
    assert test_user.full_name == "Budi Santoso"
    assert test_user.education_level == "s2"
    assert test_user.onboarding_step == 2


# ═══════════════════════════════════════════════════════════════════════════
# a06 — PATCH /users/me: education_level invalid → 422
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_a06_patch_user_invalid_education_level(
    authed_client: AsyncClient,
) -> None:
    """
    a06: PATCH /users/me dengan education_level tidak valid → 422.

    Payload:
      education_level = "d3"  — bukan 's1', 's2', atau 's3'

    Expected:
    - 422 Unprocessable Entity
    - Body mengandung validation error detail untuk field education_level

    Ref: Blueprint §6.1 — Literal["s1", "s2", "s3"] constraint
    """
    payload = {"education_level": "d3"}

    resp = await authed_client.patch(_USERS_ME_URL, json=payload)

    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"

    body = resp.json()
    assert "detail" in body
    # Cek field error merujuk ke education_level
    errors = body["detail"]
    assert any(
        "education_level" in str(err).lower() for err in errors
    ), f"Expected education_level in errors, got: {errors}"

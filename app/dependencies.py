# ═══════════════════════════════════════════════════════════════════════════
# File    : app/dependencies.py
# Desc    : FastAPI dependency injection utama.
#           get_db            — async database session
#           get_current_user  — user terautentikasi (raise 401 jika tidak ada JWT)
#           get_optional_user — user atau None (guest-compatible endpoints)
# Layer   : Dependencies
# Deps    : sqlalchemy, app.core.auth, app.models.database
# Step    : STEP 3 — Backend Setup
# Ref     : Blueprint §2.2, §3.1
# NOTE    : User model menggunakan placeholder dari STEP 3.
#           STEP 4 mengisi app/models/database.py dengan model penuh.
# ═══════════════════════════════════════════════════════════════════════════

import uuid
from collections.abc import AsyncGenerator
from typing import Any, Optional

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.core.auth import extract_token_from_header, verify_jwt
from app.core.exceptions import UnauthorizedError
from app.core.logging import get_logger

log = get_logger(__name__)

# ── SQLAlchemy async engine & session factory ─────────────────────────────

engine = create_async_engine(
    settings.async_database_url,
    echo=settings.is_development,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency — yield async DB session.
    Session otomatis di-close setelah request selesai.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ── Auth dependencies ─────────────────────────────────────────────────────

async def get_current_user(
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """
    Dependency — return user terautentikasi.
    Raise UnauthorizedError (401) jika tidak ada token atau token tidak valid.

    Digunakan di endpoint yang WAJIB login.
    Ref: Blueprint §2.2 — dependencies.py
    """
    token = extract_token_from_header(authorization)
    if not token:
        raise UnauthorizedError()

    claims = await verify_jwt(token)
    supabase_id = claims.get("sub")
    if not supabase_id:
        raise UnauthorizedError(message="Token tidak mengandung user ID.")

    # Ambil user dari DB berdasarkan supabase_id
    # NOTE: Implementasi penuh menunggu User model di STEP 4.
    # Saat ini return claims dict sebagai placeholder.
    user = await _get_user_by_supabase_id(supabase_id, db)
    if user is None:
        raise UnauthorizedError(message="User tidak ditemukan.")

    return user


async def get_optional_user(
    authorization: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> Optional[Any]:
    """
    Dependency — return user jika ada JWT valid, atau None jika guest.
    TIDAK raise error jika tidak ada token.

    Digunakan di guest-compatible endpoints seperti Find Papers.
    Ref: Blueprint §2.2 — dependencies.py
    """
    token = extract_token_from_header(authorization)
    if not token:
        return None

    try:
        claims = await verify_jwt(token)
        supabase_id = claims.get("sub")
        if not supabase_id:
            return None
        return await _get_user_by_supabase_id(supabase_id, db)
    except UnauthorizedError:
        return None
    except Exception as e:
        log.warning("get_optional_user failed", error=str(e))
        return None


async def _get_user_by_supabase_id(
    supabase_id: str,
    db: AsyncSession,
) -> Optional[Any]:
    """
    Ambil user dari DB berdasarkan supabase_id.
    Implementasi penuh setelah User model tersedia di STEP 4.
    """
    from sqlalchemy import select
    from app.models.database import User

    result = await db.execute(
        select(User).where(User.supabase_id == uuid.UUID(supabase_id))
    )
    return result.scalar_one_or_none()

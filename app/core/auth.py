# ═══════════════════════════════════════════════════════════════════════════
# File    : app/core/auth.py
# Desc    : JWT ES256 verification via Supabase JWKS.
#           Menyediakan verify_jwt() untuk dependencies.py.
#           JWKS di-cache in-memory dengan TTL 1 jam.
# Layer   : Core / Auth
# Deps    : python-jose, httpx, app.config
# Step    : STEP 3 — Backend Setup
# Ref     : Blueprint §2.2, §3.1
# ═══════════════════════════════════════════════════════════════════════════

import time
from typing import Optional

import httpx
from jose import JWTError, jwt

from app.config import settings
from app.core.exceptions import UnauthorizedError
from app.core.logging import get_logger

log = get_logger(__name__)

# ── JWKS cache ────────────────────────────────────────────────────────────

_jwks_cache: dict = {}
_jwks_fetched_at: float = 0.0
_JWKS_TTL: int = 3600  # 1 jam


async def _fetch_jwks() -> dict:
    """Fetch JWKS dari Supabase Auth endpoint."""
    jwks_url = f"{settings.SUPABASE_URL}/auth/v1/.well-known/jwks.json"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(jwks_url)
        response.raise_for_status()
        return response.json()


async def get_jwks() -> dict:
    """
    Return JWKS dari cache jika masih valid, atau fetch baru dari Supabase.
    Cache TTL: 1 jam — cukup untuk rotasi kunci yang jarang.
    """
    global _jwks_cache, _jwks_fetched_at

    now = time.time()
    if _jwks_cache and (now - _jwks_fetched_at) < _JWKS_TTL:
        return _jwks_cache

    try:
        jwks = await _fetch_jwks()
        _jwks_cache = jwks
        _jwks_fetched_at = now
        log.debug("JWKS refreshed from Supabase")
        return jwks
    except Exception as e:
        log.warning("Failed to fetch JWKS", error=str(e))
        if _jwks_cache:
            # Gunakan cache lama jika fetch gagal
            log.warning("Using stale JWKS cache")
            return _jwks_cache
        raise UnauthorizedError(message="Tidak bisa memverifikasi token.") from e


# ── JWT Verification ─────────────────────────────────────────────────────

async def verify_jwt(token: str) -> dict:
    """
    Verifikasi JWT ES256 dari Supabase Auth.

    Returns dict berisi claims JWT (sub, email, role, exp, dll).
    Raises UnauthorizedError jika token tidak valid.

    Supabase JWT claims yang relevan:
    - sub: UUID user di Supabase Auth
    - email: email user
    - role: 'authenticated' untuk user biasa
    - exp: expiry timestamp
    """
    try:
        jwks = await get_jwks()

        # Decode header untuk mendapatkan kid (key ID)
        headers = jwt.get_unverified_header(token)
        kid = headers.get("kid")

        # Cari key matching di JWKS
        key = None
        for jwk_key in jwks.get("keys", []):
            if jwk_key.get("kid") == kid or kid is None:
                key = jwk_key
                break

        if key is None:
            raise UnauthorizedError(message="JWT key tidak ditemukan.")

        # Verify JWT — algorithm ES256 sesuai Supabase Auth
        payload = jwt.decode(
            token,
            key,
            algorithms=["ES256"],
            options={
                "verify_aud": False,  # Supabase tidak set audience di semua token
            },
        )

        # Validasi role — hanya 'authenticated' yang valid untuk protected endpoints
        role = payload.get("role", "")
        if role not in ("authenticated", "service_role"):
            raise UnauthorizedError(
                message="Token tidak memiliki role yang valid."
            )

        return payload

    except UnauthorizedError:
        raise
    except JWTError as e:
        log.debug("JWT verification failed", error=str(e))
        raise UnauthorizedError(message="Token tidak valid atau sudah kadaluarsa.") from e
    except Exception as e:
        log.warning("Unexpected auth error", error=str(e))
        raise UnauthorizedError(message="Gagal memverifikasi autentikasi.") from e


def extract_token_from_header(authorization: Optional[str]) -> Optional[str]:
    """
    Ekstrak Bearer token dari Authorization header.
    Return None jika header tidak ada atau format salah.
    """
    if not authorization:
        return None
    parts = authorization.split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1]

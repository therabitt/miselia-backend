# ═══════════════════════════════════════════════════════════════════════════
# File    : app/core/security.py
# Desc    : Admin IP whitelist check + CORS origin config.
#           IP whitelist digunakan oleh admin endpoints.
# Layer   : Core / Security
# Deps    : app.config
# Step    : STEP 3 — Backend Setup
# Ref     : Blueprint §2.2
# ═══════════════════════════════════════════════════════════════════════════

from fastapi import Request

from app.config import settings
from app.core.exceptions import ForbiddenError


def get_client_ip(request: Request) -> str:
    """
    Ekstrak IP client dari request.
    Cek X-Forwarded-For dulu (Railway reverse proxy), fallback ke client.host.
    """
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # Format: "client, proxy1, proxy2" — ambil yang pertama
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def require_admin_ip(request: Request) -> None:
    """
    Guard: IP request harus ada di ADMIN_IP_WHITELIST.
    Dipanggil di admin endpoints bersama dengan require_admin_user.
    Ref: Blueprint §2.2 admin.py
    """
    client_ip = get_client_ip(request)
    if client_ip not in settings.admin_ip_list:
        raise ForbiddenError(message=f"Akses dari IP {client_ip} tidak diizinkan.")


def is_admin_ip(request: Request) -> bool:
    """Cek apakah IP request ada di whitelist — tanpa raise exception."""
    return get_client_ip(request) in settings.admin_ip_list


def get_cors_origins() -> list[str]:
    """Return list allowed origins untuk CORS middleware."""
    return settings.allowed_origins

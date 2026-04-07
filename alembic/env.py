# ═════════════════════════════════════════════════════════════════════════════
# File    : alembic/env.py
# Desc    : Alembic environment — async engine via asyncpg.
#           Online mode: asyncpg untuk Supabase/PostgreSQL.
#           Offline mode: sync URL untuk generate SQL scripts.
#           Target metadata dari Base (semua ORM models di database.py).
# Layer   : Database / Migration
# Deps    : sqlalchemy, asyncpg, alembic, app.config, app.models.database
# Step    : STEP 5 — Alembic Setup & Migration Files
# Ref     : Blueprint §2.2, Appendix D
# ═════════════════════════════════════════════════════════════════════════════

import asyncio
import logging
from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.models.database import Base

# ── Alembic Config ────────────────────────────────────────────────────────

config = context.config
log = logging.getLogger("alembic.env")

# Setup loggers dari alembic.ini (jika ada fileConfig)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata untuk autogenerate — semua ORM models
target_metadata = Base.metadata


# ── URL helpers ───────────────────────────────────────────────────────────

def _get_sync_url() -> str:
    """
    URL untuk offline mode (generate SQL scripts).
    Gunakan postgresql:// (bukan asyncpg) untuk offline rendering.
    """
    url = settings.DATABASE_URL
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


def _get_async_url() -> str:
    """URL untuk online mode (eksekusi langsung ke DB via asyncpg)."""
    return settings.async_database_url


# ── Offline mode ──────────────────────────────────────────────────────────

def run_migrations_offline() -> None:
    """
    Generate SQL migration script tanpa koneksi DB.
    Output ke stdout — berguna untuk review sebelum apply ke production.
    """
    url = _get_sync_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


# ── Online mode ───────────────────────────────────────────────────────────

def do_run_migrations(connection: Connection) -> None:
    """
    Jalankan migration dengan koneksi yang sudah tersedia.
    Dipanggil dari run_async_migrations via run_sync.
    """
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        # Sertakan schema PostgreSQL eksplisit
        include_schemas=False,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """
    Buat async engine dan jalankan migration.
    Engine dibuat tanpa connection pooling (NullPool) karena
    migration berjalan sekali dan tidak perlu pool.
    """
    connectable = create_async_engine(
        _get_async_url(),
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()
    log.info("Migration selesai — engine disposed")


def run_migrations_online() -> None:
    """Entry point untuk online mode — jalankan event loop."""
    asyncio.run(run_async_migrations())


# ── Entry point ───────────────────────────────────────────────────────────

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

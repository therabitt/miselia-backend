# ═══════════════════════════════════════════════════════════════════════════
# File    : tests/conftest.py
# Desc    : pytest fixtures untuk test suite Miselia.
#
#           STRATEGI ISOLASI TEST:
#           - Satu engine async terhadap DATABASE_URL_TEST (PostgreSQL)
#           - Per test session: apply semua migration Alembic (create_all + migrate)
#           - Per test: BEGIN SAVEPOINT → jalankan test → ROLLBACK TO SAVEPOINT
#             Pattern ini memastikan setiap test mulai dari state bersih
#             tanpa harus drop/create tabel setiap kali.
#
#           FIXTURES YANG TERSEDIA:
#           - db_session         : AsyncSession yang di-rollback setelah test
#           - test_client        : httpx.AsyncClient terhubung ke FastAPI app
#           - test_user          : User object di DB test
#           - subscription_free  : Subscription tier Free untuk test_user
#           - subscription_sarjana   : Subscription tier Sarjana
#           - subscription_magister  : Subscription tier Magister
#           - subscription_institutional : Subscription tier Institutional
#           - institutional_account  : InstitutionalAccount untuk institutional sub
#
#           PRASYARAT:
#           - PostgreSQL berjalan (via docker-compose: docker-compose up postgres)
#           - DATABASE_URL_TEST ada di .env atau environment variable
#           - DB 'miselia_test' sudah dibuat (dibuat otomatis oleh session_setup fixture)
#
# Layer   : Tests
# Deps    : pytest, pytest-asyncio, httpx, sqlalchemy, alembic
# Step    : STEP 8 — Backend: Testing Setup
# Ref     : Blueprint §2.2, §6.1–§6.3, §7.1
# ═══════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings
from app.main import app
from app.models.database import Base

# ═══════════════════════════════════════════════════════════════════════════
# Test database URL
# ═══════════════════════════════════════════════════════════════════════════


def _get_test_database_url() -> str:
    """
    Return async DATABASE_URL untuk test.
    Dibaca dari DATABASE_URL_TEST di env, fallback ke DATABASE_URL dengan
    nama DB diganti 'miselia_test'.
    """
    # Coba baca DATABASE_URL_TEST dari settings terlebih dahulu
    test_url = getattr(settings, "DATABASE_URL_TEST", None)
    if test_url:
        if test_url.startswith("postgres://"):
            test_url = test_url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif test_url.startswith("postgresql://"):
            test_url = test_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return test_url

    # Fallback: ganti nama DB di DATABASE_URL ke miselia_test
    url = settings.async_database_url
    # Ganti nama database di akhir URL
    if "/" in url:
        base, _ = url.rsplit("/", 1)
        return f"{base}/miselia_test"
    return url


TEST_DATABASE_URL = _get_test_database_url()

# ── Tambahkan DATABASE_URL_TEST ke Settings jika belum ada ────────────────
# Settings akan mencoba membaca DATABASE_URL_TEST dari env
# Jika tidak ada, kita inject langsung ke config

# ═══════════════════════════════════════════════════════════════════════════
# Session-scoped: Engine + Migration
# Dijalankan SEKALI per pytest session — membuat semua tabel
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    """Gunakan asyncio sebagai backend untuk anyio (dipakai pytest-asyncio)."""
    return "asyncio"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """
    Hook: tambahkan loop_scope="session" ke semua async test function.

    WAJIB untuk pytest-asyncio 0.25.x:
      - asyncio_default_fixture_loop_scope="session" (pyproject.toml) → fixtures
        menggunakan session event loop.
      - Tapi test FUNCTIONS masih menggunakan function-scoped loop secara default.
      - Tidak ada ini option untuk mengubah ini di 0.25.x — harus via marker.

    Hook ini secara otomatis menambahkan @pytest.mark.asyncio(loop_scope="session")
    ke setiap async test, sehingga test + fixtures semua share satu session loop.
    Ini mencegah:
        RuntimeError: Task got Future attached to a different loop

    Ref: pytest-asyncio docs — Event loop scope for tests
    """
    asyncio_session_mark = pytest.mark.asyncio(loop_scope="session")
    for item in items:
        if isinstance(item, pytest.Function) and asyncio.iscoroutinefunction(
            getattr(item, "function", None)
        ):
            item.add_marker(asyncio_session_mark, append=False)


@pytest_asyncio.fixture(scope="session")
async def test_engine() -> AsyncGenerator[Any, None]:
    """
    Buat async engine untuk test database.
    Scope: session — engine dibuat sekali, dibuang di akhir session.

    Auto-create 'miselia_test' jika belum ada:
    - Koneksi ke maintenance DB 'postgres' via asyncpg
    - CREATE DATABASE ... IF NOT EXISTS (menggunakan exist-check manual)
    - Setelah DB ada, buat semua tabel via Base.metadata.create_all

    CATATAN: create_all tidak menjalankan Alembic migration.
    Untuk tabel partitioned (analytics_events), gunakan alembic.command.upgrade().
    Ref: Blueprint §2.2, §6.1
    """
    # ── Step 1: Auto-create DB test jika belum ada ───────────────────────
    # Ambil DSN asyncpg (tanpa asyncpg+postgresql:// prefix) dari TEST_DATABASE_URL
    # TEST_DATABASE_URL = 'postgresql+asyncpg://user:pass@host:port/miselia_test'
    # asyncpg.connect() butuh: 'postgresql://user:pass@host:port/postgres'
    maintenance_dsn = TEST_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)
    # Ganti nama DB ke 'postgres' (maintenance DB — selalu ada)
    if "/" in maintenance_dsn:
        base_dsn, _ = maintenance_dsn.rsplit("/", 1)
        maintenance_dsn = f"{base_dsn}/postgres"

    conn_raw: asyncpg.Connection = await asyncpg.connect(dsn=maintenance_dsn)
    try:
        db_exists = await conn_raw.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", "miselia_test"
        )
        if not db_exists:
            # CREATE DATABASE tidak bisa dalam transaction — gunakan execute langsung
            await conn_raw.execute("CREATE DATABASE miselia_test OWNER postgres")
    finally:
        await conn_raw.close()

    # ── Step 2: Buat engine dan semua tabel ──────────────────────────────
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,  # Matikan SQL logging di test
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Teardown: drop semua tabel setelah session selesai
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


# ═══════════════════════════════════════════════════════════════════════════
# Function-scoped: DB connection + session — isolation via fresh engine per test
#
# DESAIN:
#   test_engine (session-scoped) hanya digunakan untuk:
#     - Auto-create database miselia_test
#     - Base.metadata.create_all (setup tabel)
#     - Base.metadata.drop_all (teardown tabel)
#
#   db_connection (function-scoped) membuat AsyncEngine BARU per test dengan
#   pool_size=1. Ini memastikan:
#     1. Tidak ada pool sharing antar test → tidak ada InterfaceError
#     2. Setiap test punya connection lifecycle sendiri (BEGIN → test → ROLLBACK)
#     3. Tidak bergantung pada session event loop → tidak ada loop conflict
#
#   Isolation: rollback setelah setiap test — DB kembali ke state sebelum test.
# ═══════════════════════════════════════════════════════════════════════════


@pytest_asyncio.fixture
async def db_connection(test_engine: Any) -> AsyncGenerator[AsyncConnection, None]:
    """
    Buat AsyncEngine BARU per test (pool_size=1) untuk isolasi penuh.

    Parameter test_engine hanya sebagai dependency order: memastikan tabel sudah
    dibuat sebelum test berjalan. Koneksi aktual menggunakan engine baru agar
    tidak ada pool sharing dengan test lain.

    Rollback otomatis setelah test selesai → data kembali ke state awal.
    """
    # Engine baru per test — tidak share pool dengan test_engine atau test lain
    fresh_engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        pool_size=1,  # Satu connection per test — tidak perlu lebih
        max_overflow=0,  # Tidak ada overflow — strict isolation
        pool_pre_ping=False,
    )
    try:
        async with fresh_engine.connect() as conn:
            await conn.begin()
            yield conn
            await conn.rollback()
    finally:
        await fresh_engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_connection: AsyncConnection) -> AsyncGenerator[AsyncSession, None]:
    """
    AsyncSession yang ter-bind ke db_connection (function-scoped fresh engine).
    Setiap test mendapat session baru — di-rollback setelah test selesai.
    Digunakan sebagai pengganti get_db() dependency di test.
    """
    session_factory = async_sessionmaker(
        bind=db_connection,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    async with session_factory() as session:
        yield session


# ═══════════════════════════════════════════════════════════════════════════
# HTTP test client
# ═══════════════════════════════════════════════════════════════════════════


@pytest_asyncio.fixture
async def test_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """
    httpx.AsyncClient untuk test endpoint FastAPI.
    Override dependency get_db() → db_session untuk isolasi test.

    Penggunaan:
        async def test_health(test_client: AsyncClient):
            resp = await test_client.get("/api/v1/health")
            assert resp.status_code == 200
    """
    from app.dependencies import get_db

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),  # type: ignore[arg-type]
        base_url="http://testserver",
        headers={"Content-Type": "application/json"},
    ) as client:
        yield client

    # Cleanup override
    app.dependency_overrides.pop(get_db, None)


# ═══════════════════════════════════════════════════════════════════════════
# Test data fixtures
# Blueprint §6.1 — User
# ═══════════════════════════════════════════════════════════════════════════


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> Any:
    """
    User fixture untuk testing.
    Menggunakan UUID deterministik agar test reproducible.
    Ref: Blueprint §6.1
    """
    from app.models.database import User

    user = User(
        id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        supabase_id=uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        email="test@miselia.id",
        full_name="Test User",
        university="Universitas Test",
        field_of_study="Teknik Informatika",
        education_level="s1",
        email_verified=True,
        onboarding_step=5,
        onboarding_completed_at=datetime.now(UTC),
        is_admin=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def test_admin_user(db_session: AsyncSession) -> Any:
    """
    Admin user fixture untuk testing admin endpoints.
    Ref: Blueprint §2.2 admin.py guard
    """
    from app.models.database import User

    user = User(
        id=uuid.UUID("00000000-0000-0000-0000-000000000099"),
        supabase_id=uuid.UUID("99999999-9999-9999-9999-999999999999"),
        email="admin@miselia.id",
        full_name="Admin User",
        email_verified=True,
        onboarding_step=5,
        is_admin=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


# ═══════════════════════════════════════════════════════════════════════════
# Institutional account fixture
# Blueprint §6.9 — InstitutionalAccount
# ═══════════════════════════════════════════════════════════════════════════


@pytest_asyncio.fixture
async def test_institutional_account(db_session: AsyncSession) -> Any:
    """
    InstitutionalAccount fixture untuk test institutional subscription.
    Ref: Blueprint §6.9, Decision #5
    """
    from app.models.database import InstitutionalAccount

    account = InstitutionalAccount(
        id=uuid.UUID("10000000-0000-0000-0000-000000000001"),
        name="Universitas Test Bandung",
        org_code="UTB2026",
        contact_email="admin@utb.ac.id",
        seats_purchased=25,
        seats_used=1,
        valid_from=datetime.now(UTC) - timedelta(days=30),
        valid_until=datetime.now(UTC) + timedelta(days=150),
        is_active=True,
    )
    db_session.add(account)
    await db_session.flush()
    return account


# ═══════════════════════════════════════════════════════════════════════════
# Subscription fixtures — satu per tier
# Blueprint §6.2, §7.1
# ═══════════════════════════════════════════════════════════════════════════


@pytest_asyncio.fixture
async def subscription_free(db_session: AsyncSession, test_user: Any) -> Any:
    """
    Subscription tier Free untuk test_user.
    Free: tidak ada current_period_end, tidak ada expiry.
    Ref: Blueprint §6.2, §7.1 TierConfig FREE
    """
    from app.models.database import Subscription

    sub = Subscription(
        id=uuid.UUID("20000000-0000-0000-0000-000000000001"),
        user_id=test_user.id,
        tier="free",
        plan_type="free",
        status="active",
        current_period_start=None,
        current_period_end=None,
        institutional_account_id=None,
    )
    db_session.add(sub)
    await db_session.flush()
    return sub


@pytest_asyncio.fixture
async def subscription_sarjana(db_session: AsyncSession, test_user: Any) -> Any:
    """
    Subscription tier Sarjana (monthly) untuk test_user.
    Sarjana: 3 active projects, P1–P6+P8, unlimited reruns.
    Ref: Blueprint §6.2, §7.1 TierConfig SARJANA
    """
    from app.models.database import Subscription

    now = datetime.now(UTC)
    sub = Subscription(
        id=uuid.UUID("20000000-0000-0000-0000-000000000002"),
        user_id=test_user.id,
        tier="sarjana",
        plan_type="monthly",
        status="active",
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
        institutional_account_id=None,
    )
    db_session.add(sub)
    await db_session.flush()
    return sub


@pytest_asyncio.fixture
async def subscription_magister(db_session: AsyncSession, test_user: Any) -> Any:
    """
    Subscription tier Magister (monthly) untuk test_user.
    Magister: 10 active projects, P1–P8 + P7 SLR, unlimited chat.
    Ref: Blueprint §6.2, §7.1 TierConfig MAGISTER
    """
    from app.models.database import Subscription

    now = datetime.now(UTC)
    sub = Subscription(
        id=uuid.UUID("20000000-0000-0000-0000-000000000003"),
        user_id=test_user.id,
        tier="magister",
        plan_type="monthly",
        status="active",
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
        institutional_account_id=None,
    )
    db_session.add(sub)
    await db_session.flush()
    return sub


@pytest_asyncio.fixture
async def subscription_institutional(
    db_session: AsyncSession,
    test_user: Any,
    test_institutional_account: Any,
) -> Any:
    """
    Subscription tier Institutional untuk test_user.
    Institutional: managed via institutional_account, no individual payment.
    Ref: Blueprint §6.2, §7.1 TierConfig INSTITUTIONAL
    """
    from app.models.database import Subscription

    now = datetime.now(UTC)
    sub = Subscription(
        id=uuid.UUID("20000000-0000-0000-0000-000000000004"),
        user_id=test_user.id,
        tier="institutional",
        plan_type="institutional",
        status="active",
        current_period_start=now,
        current_period_end=now + timedelta(days=150),  # 5 bulan (sesuai institutional)
        institutional_account_id=test_institutional_account.id,
    )
    db_session.add(sub)
    await db_session.flush()
    return sub


# ═══════════════════════════════════════════════════════════════════════════
# Convenience fixture — semua tier sekaligus
# ═══════════════════════════════════════════════════════════════════════════


@pytest_asyncio.fixture
async def all_subscriptions(
    subscription_free: Any,
    subscription_sarjana: Any,
    subscription_magister: Any,
    subscription_institutional: Any,
) -> dict[str, Any]:
    """
    Dict berisi semua tier subscription untuk test yang perlu compare antar tier.

    Penggunaan:
        async def test_tier_check(all_subscriptions):
            free_sub = all_subscriptions["free"]
            sarjana_sub = all_subscriptions["sarjana"]
    """
    return {
        "free": subscription_free,
        "sarjana": subscription_sarjana,
        "magister": subscription_magister,
        "institutional": subscription_institutional,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Helper: JWT token mock untuk test endpoint yang butuh auth
# ═══════════════════════════════════════════════════════════════════════════


def make_test_auth_header(
    supabase_id: str = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
) -> dict[str, str]:
    """
    Buat Authorization header untuk test.
    Digunakan untuk override verify_jwt() di endpoint test.

    NOTE: Untuk endpoint test yang butuh auth penuh (POST /auth/verify, dll),
    gunakan mock pada app.core.auth.verify_jwt bukan token nyata.

    Penggunaan:
        async def test_endpoint(test_client, monkeypatch):
            monkeypatch.setattr(
                "app.core.auth.verify_jwt",
                AsyncMock(return_value={"sub": "aaaaaaaa-...", "role": "authenticated"})
            )
            resp = await test_client.get("/api/v1/users/me",
                headers=make_test_auth_header())
    """
    return {"Authorization": f"Bearer test-token-{supabase_id}"}

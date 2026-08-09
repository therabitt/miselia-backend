# ═══════════════════════════════════════════════════════════════════════════
# File    : tests/test_library.py
# Desc    : Test suite untuk Library endpoints — 13 test cases.
#
#           Cakupan:
#             l01 — GET /library/papers: list kosong → 200, papers=[], total=0
#             l02 — POST /library/papers: save paper sukses → 201
#             l03 — POST /library/papers: save duplikat → 409
#             l04 — POST /library/papers: paper_id tidak ada → 404
#             l05 — GET /library/papers/{id}: detail paper → 200 field lengkap
#             l06 — GET /library/papers/{id}: tidak ditemukan → 404
#             l07 — GET /library/papers/{id}: milik user lain → 404
#             l08 — PATCH /library/papers/{id}: update notes dan tags → 200
#             l09 — PATCH /library/papers/{id}: tags normalisasi → 200, ternormalisasi
#             l10 — PATCH /library/papers/{id}: tags > 10 item → 422
#             l11 — DELETE /library/papers/{id}: soft delete → 204
#             l12 — DELETE /library/papers/{id}: tidak ditemukan → 404
#             l13 — GET /library/papers setelah delete → paper tidak muncul
#
#           STRATEGI:
#             - Semua endpoint butuh auth: override get_current_user → test_user
#             - POST/PATCH/DELETE butuh check_rate_limit mock (AsyncMock, no Redis)
#             - Butuh Paper row di DB: fixture test_paper lokal (UUID deterministik)
#             - Free tier: quota 25 papers, expires_at = +30 hari
#             - DB real via db_session (PostgreSQL, per-test SAVEPOINT rollback)
#             - Fixture test_library_paper: LibraryPaper row yang sudah tersimpan
#               (digunakan di l05–l13)
#
#           GAP RESOLUTIONS:
#             GAP 1: get_current_user override via authed_client fixture lokal
#             GAP 5: check_rate_limit di-mock per test (AsyncMock, no Redis)
#             GAP 3: test_paper fixture lokal, bukan di conftest
#             GAP 6: Tidak butuh subscription row → Free tier fallback default
#
# Layer   : Tests / Library
# Deps    : pytest, pytest-asyncio, httpx, sqlalchemy, unittest.mock
# Step    : STEP 7 — Fase 2
# Ref     : Blueprint §4.3, §6.12, §H.5, Decision #2, Decision #12, Decision #28
# ═══════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.main import app
from app.models.database import LibraryPaper, Paper

# ── Konstanta test ────────────────────────────────────────────────────────

_PAPER_UUID = uuid.UUID("30000000-0000-0000-0000-000000000001")
_PAPER_UUID_MISSING = uuid.UUID("30000000-0000-0000-0000-000000000099")
_OTHER_USER_UUID = uuid.UUID("00000000-0000-0000-0000-000000000002")

_LIBRARY_BASE_URL = "/api/v1/library/papers"


# ── Fixtures lokal ────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def test_paper(db_session: AsyncSession) -> Any:
    """
    Fixture: Paper row minimal yang valid di DB test.
    Dibutuhkan sebagai FK target untuk LibraryPaper (paper_id → papers.id).
    UUID deterministik untuk reproducibility.
    Ref: Blueprint §6.12 — papers table
    """
    paper = Paper(
        id=_PAPER_UUID,
        title="Test Paper: Machine Learning Applications in Education",
        authors=["Budi Santoso", "Siti Rahayu"],
        year=2024,
        venue="Jurnal Ilmu Komputer Indonesia",
        citation_count=42,
        abstract="Penelitian ini membahas aplikasi machine learning di dunia pendidikan.",
        is_open_access=True,
        is_manually_imported=False,
        semantic_scholar_id="test-s2-id-001",
    )
    db_session.add(paper)
    await db_session.flush()
    return paper


@pytest_asyncio.fixture
async def authed_client(
    test_client: AsyncClient,
    test_user: Any,
) -> AsyncGenerator[AsyncClient, None]:
    """
    AsyncClient dengan get_current_user override → test_user.
    Yield client, lalu cleanup override setelah test selesai.
    """
    app.dependency_overrides[get_current_user] = lambda: test_user
    yield test_client
    app.dependency_overrides.pop(get_current_user, None)


@pytest_asyncio.fixture
async def test_library_paper(
    db_session: AsyncSession,
    test_user: Any,
    test_paper: Any,
) -> Any:
    """
    Fixture: LibraryPaper row yang sudah tersimpan di DB test.
    Digunakan oleh l05–l13 yang butuh paper yang sudah ada.

    Tier Free: expires_at = +30 hari dari sekarang.
    Ref: Blueprint §6.12 — library_papers.expires_at untuk Free tier
    """
    now = datetime.now(UTC)
    lp = LibraryPaper(
        id=uuid.UUID("40000000-0000-0000-0000-000000000001"),
        user_id=test_user.id,
        paper_id=test_paper.id,
        source="find_papers",
        notes="Catatan awal test",
        tags=["nlp", "education"],
        is_visible=True,
        expires_at=now + timedelta(days=30),
    )
    db_session.add(lp)
    await db_session.flush()
    return lp


# ═══════════════════════════════════════════════════════════════════════════
# l01 — GET /library/papers: list kosong → 200, papers=[], total=0
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_l01_list_papers_empty(
    authed_client: AsyncClient,
) -> None:
    """
    l01: GET /library/papers untuk user tanpa paper → 200, list kosong.

    Expected:
    - 200 OK
    - papers = []
    - total = 0
    - quota.current_count = 0

    Tidak ada setup paper → library kosong.
    Ref: Blueprint §4.3 GET /library/papers
    """
    resp = await authed_client.get(_LIBRARY_BASE_URL)

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    body = resp.json()
    assert body["papers"] == []
    assert body["total"] == 0
    assert body["quota"]["current_count"] == 0
    assert "limit" in body
    assert "offset" in body


# ═══════════════════════════════════════════════════════════════════════════
# l02 — POST /library/papers: save paper sukses → 201
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_l02_save_paper_success(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    test_user: Any,
    test_paper: Any,
) -> None:
    """
    l02: POST /library/papers dengan paper_id valid → 201, paper tersimpan.

    Expected:
    - 201 Created
    - Body: id, paper_info (title, id), source, expires_at (Free tier: 30 hari)
    - LibraryPaper row ada di DB dengan is_visible=True

    Mock: check_rate_limit (no Redis)
    Ref: Blueprint §4.3 POST /library/papers, Decision #2 (30 hari Free)
    """
    payload = {
        "paper_id": str(test_paper.id),
        "source": "find_papers",
    }

    with patch("app.api.v1.library.check_rate_limit", new_callable=AsyncMock) as mock_rl:
        mock_rl.return_value = None
        resp = await authed_client.post(_LIBRARY_BASE_URL, json=payload)

    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"

    body = resp.json()
    assert "id" in body
    assert body["source"] == "find_papers"
    assert body["paper_info"]["id"] == str(test_paper.id)
    assert body["paper_info"]["title"] == test_paper.title
    assert body["expires_at"] is not None  # Free tier: 30 hari

    # Verifikasi LibraryPaper tersimpan di DB
    lp_id = uuid.UUID(body["id"])
    result = await db_session.execute(select(LibraryPaper).where(LibraryPaper.id == lp_id))
    db_lp = result.scalar_one_or_none()
    assert db_lp is not None, "LibraryPaper harus tersimpan di DB"
    assert db_lp.user_id == test_user.id
    assert db_lp.paper_id == test_paper.id
    assert db_lp.is_visible is True


# ═══════════════════════════════════════════════════════════════════════════
# l03 — POST /library/papers: save duplikat → 409
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_l03_save_paper_duplicate(
    authed_client: AsyncClient,
    test_library_paper: Any,
    test_paper: Any,
) -> None:
    """
    l03: POST /library/papers dengan paper yang sudah ada di library → 409.

    Expected:
    - 409 Conflict (LibraryDuplicateError)

    test_library_paper sudah menyimpan test_paper untuk test_user.
    Ref: Blueprint §4.3 — duplikasi check via (user_id, paper_id)
    """
    payload = {
        "paper_id": str(test_paper.id),
        "source": "find_papers",
    }

    with patch("app.api.v1.library.check_rate_limit", new_callable=AsyncMock) as mock_rl:
        mock_rl.return_value = None
        resp = await authed_client.post(_LIBRARY_BASE_URL, json=payload)

    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.text}"
    assert "detail" in resp.json()


# ═══════════════════════════════════════════════════════════════════════════
# l04 — POST /library/papers: paper_id tidak ada → 404
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_l04_save_paper_not_found(
    authed_client: AsyncClient,
) -> None:
    """
    l04: POST /library/papers dengan paper_id yang tidak ada di tabel papers → 404.

    Expected:
    - 404 Not Found

    _PAPER_UUID_MISSING tidak ada di DB.
    Ref: Blueprint §4.3 — FK validation paper_id
    """
    payload = {
        "paper_id": str(_PAPER_UUID_MISSING),
        "source": "find_papers",
    }

    with patch("app.api.v1.library.check_rate_limit", new_callable=AsyncMock) as mock_rl:
        mock_rl.return_value = None
        resp = await authed_client.post(_LIBRARY_BASE_URL, json=payload)

    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"
    assert "detail" in resp.json()


# ═══════════════════════════════════════════════════════════════════════════
# l05 — GET /library/papers/{id}: detail paper → 200 field lengkap
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_l05_get_paper_detail(
    authed_client: AsyncClient,
    test_library_paper: Any,
    test_paper: Any,
) -> None:
    """
    l05: GET /library/papers/{library_paper_id} → 200, field lengkap.

    Expected:
    - 200 OK
    - id, paper_info (title, authors, year), source, notes, tags,
      is_incomplete, expires_at, added_at

    Ref: Blueprint §4.3 GET /library/papers/{id}
    """
    url = f"{_LIBRARY_BASE_URL}/{test_library_paper.id}"
    resp = await authed_client.get(url)

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    body = resp.json()
    assert body["id"] == str(test_library_paper.id)
    assert body["source"] == "find_papers"
    assert body["notes"] == test_library_paper.notes
    assert body["tags"] == test_library_paper.tags

    paper_info = body["paper_info"]
    assert paper_info["id"] == str(test_paper.id)
    assert paper_info["title"] == test_paper.title
    assert paper_info["year"] == test_paper.year

    assert "added_at" in body
    assert body["expires_at"] is not None


# ═══════════════════════════════════════════════════════════════════════════
# l06 — GET /library/papers/{id}: tidak ditemukan → 404
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_l06_get_paper_not_found(
    authed_client: AsyncClient,
) -> None:
    """
    l06: GET /library/papers/{id} dengan UUID yang tidak ada → 404.

    Expected:
    - 404 Not Found (LibraryPaperNotFoundError)

    Ref: Blueprint §4.3
    """
    nonexistent_id = uuid.UUID("40000000-0000-0000-0000-000000000099")
    url = f"{_LIBRARY_BASE_URL}/{nonexistent_id}"

    resp = await authed_client.get(url)

    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"
    assert "detail" in resp.json()


# ═══════════════════════════════════════════════════════════════════════════
# l07 — GET /library/papers/{id}: milik user lain → 404
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_l07_get_paper_other_user(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    test_paper: Any,
) -> None:
    """
    l07: GET /library/papers/{id} untuk paper milik user lain → 404.

    Expected:
    - 404 Not Found (tidak bocorkan existence — 404 bukan 403)

    Buat LibraryPaper dengan user_id lain, GET sebagai test_user.
    Ref: Blueprint §4.3 — security: jangan expose milik user lain
    """
    other_lp = LibraryPaper(
        id=uuid.UUID("40000000-0000-0000-0000-000000000002"),
        user_id=_OTHER_USER_UUID,
        paper_id=test_paper.id,
        source="find_papers",
        is_visible=True,
    )
    db_session.add(other_lp)
    await db_session.flush()

    url = f"{_LIBRARY_BASE_URL}/{other_lp.id}"
    resp = await authed_client.get(url)

    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"


# ═══════════════════════════════════════════════════════════════════════════
# l08 — PATCH /library/papers/{id}: update notes dan tags → 200
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_l08_update_notes_and_tags(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    test_library_paper: Any,
) -> None:
    """
    l08: PATCH /library/papers/{id} dengan notes dan tags baru → 200.

    Expected:
    - 200 OK
    - notes dan tags terupdate di response dan DB

    Mock: check_rate_limit (no Redis)
    Ref: Blueprint §4.3 PATCH /library/papers/{id}
    """
    url = f"{_LIBRARY_BASE_URL}/{test_library_paper.id}"
    payload = {
        "notes": "Catatan diperbarui",
        "tags": ["machine-learning", "education"],
    }

    with patch("app.api.v1.library.check_rate_limit", new_callable=AsyncMock) as mock_rl:
        mock_rl.return_value = None
        resp = await authed_client.patch(url, json=payload)

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    body = resp.json()
    assert body["notes"] == "Catatan diperbarui"
    assert body["tags"] == ["machine-learning", "education"]

    # Verifikasi update di DB
    await db_session.refresh(test_library_paper)
    assert test_library_paper.notes == "Catatan diperbarui"
    assert test_library_paper.tags == ["machine-learning", "education"]


# ═══════════════════════════════════════════════════════════════════════════
# l09 — PATCH /library/papers/{id}: tags normalisasi → 200, ternormalisasi
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_l09_update_tags_normalization(
    authed_client: AsyncClient,
    test_library_paper: Any,
) -> None:
    """
    l09: PATCH /library/papers/{id} dengan tags mentah → 200, ternormalisasi.

    Payload raw:
      ["  NLP ", "nlp", "Python", ""]  ← duplikat + whitespace + kosong

    Expected response tags:
      ["nlp", "python"]  ← strip+lower+dedup, kosong dihapus

    Ref: Blueprint §2.2 G4, Step 6 LibraryPaperUpdate.normalize_tags()
    """
    url = f"{_LIBRARY_BASE_URL}/{test_library_paper.id}"
    payload = {"tags": ["  NLP ", "nlp", "Python", ""]}

    with patch("app.api.v1.library.check_rate_limit", new_callable=AsyncMock) as mock_rl:
        mock_rl.return_value = None
        resp = await authed_client.patch(url, json=payload)

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    assert resp.json()["tags"] == ["nlp", "python"]


# ═══════════════════════════════════════════════════════════════════════════
# l10 — PATCH /library/papers/{id}: tags > 10 item → 422
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_l10_update_tags_too_many(
    authed_client: AsyncClient,
    test_library_paper: Any,
) -> None:
    """
    l10: PATCH /library/papers/{id} dengan > 10 tags unik → 422.

    Payload: 11 tags unik (melewati limit maksimum 10)

    Expected:
    - 422 Unprocessable Entity

    Ref: Blueprint §2.2 G4 — max 10 tags, Step 6 normalize_tags()
    """
    url = f"{_LIBRARY_BASE_URL}/{test_library_paper.id}"
    payload = {"tags": [f"tag{i}" for i in range(11)]}

    with patch("app.api.v1.library.check_rate_limit", new_callable=AsyncMock) as mock_rl:
        mock_rl.return_value = None
        resp = await authed_client.patch(url, json=payload)

    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}: {resp.text}"
    assert "detail" in resp.json()


# ═══════════════════════════════════════════════════════════════════════════
# l11 — DELETE /library/papers/{id}: soft delete → 204
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_l11_delete_paper(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    test_library_paper: Any,
) -> None:
    """
    l11: DELETE /library/papers/{id} → 204 No Content.

    Expected:
    - 204 No Content (empty body)
    - DB row: is_visible=False, expired_at di-set (soft delete)

    Row TIDAK dihapus — hanya is_visible=False.
    Ref: Blueprint §4.3, §12.3 — soft delete pattern
    """
    url = f"{_LIBRARY_BASE_URL}/{test_library_paper.id}"

    with patch("app.api.v1.library.check_rate_limit", new_callable=AsyncMock) as mock_rl:
        mock_rl.return_value = None
        resp = await authed_client.delete(url)

    assert resp.status_code == 204, f"Expected 204, got {resp.status_code}: {resp.text}"
    assert resp.content == b"", "204 harus empty body"

    # Verifikasi soft delete di DB (row masih ada, is_visible=False)
    await db_session.refresh(test_library_paper)
    assert test_library_paper.is_visible is False
    assert test_library_paper.expired_at is not None


# ═══════════════════════════════════════════════════════════════════════════
# l12 — DELETE /library/papers/{id}: tidak ditemukan → 404
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_l12_delete_paper_not_found(
    authed_client: AsyncClient,
) -> None:
    """
    l12: DELETE /library/papers/{id} dengan UUID yang tidak ada → 404.

    Expected:
    - 404 Not Found (LibraryPaperNotFoundError)

    Ref: Blueprint §4.3
    """
    nonexistent_id = uuid.UUID("40000000-0000-0000-0000-000000000099")
    url = f"{_LIBRARY_BASE_URL}/{nonexistent_id}"

    with patch("app.api.v1.library.check_rate_limit", new_callable=AsyncMock) as mock_rl:
        mock_rl.return_value = None
        resp = await authed_client.delete(url)

    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"
    assert "detail" in resp.json()


# ═══════════════════════════════════════════════════════════════════════════
# l13 — GET /library/papers setelah delete → paper tidak muncul
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_l13_list_papers_after_delete(
    authed_client: AsyncClient,
    db_session: AsyncSession,
    test_library_paper: Any,
) -> None:
    """
    l13: GET /library/papers setelah soft delete → paper tidak muncul.

    Flow:
    1. test_library_paper ada (is_visible=True) → GET: total=1
    2. DELETE → soft delete (is_visible=False)
    3. GET → total=0, papers=[]

    Verifikasi bahwa GET hanya return is_visible=True papers.
    Ref: Blueprint §4.3 — filter WHERE is_visible=TRUE
    """
    # Step 1: Verifikasi paper muncul sebelum delete
    resp_before = await authed_client.get(_LIBRARY_BASE_URL)
    assert resp_before.status_code == 200
    body_before = resp_before.json()
    assert body_before["total"] == 1, f"Sebelum delete harus 1, got: {body_before['total']}"
    assert body_before["papers"][0]["id"] == str(test_library_paper.id)

    # Step 2: Soft delete
    delete_url = f"{_LIBRARY_BASE_URL}/{test_library_paper.id}"
    with patch("app.api.v1.library.check_rate_limit", new_callable=AsyncMock) as mock_rl:
        mock_rl.return_value = None
        del_resp = await authed_client.delete(delete_url)
    assert del_resp.status_code == 204

    # Step 3: Verifikasi tidak muncul setelah delete
    resp_after = await authed_client.get(_LIBRARY_BASE_URL)
    assert resp_after.status_code == 200
    body_after = resp_after.json()
    assert body_after["total"] == 0, f"Setelah delete harus 0, got: {body_after['total']}"
    assert body_after["papers"] == []
    assert body_after["quota"]["current_count"] == 0

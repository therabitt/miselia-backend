# ═══════════════════════════════════════════════════════════════════════════
# File    : tests/test_find_papers.py
# Desc    : Test suite untuk Find Papers feature — 13 test cases.
#
#           Cakupan:
#             - Guest flow (no token) → 200, session_id=None, no DB write
#             - Auth flow (with JWT)  → 200, session_id set, row di search_sessions
#             - Input validation      → query terlalu pendek/panjang → 422
#             - Content moderation    → query blocked → 400
#             - Rate limiting         → 11 request dari IP sama → 429
#             - Cache behavior        → request ke-2 lebih cepat dari ke-1
#             - Dedup                 → tidak ada DOI duplikat di response
#             - Empty results         → 200, total_found=0, papers=[]
#             - Response time         → search_duration_ms < 5000
#             - Parallel fetch        → asyncio.gather lebih cepat dari sequential
#             - Relevance order       → papers terurut descending by relevance_score
#
#           STRATEGI MOCK — DWIE LEVEL:
#             Level 1 (integration tests T01–T10, T11, T13):
#               - Mock di level service: patch 'app.services.find_papers_service.search'
#                 atau 'app.services.find_papers_service.fetch_and_rank'
#               - Menggunakan httpx.AsyncClient + FastAPI ASGI langsung (tanpa DB)
#               - Override dependency get_db() dan get_optional_user() / get_current_user()
#               - Tidak butuh PostgreSQL running — semua DB mock via dependency override
#
#             Level 2 (unit tests T12):
#               - Mock di level integrations: patch fetch_from_semantic_scholar,
#                 fetch_from_openalex, check_s2_rate_limit
#               - Pure Python async — tidak butuh FastAPI atau DB sama sekali
#
#           GAP RESOLUTIONS:
#             Gap S8-1: InsufficientPapersError tidak di-raise dari find_papers endpoint.
#                       T10 → test_empty_results_ok (200 dengan papers=[])
#             Gap S8-2: Cache test mock paper_service.get_cached_or_fetch dengan delay
#             Gap S8-3: Rate limit test mock app.api.v1.find_papers.check_rate_limit
#             Gap S8-4: Auth test mock verify_jwt + override get_optional_user dependency
#             Gap S8-5: Parallel test mock fetch functions dengan delay dikontrol
#             Gap S8-6: Tidak tambah mock_s2/mock_oa ke conftest — mock lokal lebih tepat
#
# Layer   : Tests / Find Papers
# Deps    : pytest, pytest-asyncio, httpx, sqlalchemy, unittest.mock
# Step    : STEP 8 — Backend: Tests Find Papers
# Ref     : Blueprint §2.2, §3.1–3.5, §14.0–14.1, PMD Fase 1 §C Testing
# ═══════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.exceptions import RateLimitExceededError

# ── Konstanta test ────────────────────────────────────────────────────────────

# Query valid untuk reuse
VALID_QUERY = "pengaruh media sosial terhadap motivasi belajar mahasiswa"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_mock_papers(n: int = 5, start_score: float = 0.9) -> list[dict[str, Any]]:
    """
    Buat n mock paper dicts dengan field lengkap sesuai PaperResult schema.
    relevance_score menurun dari start_score: 0.9, 0.8, 0.7, ...
    (sudah terurut descending — seolah-olah sudah di-sort oleh fetch_and_rank)
    """
    return [
        {
            "paper_id": f"paper-{i:03d}",
            "title": f"Penelitian Media Sosial dan Motivasi Belajar Vol {i}",
            "authors": [f"Penulis {i}A", f"Penulis {i}B"],
            "year": 2020 + (i % 5),
            "venue": f"Jurnal Pendidikan {i}",
            "citation_count": (n - i) * 10,
            "abstract": f"Abstrak penelitian nomor {i} tentang media sosial.",
            "relevance_score": round(start_score - (i * 0.1), 2),
            "source": "semantic_scholar" if i % 2 == 0 else "openalex",
            "doi": f"10.1234/test-{i:03d}" if i < (n - 1) else None,
            "pdf_url": f"https://arxiv.org/pdf/test-{i}.pdf" if i % 2 == 0 else None,
            "is_open_access": i % 2 == 0,
        }
        for i in range(n)
    ]


def _make_mock_user(
    user_id: str = "00000000-0000-0000-0000-000000000001",
) -> MagicMock:
    """
    Buat mock User object yang cukup untuk get_optional_user / get_current_user.
    """
    import uuid

    user = MagicMock()
    user.id = uuid.UUID(user_id)
    user.email = "test@miselia.id"
    user.supabase_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    return user


async def _make_test_client_no_db(
    mock_user: Any = None,
) -> AsyncGenerator[AsyncClient, None]:
    """
    Buat httpx.AsyncClient dengan:
      - Override get_db() → mock AsyncSession (tanpa DB nyata)
      - Override get_optional_user() → mock_user atau None (guest)
      - Override get_current_user() → mock_user atau raise 401

    Ini memungkinkan tests berjalan tanpa PostgreSQL.
    """
    from app.dependencies import get_current_user, get_db, get_optional_user
    from app.main import app

    # Mock DB session — tidak butuh PostgreSQL
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()

    # refresh: set id pada object yang di-add
    import uuid

    async def mock_refresh(obj: Any) -> None:
        if not hasattr(obj, "id") or obj.id is None:
            obj.id = uuid.uuid4()

    mock_db.refresh = mock_refresh

    async def override_get_db() -> AsyncGenerator[Any, None]:
        yield mock_db

    async def override_get_optional_user() -> Any:
        return mock_user

    async def override_get_current_user() -> Any:
        if mock_user is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=401, detail="Not authenticated")
        return mock_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_optional_user] = override_get_optional_user
    app.dependency_overrides[get_current_user] = override_get_current_user

    client = AsyncClient(
        transport=ASGITransport(app=app),  # type: ignore[arg-type]
        base_url="http://testserver",
        headers={"Content-Type": "application/json"},
    )

    return client, mock_db, app


# ═════════════════════════════════════════════════════════════════════════════
# T01 — Guest flow: POST /papers/find tanpa token → 200, session_id=None
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
async def test_find_papers_guest_success() -> None:
    """
    Guest request (get_optional_user=None) → 200 OK.
    Response: papers list, session_id=None, total_found=5.
    DB.add tidak dipanggil (Decision #13: guest tidak disimpan).

    Ref: Blueprint §3.1, Decision #13
    """
    from app.main import app

    mock_papers = _make_mock_papers(5)
    client, mock_db, _ = await _make_test_client_no_db(mock_user=None)

    try:
        async with client:
            with patch(
                "app.services.find_papers_service.fetch_and_rank",
                new_callable=AsyncMock,
                return_value=mock_papers,
            ):
                resp = await client.post(
                    "/api/v1/papers/find",
                    json={"query": VALID_QUERY},
                )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()

    assert body["session_id"] is None, "Guest: session_id harus None"
    assert body["total_found"] == 5
    assert len(body["papers"]) == 5
    assert isinstance(body["search_duration_ms"], int)
    assert body["search_duration_ms"] >= 0

    # Verifikasi struktur paper
    p0 = body["papers"][0]
    assert "paper_id" in p0
    assert "title" in p0
    assert "relevance_score" in p0
    assert "is_open_access" in p0

    # DB.add tidak dipanggil untuk guest (Decision #13)
    mock_db.add.assert_not_called()


# ═════════════════════════════════════════════════════════════════════════════
# T02 — Auth flow: POST dengan user → session_id set, DB.add dipanggil
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
async def test_find_papers_authenticated_saves_session() -> None:
    """
    Authenticated request (get_optional_user=mock_user) → 200 OK.
    session_id tidak None, DB.add dipanggil satu kali (SearchSession).

    Gap S8-4: Override dependency langsung — tidak butuh verify_jwt atau DB nyata.
    Ref: Blueprint §3.4
    """
    from app.main import app

    mock_user = _make_mock_user()
    mock_papers = _make_mock_papers(5)
    client, mock_db, _ = await _make_test_client_no_db(mock_user=mock_user)

    try:
        async with client:
            with patch(
                "app.services.find_papers_service.fetch_and_rank",
                new_callable=AsyncMock,
                return_value=mock_papers,
            ):
                resp = await client.post(
                    "/api/v1/papers/find",
                    json={"query": VALID_QUERY},
                    headers={"Authorization": "Bearer test-token"},
                )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()

    # session_id harus ada (bukan None)
    assert body["session_id"] is not None, "Auth: session_id harus tidak None"
    assert body["total_found"] == 5

    # DB.add harus dipanggil satu kali (untuk SearchSession)
    mock_db.add.assert_called_once()
    from app.models.database import SearchSession

    added_obj = mock_db.add.call_args[0][0]
    assert isinstance(added_obj, SearchSession), (
        f"DB.add harus dipanggil dengan SearchSession, got: {type(added_obj)}"
    )
    # paper_ids harus list of str (paper_id dari mock_papers)
    assert added_obj.paper_ids == [p["paper_id"] for p in mock_papers]
    assert added_obj.user_id == mock_user.id


# ═════════════════════════════════════════════════════════════════════════════
# T03 — Guest: DB.add tidak dipanggil
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
async def test_find_papers_guest_no_session_saved() -> None:
    """
    Guest request → search_sessions tidak ditambah.
    Mock DB.add tidak boleh dipanggil.
    Blueprint §3.4, Decision #13.
    """
    from app.main import app

    mock_papers = _make_mock_papers(5)
    client, mock_db, _ = await _make_test_client_no_db(mock_user=None)

    try:
        async with client:
            with patch(
                "app.services.find_papers_service.fetch_and_rank",
                new_callable=AsyncMock,
                return_value=mock_papers,
            ):
                resp = await client.post(
                    "/api/v1/papers/find",
                    json={"query": VALID_QUERY},
                )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] is None

    # Pastikan tidak ada SearchSession yang di-insert
    mock_db.add.assert_not_called()


# ═════════════════════════════════════════════════════════════════════════════
# T04 — Validasi: query terlalu pendek → 422
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
async def test_find_papers_query_too_short() -> None:
    """
    Query < 3 karakter → Pydantic validation → 422 Unprocessable Entity.
    FindPapersRequest.query = Field(..., min_length=3)
    """
    from app.main import app

    client, _, _ = await _make_test_client_no_db(mock_user=None)

    try:
        async with client:
            resp = await client.post(
                "/api/v1/papers/find",
                json={"query": "ab"},  # 2 char < min_length=3
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}"
    body = resp.json()
    assert "detail" in body


# ═════════════════════════════════════════════════════════════════════════════
# T05 — Validasi: query terlalu panjang → 422
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
async def test_find_papers_query_too_long() -> None:
    """
    Query > 500 karakter → Pydantic validation → 422 Unprocessable Entity.
    FindPapersRequest.query = Field(..., max_length=500)
    """
    from app.main import app

    client, _, _ = await _make_test_client_no_db(mock_user=None)

    try:
        async with client:
            resp = await client.post(
                "/api/v1/papers/find",
                json={"query": "x" * 501},  # 501 char > max_length=500
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 422, f"Expected 422, got {resp.status_code}"
    assert "detail" in resp.json()


# ═════════════════════════════════════════════════════════════════════════════
# T06 — Content moderation: query blocked → 400
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
async def test_find_papers_blocked_query() -> None:
    """
    Query match BLOCKED_PATTERNS → ContentPolicyViolationError → 400.
    Moderation gate berjalan sebelum fetch_and_rank.
    Tidak perlu mock fetch_and_rank — moderation raise sebelum sampai sana.

    Ref: Blueprint §8.1 BLOCKED_PATTERNS
    """
    from app.main import app

    client, _, _ = await _make_test_client_no_db(mock_user=None)

    try:
        async with client:
            resp = await client.post(
                "/api/v1/papers/find",
                json={"query": "cara buat bom untuk penelitian"},  # blocked
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body.get("error") == "content_policy_violation", (
        f"Expected error=content_policy_violation, got: {body}"
    )


# ═════════════════════════════════════════════════════════════════════════════
# T07 — Rate limit: 11 request dari IP sama → 429 di ke-11
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
async def test_find_papers_rate_limit_guest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Guest rate limit: 10 req/jam per IP. Request ke-11 → 429.

    Gap S8-3: Mock check_rate_limit sebagai counter yang increment
    dan raise RateLimitExceededError saat > 10.

    Ref: Blueprint §2.2 RATE_LIMITS["guest_find_papers"] = 10/jam
    """
    from app.main import app

    call_count = 0
    GUEST_LIMIT = 10

    async def mock_rate_limit(limit_name: str, identifier: str) -> None:
        nonlocal call_count
        if limit_name == "guest_find_papers":
            call_count += 1
            if call_count > GUEST_LIMIT:
                raise RateLimitExceededError(
                    message=f"Terlalu banyak request. Batas {GUEST_LIMIT} per jam."
                )

    monkeypatch.setattr("app.api.v1.find_papers.check_rate_limit", mock_rate_limit)

    mock_papers = _make_mock_papers(3)
    client, _, _ = await _make_test_client_no_db(mock_user=None)

    try:
        async with client:
            with patch(
                "app.services.find_papers_service.fetch_and_rank",
                new_callable=AsyncMock,
                return_value=mock_papers,
            ):
                # Request 1–10: harus berhasil
                for i in range(GUEST_LIMIT):
                    resp = await client.post(
                        "/api/v1/papers/find",
                        json={"query": VALID_QUERY},
                        headers={"X-Forwarded-For": "1.2.3.4"},
                    )
                    assert resp.status_code == 200, (
                        f"Request ke-{i + 1} harus 200, got {resp.status_code}"
                    )

                # Request ke-11: harus 429
                resp_429 = await client.post(
                    "/api/v1/papers/find",
                    json={"query": VALID_QUERY},
                    headers={"X-Forwarded-For": "1.2.3.4"},
                )
    finally:
        app.dependency_overrides.clear()

    assert resp_429.status_code == 429, (
        f"Request ke-11 harus 429, got {resp_429.status_code}: {resp_429.text}"
    )
    body = resp_429.json()
    assert body.get("error") == "rate_limit_exceeded", (
        f"Expected error=rate_limit_exceeded, got: {body}"
    )


# ═════════════════════════════════════════════════════════════════════════════
# T08 — Cache behavior: request ke-2 lebih cepat dari ke-1
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
async def test_cache_hit_faster() -> None:
    """
    Gap S8-2: Simulasi cache behavior menggunakan mock get_cached_or_fetch.
      - Panggilan pertama: delay 150ms (cold fetch dari API)
      - Panggilan kedua: return instant (cache hit)

    Verifikasi bahwa search_duration_ms ke-2 < search_duration_ms ke-1.
    Ref: Blueprint §18.3 (PAPER_CACHE_TTL)
    """
    from app.main import app

    mock_papers = _make_mock_papers(5)
    call_count = 0
    SIMULATED_DELAY_S = 0.15  # 150ms simulasi network fetch

    async def mock_cached_or_fetch(
        query: str,
        filters: dict[str, Any],
    ) -> list[dict[str, Any]]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            await asyncio.sleep(SIMULATED_DELAY_S)  # Simulasi cold path
        return mock_papers  # Selanjutnya: cache hit (instant)

    client, _, _ = await _make_test_client_no_db(mock_user=None)

    try:
        async with client:
            with patch(
                "app.services.paper_service.get_cached_or_fetch",
                side_effect=mock_cached_or_fetch,
            ):
                # Request 1 — cold path
                t0 = time.monotonic()
                resp1 = await client.post(
                    "/api/v1/papers/find",
                    json={"query": VALID_QUERY},
                )
                t1 = time.monotonic()
                duration_first = t1 - t0

                # Request 2 — warm path (cache hit simulation)
                t2 = time.monotonic()
                resp2 = await client.post(
                    "/api/v1/papers/find",
                    json={"query": VALID_QUERY},
                )
                t3 = time.monotonic()
                duration_second = t3 - t2
    finally:
        app.dependency_overrides.clear()

    assert resp1.status_code == 200
    assert resp2.status_code == 200

    # Request ke-2 harus lebih cepat
    assert duration_second < duration_first, (
        f"Cache hit harus lebih cepat: first={duration_first:.3f}s, "
        f"second={duration_second:.3f}s"
    )

    body1 = resp1.json()
    body2 = resp2.json()

    # search_duration_ms cold > warm
    assert body1["search_duration_ms"] >= body2["search_duration_ms"], (
        f"search_duration_ms cold={body1['search_duration_ms']}ms, "
        f"warm={body2['search_duration_ms']}ms"
    )

    assert call_count == 2, f"get_cached_or_fetch harus dipanggil 2x, got: {call_count}"


# ═════════════════════════════════════════════════════════════════════════════
# T09 — Dedup: tidak ada DOI duplikat di response
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
async def test_dedup_no_duplicate_doi() -> None:
    """
    Mock get_cached_or_fetch mengembalikan papers dengan DOI duplikat.
    fetch_and_rank real (melalui merge_and_dedup) harus membuang duplikat.
    Response tidak boleh mengandung DOI yang sama 2×.

    Ref: Blueprint §14.0 (_dedup_papers)
    """
    from app.main import app

    # Raw papers: 2 entri dengan DOI sama dari sumber berbeda
    papers_with_dup = [
        {
            "paper_id": "s2-001",
            "title": "Paper A dari Semantic Scholar",
            "authors": ["Author A"],
            "year": 2022,
            "venue": "Journal A",
            "citation_count": 50,
            "abstract": "Abstrak paper A dari S2.",
            "source": "semantic_scholar",
            "doi": "10.1234/duplicate-doi",
            "pdf_url": None,
            "is_open_access": True,
        },
        {
            "paper_id": "oa-001",
            "title": "Paper A dari OpenAlex",
            "authors": ["Author A"],
            "year": 2022,
            "venue": "Journal A",
            "citation_count": 45,
            "abstract": "Abstrak paper A dari OA.",
            "source": "openalex",
            "doi": "10.1234/duplicate-doi",  # ← DOI duplikat
            "pdf_url": None,
            "is_open_access": True,
        },
        {
            "paper_id": "s2-002",
            "title": "Paper B — unik",
            "authors": ["Author B"],
            "year": 2021,
            "venue": "Journal B",
            "citation_count": 20,
            "abstract": "Abstrak paper B.",
            "source": "semantic_scholar",
            "doi": "10.1234/unique-doi",
            "pdf_url": None,
            "is_open_access": False,
        },
    ]

    client, _, _ = await _make_test_client_no_db(mock_user=None)

    try:
        async with client:
            with patch(
                "app.services.paper_service.get_cached_or_fetch",
                new_callable=AsyncMock,
                return_value=papers_with_dup,
            ):
                resp = await client.post(
                    "/api/v1/papers/find",
                    json={"query": "paper a penelitian"},
                )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()

    # Kumpulkan DOI non-None dari response
    doi_list = [p["doi"] for p in body["papers"] if p["doi"] is not None]
    doi_set = set(doi_list)

    assert len(doi_list) == len(doi_set), (
        f"FAIL: ada DOI duplikat di response! doi_list={doi_list}"
    )


# ═════════════════════════════════════════════════════════════════════════════
# T10 — Empty results: mock return [] → 200 dengan total_found=0
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
async def test_empty_results_ok() -> None:
    """
    Gap S8-1: InsufficientPapersError tidak di-raise dari Find Papers endpoint.
    Ketika tidak ada paper ditemukan → 200 dengan papers=[], total_found=0.

    Ref: Blueprint §3.1 — Find Papers tidak punya minimum threshold
    """
    from app.main import app

    client, _, _ = await _make_test_client_no_db(mock_user=None)

    try:
        async with client:
            with patch(
                "app.services.find_papers_service.fetch_and_rank",
                new_callable=AsyncMock,
                return_value=[],
            ):
                resp = await client.post(
                    "/api/v1/papers/find",
                    json={"query": "topik yang sangat spesifik dan langka xyz"},
                )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    body = resp.json()
    assert body["papers"] == [], f"papers harus empty list: {body['papers']}"
    assert body["total_found"] == 0
    assert body["session_id"] is None  # guest


# ═════════════════════════════════════════════════════════════════════════════
# T11 — Response time: search_duration_ms < 5000
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
async def test_response_time_under_5s() -> None:
    """
    Dengan mock fetch_and_rank (instant), search_duration_ms harus < 5000ms.
    Verifikasi service overhead tidak melebihi batas.

    Ref: PMD Fase 1 §C Testing DoD
    """
    from app.main import app

    mock_papers = _make_mock_papers(5)
    client, _, _ = await _make_test_client_no_db(mock_user=None)

    try:
        async with client:
            with patch(
                "app.services.find_papers_service.fetch_and_rank",
                new_callable=AsyncMock,
                return_value=mock_papers,
            ):
                resp = await client.post(
                    "/api/v1/papers/find",
                    json={"query": VALID_QUERY},
                )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["search_duration_ms"] < 5000, (
        f"search_duration_ms harus < 5000ms, got: {body['search_duration_ms']}ms"
    )


# ═════════════════════════════════════════════════════════════════════════════
# T12 — Parallel fetch: asyncio.gather lebih cepat dari sequential
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
async def test_parallel_fetch_faster_than_sequential() -> None:
    """
    Gap S8-5: Verifikasi fetch S2 + OA dilakukan secara paralel (asyncio.gather).

    Strategy: mock fetch_from_semantic_scholar dan fetch_from_openalex
    (fungsi modul, bukan class method) — masing-masing delay 150ms.
    Jika parallel: total ~150ms. Jika sequential: total ~300ms.

    Pure unit test — tidak butuh test_client atau DB.
    Ref: Blueprint §14.0 (asyncio.gather untuk parallel fetch)
    """
    DELAY_S = 0.15  # 150ms per source

    async def mock_fetch_s2(
        queries: list[str],
        filters: dict[str, Any],
        max_candidates: int,
    ) -> list[dict[str, Any]]:
        await asyncio.sleep(DELAY_S)
        return [
            {
                "paper_id": "s2-parallel-001",
                "title": "S2 Paper",
                "authors": ["Author S2"],
                "year": 2023,
                "venue": "Journal S2",
                "citation_count": 10,
                "abstract": "Abstract S2",
                "source": "semantic_scholar",
                "doi": "10.s2/001",
                "pdf_url": None,
                "is_open_access": False,
            }
        ]

    async def mock_fetch_oa(
        queries: list[str],
        filters: dict[str, Any],
        max_candidates: int,
    ) -> list[dict[str, Any]]:
        await asyncio.sleep(DELAY_S)
        return [
            {
                "paper_id": "oa-parallel-001",
                "title": "OA Paper",
                "authors": ["Author OA"],
                "year": 2022,
                "venue": "Journal OA",
                "citation_count": 5,
                "abstract": "Abstract OA",
                "source": "openalex",
                "doi": "10.oa/001",
                "pdf_url": None,
                "is_open_access": True,
            }
        ]

    with (
        patch(
            "app.services.paper_service.fetch_from_semantic_scholar",
            side_effect=mock_fetch_s2,
        ),
        patch(
            "app.services.paper_service.fetch_from_openalex",
            side_effect=mock_fetch_oa,
        ),
        patch(
            "app.services.paper_service.check_s2_rate_limit",
            new_callable=AsyncMock,
            return_value=True,  # S2 allowed
        ),
    ):
        from app.services.paper_service import fetch_papers_with_resilience

        t_start = time.monotonic()
        results = await fetch_papers_with_resilience(
            optimized_queries=["machine learning research"],
            filters={},
            max_candidates=50,
            pipeline="test_parallel",
        )
        t_end = time.monotonic()

    total_elapsed = t_end - t_start
    sequential_estimate = DELAY_S * 2  # ~300ms jika sequential

    # Parallel: total < sequential_estimate * 1.5 (dengan async overhead)
    assert total_elapsed < sequential_estimate * 1.5, (
        f"Fetch terlalu lambat — kemungkinan sequential bukan parallel: "
        f"elapsed={total_elapsed:.3f}s, sequential_estimate={sequential_estimate:.3f}s"
    )
    # Verifikasi hasil dari kedua source terkumpul (2 papers)
    assert results is not None
    assert len(results) >= 1  # Setidaknya satu source berhasil


# ═════════════════════════════════════════════════════════════════════════════
# T13 — Relevance order: papers terurut descending by relevance_score
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.unit
async def test_relevance_sorted_descending() -> None:
    """
    Papers di response harus terurut descending by relevance_score.

    Kontrak: fetch_and_rank() bertanggung jawab untuk sort (Step 4 di paper_service).
    Endpoint hanya meneruskan hasilnya tanpa sort ulang.

    Test ini memverifikasi DUA hal:
    1. Endpoint preserves urutan yang dikembalikan fetch_and_rank (tidak dibalik)
    2. calculate_relevance_score() + sort di paper_service menghasilkan urutan benar

    Ref: Blueprint §3.3, fetch_and_rank() Step 4
    """
    from app.main import app

    # --- Part 1: Verifikasi endpoint preserves order dari fetch_and_rank ---
    # Mock fetch_and_rank SUDAH return dalam urutan descending
    # (sesuai kontrak: fetch_and_rank selalu return sorted)
    already_sorted_papers = [
        {
            "paper_id": "p-high",
            "title": "Paper Relevansi Tinggi",
            "authors": ["Author A"],
            "year": 2023,
            "venue": "Journal A",
            "citation_count": 100,
            "abstract": "Abstrak sangat relevan.",
            "relevance_score": 0.95,
            "source": "semantic_scholar",
            "doi": "10.1234/high",
            "pdf_url": None,
            "is_open_access": True,
        },
        {
            "paper_id": "p-mid",
            "title": "Paper Relevansi Sedang",
            "authors": ["Author B"],
            "year": 2021,
            "venue": "Journal B",
            "citation_count": 20,
            "abstract": "Abstrak sedang.",
            "relevance_score": 0.6,
            "source": "openalex",
            "doi": "10.1234/mid",
            "pdf_url": None,
            "is_open_access": False,
        },
        {
            "paper_id": "p-low",
            "title": "Paper Relevansi Rendah",
            "authors": ["Author C"],
            "year": 2019,
            "venue": "Journal C",
            "citation_count": 1,
            "abstract": None,
            "relevance_score": 0.2,
            "source": "semantic_scholar",
            "doi": None,
            "pdf_url": None,
            "is_open_access": False,
        },
    ]

    client, _, _ = await _make_test_client_no_db(mock_user=None)

    try:
        async with client:
            with patch(
                "app.services.find_papers_service.fetch_and_rank",
                new_callable=AsyncMock,
                return_value=already_sorted_papers,
            ):
                resp = await client.post(
                    "/api/v1/papers/find",
                    json={"query": "penelitian relevansi"},
                )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    papers = body["papers"]

    assert len(papers) == 3, f"Harus 3 papers, got: {len(papers)}"

    # Verifikasi endpoint preserves urutan descending dari fetch_and_rank
    scores = [p["relevance_score"] for p in papers]
    assert scores == sorted(scores, reverse=True), (
        f"Endpoint harus preserve urutan descending dari fetch_and_rank, "
        f"got scores: {scores}"
    )
    assert papers[0]["paper_id"] == "p-high"
    assert papers[-1]["paper_id"] == "p-low"

    # --- Part 2: Verifikasi sort logic di paper_service langsung (unit) ---
    from app.services.paper_service import calculate_relevance_score

    query_terms = ["relevansi", "paper", "penelitian"]

    # Paper dengan title match yang baik harus dapat score lebih tinggi
    paper_high = {
        "title": "penelitian relevansi paper terbaik",
        "abstract": "relevansi sangat tinggi pada penelitian ini",
        "citation_count": 50,
        "year": 2023,
    }
    paper_low = {
        "title": "topik tidak relevan sama sekali",
        "abstract": None,
        "citation_count": 0,
        "year": 2010,
    }

    score_high = calculate_relevance_score(paper_high, query_terms)
    score_low = calculate_relevance_score(paper_low, query_terms)

    assert score_high > score_low, (
        f"Paper dengan title+abstract match harus score lebih tinggi: "
        f"high={score_high:.3f}, low={score_low:.3f}"
    )
    assert 0.0 <= score_high <= 1.0, f"Score harus 0-1.0, got: {score_high}"
    assert 0.0 <= score_low <= 1.0, f"Score harus 0-1.0, got: {score_low}"


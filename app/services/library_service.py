# ═══════════════════════════════════════════════════════════════════════════
# File    : app/services/library_service.py
# Desc    : Library service — business logic untuk semua operasi Library.
#
#           Fungsi utama:
#             get_user_tier()                    — ambil tier aktif user dari DB.
#             check_library_quota()              — cek kuota library per tier.
#             get_library_papers()               — list paper dengan filter.
#             add_paper_to_library()             — simpan paper ke library.
#             update_library_paper()             — update notes/tags (partial).
#             remove_paper_from_library()        — soft delete paper.
#             restore_library_papers_on_upgrade() — restore paper expired saat upgrade.
#
#           Separation of concerns:
#             - Service layer: semua business rule, validasi, dan DB query.
#             - Endpoint layer: hanya HTTP concerns (parsing, response format).
#
#           Library MVP sources (Decision #12):
#             - 'find_papers': dari hasil Find Papers
#             - 'stage_run': di-push dari hasil pipeline
#             Import sources ('csv_import', 'bib_import', 'ris_import')
#             ditambahkan di Fase 5 (Decision #28, migration 028).
#
#           Soft delete flow (Decision #2):
#             remove_paper → is_visible=False, expired_at=NOW()
#             cleanup_expired_library_papers (Celery job) → hard delete setelah 90 hari
#             restore_library_papers_on_upgrade → restore dalam window 90 hari
#
#           Tier fallback (Decision #2):
#             User tanpa subscription row → tier='free' (fallback defensif).
#             grace_period dihitung sebagai tier aktif (Decision #1).
#
# Layer   : Services / Library
# Deps    : sqlalchemy, app.models.database, app.core.tier_config,
#           app.core.exceptions, app.core.logging
# Step    : STEP 3 — Fase 2
# Ref     : Blueprint §4.2, §6.12, §7.1, §12.3, Decision #2, #12, #28
# ═══════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Optional

from sqlalchemy import Text as SAText, and_, cast, func, select, update
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import (
    ForbiddenError,
    LibraryDuplicateError,
    LibraryPaperNotFoundError,
    LibraryQuotaExceededError,
    PaperNotFoundError,
)
from app.core.logging import get_logger
from app.core.tier_config import (
    LibraryQuotaInfo,
    SubscriptionTier,
    get_tier_config,
)
from app.models.database import LibraryPaper, Paper, Subscription

log = get_logger(__name__)

# ── Konstanta ─────────────────────────────────────────────────────────────

_NOTES_MAX_CHARS = 2000  # Blueprint §2.2 PATCH /library/papers/{id}
_TAGS_MAX_COUNT = 10  # Blueprint §2.2
_TAGS_MAX_CHAR_PER_ITEM = 30  # Blueprint §2.2
_FREE_EXPIRY_DAYS = 30  # Decision #2 — Free tier 30 hari aktif
_RESTORE_WINDOW_DAYS = 90  # Decision #2 — window restore setelah expired

# Source yang valid untuk MVP Library (Decision #12)
# csv_import/bib_import/ris_import ditambahkan di Fase 5 (Decision #28)
_VALID_MVP_SOURCES = frozenset(["find_papers", "stage_run"])


# ── Tier helper ───────────────────────────────────────────────────────────


async def get_user_tier(
    user_id: uuid.UUID,
    db: AsyncSession,
) -> str:
    """
    Return tier aktif user sebagai string ('free'|'sarjana'|'magister'|'institutional').

    Query tabel subscriptions untuk status 'active' atau 'grace_period'.
    grace_period masih dihitung sebagai tier aktif (Decision #1: grace 3 hari).

    Fallback ke 'free' jika:
    - Tidak ada subscription row sama sekali (user baru)
    - Semua subscription berstatus 'expired'

    Ref: Blueprint §7.1, Decision #1, Decision #2
    """
    result = await db.execute(
        select(Subscription.tier)
        .where(
            and_(
                Subscription.user_id == user_id,
                Subscription.status.in_(["active", "grace_period"]),
            )
        )
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )
    tier_str = result.scalar_one_or_none()

    if tier_str is None:
        log.debug("No active subscription found, defaulting to free", user_id=str(user_id))
        return SubscriptionTier.FREE.value

    return tier_str


# ── Quota helper ──────────────────────────────────────────────────────────


async def check_library_quota(
    user_id: uuid.UUID,
    tier: str,
    db: AsyncSession,
) -> LibraryQuotaInfo:
    """
    Cek kuota library user — return LibraryQuotaInfo (bukan bool).

    Return type diubah dari bool ke LibraryQuotaInfo per Decision #28
    untuk mendukung partial import (Fase 5): user bisa import sebagian
    jika slot tersisa tidak cukup untuk semua paper.

    current_count : paper is_visible=TRUE yang aktif saat ini
    max_count     : batas tier (None = unlimited untuk Magister)
    remaining     : sisa slot (None = unlimited)
    can_add_more  : True jika bisa tambah minimal 1 paper lagi

    Ref: Blueprint §4.3, Decision #28
    """
    config = get_tier_config(tier)
    max_count = config.max_library_papers

    # Hitung paper aktif (is_visible=TRUE)
    count_result = await db.execute(
        select(func.count(LibraryPaper.id)).where(
            and_(
                LibraryPaper.user_id == user_id,
                LibraryPaper.is_visible.is_(True),
            )
        )
    )
    current_count = count_result.scalar_one()

    if max_count is None:
        # Unlimited (Magister)
        return LibraryQuotaInfo(
            current_count=current_count,
            max_count=None,
            remaining=None,
            can_add_more=True,
        )

    remaining = max(0, max_count - current_count)
    return LibraryQuotaInfo(
        current_count=current_count,
        max_count=max_count,
        remaining=remaining,
        can_add_more=remaining > 0,
    )


# ── Get Library Papers ────────────────────────────────────────────────────


async def get_library_papers(
    user_id: uuid.UUID,
    db: AsyncSession,
    tags: Optional[list[str]] = None,
    source: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[LibraryPaper]:
    """
    Ambil daftar library papers milik user.

    Filter:
    - is_visible=TRUE selalu (paper expired tidak muncul di UI)
    - tags: filter GIN array containment (@> operator)
    - source: 'find_papers' atau 'stage_run'

    Order: added_at DESC (paper terbaru di atas).
    Eager load relationship 'paper' untuk title/authors/year
    tanpa N+1 query.

    Ref: Blueprint §4.2, §6.12
    """
    conditions = [
        LibraryPaper.user_id == user_id,
        LibraryPaper.is_visible.is_(True),
    ]

    if source is not None:
        conditions.append(LibraryPaper.source == source)

    if tags:
        # GIN array containment: WHERE tags @> ARRAY['tag1','tag2']
        # Hanya paper yang memiliki SEMUA tag yang diminta
        normalized_tags = [t.strip().lower() for t in tags if t.strip()]
        if normalized_tags:
            conditions.append(LibraryPaper.tags.contains(cast(normalized_tags, PG_ARRAY(SAText))))

    result = await db.execute(
        select(LibraryPaper)
        .options(selectinload(LibraryPaper.paper))
        .where(and_(*conditions))
        .order_by(LibraryPaper.added_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


# ── Add Paper to Library ──────────────────────────────────────────────────


async def add_paper_to_library(
    user_id: uuid.UUID,
    paper_id: uuid.UUID,
    source: str,
    db: AsyncSession,
    source_stage_run_id: Optional[uuid.UUID] = None,
) -> LibraryPaper:
    """
    Simpan paper ke library user.

    Flow:
    1. Validasi source (hanya MVP sources diizinkan di Fase 2).
    2. Cek kuota → raise LibraryQuotaExceededError jika penuh.
    3. Cek duplicate (user_id, paper_id) → raise LibraryDuplicateError.
    4. Hitung expires_at berdasarkan tier.
    5. INSERT library_papers.

    expires_at:
    - Free tier: added_at + 30 hari (Decision #2)
    - Sarjana/Magister/Institutional: NULL (permanent selama berlangganan)

    Raises:
        LibraryQuotaExceededError: kuota penuh.
        LibraryDuplicateError: paper sudah ada di library.

    Ref: Blueprint §4.2, §6.12, Decision #2, Decision #12
    """
    if source not in _VALID_MVP_SOURCES:
        raise ValueError(
            f"source '{source}' tidak valid di Fase 2. " f"Gunakan: {sorted(_VALID_MVP_SOURCES)}"
        )

    if source == "stage_run" and source_stage_run_id is None:
        log.warning(
            "add_paper_to_library: source=stage_run tapi source_stage_run_id=None",
            user_id=str(user_id),
            paper_id=str(paper_id),
        )

    # Cek kuota
    tier = await get_user_tier(user_id, db)
    quota = await check_library_quota(user_id, tier, db)

    if not quota.can_add_more:
        raise LibraryQuotaExceededError(
            message=(
                f"Library penuh ({quota.current_count}/{quota.max_count} paper). "
                "Upgrade untuk menyimpan lebih banyak paper."
            )
        )

    # Cek duplicate — gunakan query eksplisit, bukan coba INSERT dan catch IntegrityError
    # Alasan: IntegrityError membuat session dalam keadaan tidak valid (perlu rollback)
    dup_result = await db.execute(
        select(LibraryPaper.id).where(
            and_(
                LibraryPaper.user_id == user_id,
                LibraryPaper.paper_id == paper_id,
            )
        )
    )
    existing_id = dup_result.scalar_one_or_none()

    if existing_id is not None:
        raise LibraryDuplicateError()

    # Validasi paper_id existence di tabel papers
    # Mencegah FK IntegrityError (500) saat paper_id tidak ada.
    # Ref: Blueprint §4.3 POST /library/papers
    paper_exists = await db.execute(select(Paper.id).where(Paper.id == paper_id))
    if paper_exists.scalar_one_or_none() is None:
        raise PaperNotFoundError(message=f"Paper dengan id {paper_id} tidak ditemukan.")

    # Hitung expires_at berdasarkan tier
    now = datetime.now(UTC)
    expires_at: Optional[datetime] = None
    if tier == SubscriptionTier.FREE.value:
        expires_at = now + timedelta(days=_FREE_EXPIRY_DAYS)

    library_paper = LibraryPaper(
        user_id=user_id,
        paper_id=paper_id,
        source=source,
        source_stage_run_id=source_stage_run_id,
        is_visible=True,
        expires_at=expires_at,
        expired_at=None,
        is_incomplete=False,
    )

    db.add(library_paper)
    await db.commit()
    await db.refresh(library_paper)

    log.info(
        "paper added to library",
        user_id=str(user_id),
        paper_id=str(paper_id),
        source=source,
        tier=tier,
        expires_at=expires_at.isoformat() if expires_at else None,
    )

    return library_paper


# ── Update Library Paper ──────────────────────────────────────────────────


def _normalize_tags(raw_tags: list[str]) -> list[str]:
    """
    Normalisasi daftar tag sebelum disimpan ke DB.

    Aturan (Blueprint §2.2):
    - strip whitespace + lowercase setiap item
    - filter string kosong
    - deduplicate (preserve order pertama)
    - cap: max 10 item (raise ValidationError jika > 10 setelah filter)
    - cap: setiap item max 30 char (raise ValidationError jika ada yang > 30)
    """
    seen: set[str] = set()
    normalized: list[str] = []

    for raw in raw_tags:
        tag = raw.strip().lower()
        if not tag:
            continue
        if len(tag) > _TAGS_MAX_CHAR_PER_ITEM:
            from app.core.exceptions import MiseliaBaseError

            class TagTooLongError(MiseliaBaseError):
                status_code = 422
                error_code = "tag_too_long"
                message = f"Tag '{tag[:20]}...' melebihi {_TAGS_MAX_CHAR_PER_ITEM} karakter."

            raise TagTooLongError()
        if tag not in seen:
            seen.add(tag)
            normalized.append(tag)

    if len(normalized) > _TAGS_MAX_COUNT:
        from app.core.exceptions import MiseliaBaseError

        class TooManyTagsError(MiseliaBaseError):
            status_code = 422
            error_code = "too_many_tags"
            message = f"Maksimum {_TAGS_MAX_COUNT} tag per paper."

        raise TooManyTagsError()

    return normalized


async def update_library_paper(
    user_id: uuid.UUID,
    library_paper_id: uuid.UUID,
    db: AsyncSession,
    notes: Optional[str] = None,
    tags: Optional[list[str]] = None,
) -> LibraryPaper:
    """
    Update notes dan/atau tags sebuah library paper (partial update).

    Validasi:
    - Ownership: raise ForbiddenError jika bukan milik user.
    - notes: max 2000 karakter.
    - tags: strip+lower+dedup, max 10 item, max 30 char per item.

    Field yang tidak dikirim (None) tidak berubah.

    Ref: Blueprint §2.2, §4.2 PATCH /library/papers/{id}
    """
    # Ambil paper dan cek ownership sekaligus
    result = await db.execute(select(LibraryPaper).where(LibraryPaper.id == library_paper_id))
    library_paper = result.scalar_one_or_none()

    if library_paper is None:
        raise LibraryPaperNotFoundError()

    if library_paper.user_id != user_id:
        raise ForbiddenError(message="Paper ini bukan milik kamu.")

    changed = False

    if notes is not None:
        if len(notes) > _NOTES_MAX_CHARS:
            from app.core.exceptions import MiseliaBaseError

            class NotesTooLongError(MiseliaBaseError):
                status_code = 422
                error_code = "notes_too_long"
                message = f"Catatan melebihi {_NOTES_MAX_CHARS} karakter."

            raise NotesTooLongError()
        # String kosong = hapus notes (set ke None)
        library_paper.notes = notes.strip() or None
        changed = True

    if tags is not None:
        library_paper.tags = _normalize_tags(tags) or None  # [] → None
        changed = True

    if changed:
        await db.commit()
        await db.refresh(library_paper)

    return library_paper


# ── Remove Paper from Library ─────────────────────────────────────────────


async def remove_paper_from_library(
    user_id: uuid.UUID,
    library_paper_id: uuid.UUID,
    db: AsyncSession,
) -> None:
    """
    Soft delete paper dari library (is_visible=False, expired_at=NOW()).

    Alasan SOFT DELETE (bukan hard delete):
    - User yang upgrade dalam 90 hari bisa restore paper tanpa re-save manual.
    - "Psychological pull" untuk re-subscribe — user tahu data mereka masih ada.
    - Hard delete permanen dilakukan oleh job cleanup_expired_library_papers
      setelah 90 hari sejak expired_at.

    Raises:
        LibraryPaperNotFoundError: library paper tidak ditemukan.
        ForbiddenError: paper bukan milik user.

    Ref: Blueprint §4.2, §12.3, Decision #2
    """
    result = await db.execute(select(LibraryPaper).where(LibraryPaper.id == library_paper_id))
    library_paper = result.scalar_one_or_none()

    if library_paper is None:
        raise LibraryPaperNotFoundError()

    if library_paper.user_id != user_id:
        raise ForbiddenError(message="Paper ini bukan milik kamu.")

    now = datetime.now(UTC)
    library_paper.is_visible = False
    library_paper.expired_at = now

    await db.commit()

    log.info(
        "paper removed from library (soft delete)",
        user_id=str(user_id),
        library_paper_id=str(library_paper_id),
        expired_at=now.isoformat(),
    )


# ── Restore on Upgrade ────────────────────────────────────────────────────


async def restore_library_papers_on_upgrade(
    user_id: uuid.UUID,
    new_tier: str,
    db: AsyncSession,
) -> int:
    """
    Restore semua library paper yang soft-deleted setelah user upgrade.

    Dipanggil oleh subscription_service.py setelah payment settlement berhasil.

    Kondisi restore (Blueprint §12.3):
    - is_visible = FALSE (soft deleted)
    - expired_at IS NOT NULL
    - expired_at > NOW() - 90 hari (masih dalam window restore)

    Paper di luar window 90 hari sudah di-hard delete oleh cleanup job.
    Paper tersebut tidak bisa dikembalikan.

    expires_at baru berdasarkan new_tier:
    - Magister     : NULL (permanent)
    - Sarjana      : NOW() + 365 hari
    - Institutional: NOW() + 365 hari
    - Free         : NOW() + 30 hari (edge case: downgrade kemudian re-subscribe Free)

    Return:
        jumlah paper yang berhasil di-restore.

    Ref: Blueprint §12.3, Decision #2
    """
    now = datetime.now(UTC)
    window_cutoff = now - timedelta(days=_RESTORE_WINDOW_DAYS)

    # Hitung expires_at baru berdasarkan tier baru
    config = get_tier_config(new_tier)
    if config.library_retention_days is None:
        # Permanent (Magister)
        new_expires_at: Optional[datetime] = None
    else:
        new_expires_at = now + timedelta(days=config.library_retention_days)

    # UPDATE menggunakan SQLAlchemy ORM update statement (bulk, efisien)
    stmt = (
        update(LibraryPaper)
        .where(
            and_(
                LibraryPaper.user_id == user_id,
                LibraryPaper.is_visible.is_(False),
                LibraryPaper.expired_at.isnot(None),
                LibraryPaper.expired_at > window_cutoff,
            )
        )
        .values(
            is_visible=True,
            expires_at=new_expires_at,
            expired_at=None,
        )
        .execution_options(synchronize_session="fetch")
    )

    result = await db.execute(stmt)
    await db.commit()

    restored_count: int = result.rowcount

    log.info(
        "restore_library_papers_on_upgrade completed",
        user_id=str(user_id),
        new_tier=new_tier,
        restored_count=restored_count,
        new_expires_at=new_expires_at.isoformat() if new_expires_at else None,
    )

    return restored_count


# ── Get Single Library Paper ──────────────────────────────────────────────


async def get_library_paper_by_id(
    user_id: uuid.UUID,
    library_paper_id: uuid.UUID,
    db: AsyncSession,
) -> LibraryPaper:
    """
    Ambil satu library paper berdasarkan ID.

    Raise:
        LibraryPaperNotFoundError: tidak ditemukan atau sudah soft deleted.
        ForbiddenError: paper bukan milik user.

    is_visible=TRUE divalidasi — paper expired tidak bisa diakses
    melalui endpoint ini (sudah disembunyikan dari UI).

    Ref: Blueprint §4.2 GET /library/papers/{paper_id}
    """
    result = await db.execute(
        select(LibraryPaper)
        .options(selectinload(LibraryPaper.paper))
        .where(LibraryPaper.id == library_paper_id)
    )
    library_paper = result.scalar_one_or_none()

    if library_paper is None or not library_paper.is_visible:
        raise LibraryPaperNotFoundError()

    if library_paper.user_id != user_id:
        raise ForbiddenError(message="Paper ini bukan milik kamu.")

    return library_paper

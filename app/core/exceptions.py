# ═══════════════════════════════════════════════════════════════════════════
# File    : app/core/exceptions.py
# Desc    : Semua custom exceptions Miselia beserta HTTP status default-nya.
#           Exception handlers di-register di main.py.
# Layer   : Core / Exceptions
# Step    : STEP 3 — Backend Setup
# Ref     : Blueprint §2.2
# ═══════════════════════════════════════════════════════════════════════════

from typing import Optional


class MiseliaBaseError(Exception):
    """Base exception semua custom error Miselia."""

    status_code: int = 500
    error_code: str = "internal_error"
    message: str = "Terjadi kesalahan internal."

    def __init__(self, message: Optional[str] = None, **kwargs: object) -> None:
        self.message = message or self.__class__.message
        self.extra = kwargs
        super().__init__(self.message)


# ── Auth & Access ─────────────────────────────────────────────────────────


class UnauthorizedError(MiseliaBaseError):
    """JWT tidak valid atau tidak ada."""

    status_code = 401
    error_code = "unauthorized"
    message = "Autentikasi diperlukan."


class ForbiddenError(MiseliaBaseError):
    """User tidak punya izin untuk aksi ini."""

    status_code = 403
    error_code = "forbidden"
    message = "Akses ditolak."


class AdminRequiredError(MiseliaBaseError):
    """Endpoint ini hanya untuk admin."""

    status_code = 403
    error_code = "admin_required"
    message = "Akses admin diperlukan."


# ── Subscription & Tier ───────────────────────────────────────────────────


class SubscriptionRequiredError(MiseliaBaseError):
    """Fitur ini membutuhkan subscription aktif."""

    status_code = 402
    error_code = "subscription_required"
    message = "Upgrade subscription untuk menggunakan fitur ini."


class SubscriptionExpiredError(MiseliaBaseError):
    """Subscription sudah expired (melewati grace period)."""

    status_code = 402
    error_code = "subscription_expired"
    message = "Subscription kamu sudah berakhir. Perpanjang untuk melanjutkan."


class ProjectQuotaExceededError(MiseliaBaseError):
    """User sudah mencapai batas project aktif untuk tier-nya."""

    status_code = 403
    error_code = "project_quota_exceeded"
    message = "Batas project aktif tercapai. Upgrade atau archive project lama."


class StageNotAllowedError(MiseliaBaseError):
    """Stage type tidak tersedia untuk tier user saat ini."""

    status_code = 403
    error_code = "stage_not_allowed"
    message = "Pipeline ini tidak tersedia di tier kamu."


class StageRunLimitReachedError(MiseliaBaseError):
    """Free tier mencapai batas re-run (3x). Decision #8"""

    status_code = 403
    error_code = "stage_run_limit_reached"
    message = "Batas re-run tercapai. Upgrade untuk run tidak terbatas."


# ── Pipeline & Stage ──────────────────────────────────────────────────────


class PipelineDependencyError(MiseliaBaseError):
    """Pipeline dependency belum selesai (contoh: P2 butuh P1 completed)."""

    status_code = 422
    error_code = "pipeline_dependency_error"
    message = "Pipeline sebelumnya harus diselesaikan terlebih dahulu."


class ReviewTypeMismatchError(MiseliaBaseError):
    """P7 dijalankan di project non-systematic atau sebaliknya. Decision #19"""

    status_code = 422
    error_code = "review_type_mismatch"
    message = "Pipeline ini tidak sesuai dengan tipe review project."


class InsufficientPapersError(MiseliaBaseError):
    """Paper yang ditemukan kurang dari MIN_PAPERS_FOR_RUN (5). Blueprint §19.5"""

    status_code = 422
    error_code = "insufficient_papers"
    message = "Paper terlalu sedikit untuk menjalankan pipeline."

    def __init__(
        self,
        paper_count: int = 0,
        topic: str = "",
        suggestions: Optional[list[str]] = None,
    ) -> None:
        self.paper_count = paper_count
        self.topic = topic
        self.suggestions = suggestions or []
        super().__init__(
            message=f"Hanya ditemukan {paper_count} paper untuk topik ini. "
            "Minimal 5 paper dibutuhkan."
        )


class AIAllProvidersFailedError(MiseliaBaseError):
    """Semua AI provider gagal (GPT-4o + Claude + Gemini). Decision #23"""

    status_code = 503
    error_code = "ai_all_providers_failed"
    message = "Pipeline gagal diproses. Coba lagi dalam beberapa menit."


class StageRunNotFoundError(MiseliaBaseError):
    """Stage run tidak ditemukan atau bukan milik user ini."""

    status_code = 404
    error_code = "stage_run_not_found"
    message = "Pipeline tidak ditemukan."


class ProjectNotFoundError(MiseliaBaseError):
    """Project tidak ditemukan atau bukan milik user ini."""

    status_code = 404
    error_code = "project_not_found"
    message = "Project tidak ditemukan."


# ── Chat ──────────────────────────────────────────────────────────────────


class ChatSessionLimitReachedError(MiseliaBaseError):
    """User mencapai batas sesi chat bulanan (Free: 3/bulan). Decision #11"""

    status_code = 403
    error_code = "chat_session_limit_reached"
    message = "Batas sesi chat bulanan tercapai. Upgrade untuk sesi tidak terbatas."


class ChatMessageLimitReachedError(MiseliaBaseError):
    """User mencapai batas pesan per sesi (Free: 5 pesan). Decision #11"""

    status_code = 403
    error_code = "chat_message_limit_reached"
    message = "Batas pesan tercapai. Upgrade untuk chat tidak terbatas."


class ChatSessionNotFoundError(MiseliaBaseError):
    """Sesi chat tidak ditemukan atau sudah expired."""

    status_code = 404
    error_code = "chat_session_not_found"
    message = "Sesi chat tidak ditemukan."


# ── Library ───────────────────────────────────────────────────────────────


class LibraryPaperNotFoundError(MiseliaBaseError):
    """Paper tidak ditemukan di library user."""

    status_code = 404
    error_code = "library_paper_not_found"
    message = "Paper tidak ditemukan di library."


class LibraryQuotaExceededError(MiseliaBaseError):
    """Library sudah penuh sesuai batas tier. Decision #28"""

    status_code = 403
    error_code = "library_quota_exceeded"
    message = "Library sudah penuh. Upgrade untuk menyimpan lebih banyak paper."


# ── Import ────────────────────────────────────────────────────────────────


class PreviewExpiredError(MiseliaBaseError):
    """Import preview sudah kadaluarsa (Redis TTL 10 menit). Decision #28"""

    status_code = 410
    error_code = "preview_expired"
    message = "Sesi import kadaluarsa. Upload ulang file untuk melanjutkan."


class ImportParseError(MiseliaBaseError):
    """File import tidak bisa dibaca / format tidak valid."""

    status_code = 422
    error_code = "import_parse_failed"
    message = "File tidak bisa dibaca. Pastikan format file sudah benar."


# ── Content Moderation ────────────────────────────────────────────────────


class ContentPolicyViolationError(MiseliaBaseError):
    """Konten melanggar kebijakan penggunaan (Decision #29)."""

    status_code = 400
    error_code = "content_policy_violation"
    message = "Topik ini tidak bisa diproses. Coba ubah framing pertanyaanmu."


# ── Rate Limit ────────────────────────────────────────────────────────────


class RateLimitExceededError(MiseliaBaseError):
    """Request terlalu sering dalam waktu singkat."""

    status_code = 429
    error_code = "rate_limit_exceeded"
    message = "Terlalu banyak request. Coba lagi setelah beberapa saat."


# ── Payment ───────────────────────────────────────────────────────────────


class PaymentNotFoundError(MiseliaBaseError):
    """Transaksi pembayaran tidak ditemukan."""

    status_code = 404
    error_code = "payment_not_found"
    message = "Transaksi tidak ditemukan."


class WebhookVerificationFailedError(MiseliaBaseError):
    """Signature Midtrans webhook tidak valid."""

    status_code = 400
    error_code = "webhook_verification_failed"
    message = "Webhook tidak valid."

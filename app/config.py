# ═══════════════════════════════════════════════════════════════════════════
# File    : app/config.py
# Desc    : Pydantic BaseSettings — semua env vars dari Blueprint Appendix A.
#           Gunakan settings object ini di seluruh aplikasi.
#           JANGAN gunakan os.environ langsung.
# Layer   : Config
# Deps    : pydantic-settings
# Step    : STEP 3 — Backend Setup
# Ref     : Blueprint Appendix A
# ═══════════════════════════════════════════════════════════════════════════

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Database ──────────────────────────────────────────────────────────
    DATABASE_URL: str
    DATABASE_URL_TEST: Optional[str] = None
    SUPABASE_URL: str
    SUPABASE_SERVICE_ROLE_KEY: str
    SUPABASE_JWT_SECRET: str

    # ── Redis ─────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── OpenAI ───────────────────────────────────────────────────────────
    OPENAI_API_KEY: str
    OPENAI_MODEL: str = "gpt-4o"
    OPENAI_MAX_TOKENS: int = 4096

    # ── AI Fallback — Decision #23 ────────────────────────────────────────
    ANTHROPIC_API_KEY: Optional[str] = None
    GOOGLE_AI_API_KEY: Optional[str] = None
    AI_FALLBACK_ENABLED: bool = True

    # ── Paper APIs ────────────────────────────────────────────────────────
    SEMANTIC_SCHOLAR_API_KEY: Optional[str] = None
    OPENALEX_EMAIL: str = "dev@miselia.id"

    # ── Payment — Midtrans ────────────────────────────────────────────────
    MIDTRANS_SERVER_KEY: str = ""
    MIDTRANS_CLIENT_KEY: str = ""
    MIDTRANS_IS_PRODUCTION: bool = False
    MIDTRANS_WEBHOOK_SECRET: str = ""

    # ── Storage — Cloudflare R2 ───────────────────────────────────────────
    CLOUDFLARE_R2_ACCOUNT_ID: str = ""
    CLOUDFLARE_R2_ACCESS_KEY: str = ""
    CLOUDFLARE_R2_SECRET_KEY: str = ""
    CLOUDFLARE_R2_BUCKET_NAME: str = "miselia-outputs"

    # ── Email — Resend ────────────────────────────────────────────────────
    RESEND_API_KEY: str = ""
    EMAIL_FROM: str = "noreply@miselia.id"

    # ── App ───────────────────────────────────────────────────────────────
    APP_ENV: str = "development"
    APP_SECRET_KEY: str = "change-me-in-production"
    FRONTEND_URL: str = "http://localhost:3000"
    ADMIN_IP_WHITELIST: str = "127.0.0.1"

    # ── Monitoring ────────────────────────────────────────────────────────
    SENTRY_DSN: Optional[str] = None

    # ── Analytics — PostHog ──────────────────────────────────────────────
    POSTHOG_PROJECT_API_KEY: Optional[str] = None
    POSTHOG_HOST: str = "https://app.posthog.com"

    # ── Cache ────────────────────────────────────────────────────────
    PAPER_CACHE_TTL: int = 86400

    # ── Helpers ───────────────────────────────────────────────────────────
    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def is_development(self) -> bool:
        return self.APP_ENV == "development"

    @property
    def admin_ip_list(self) -> list[str]:
        return [ip.strip() for ip in self.ADMIN_IP_WHITELIST.split(",")]

    @property
    def allowed_origins(self) -> list[str]:
        origins = [self.FRONTEND_URL]
        if not self.is_production:
            origins.extend(
                [
                    "http://localhost:3000",
                    "http://127.0.0.1:3000",
                ]
            )
        return origins

    @property
    def async_database_url(self) -> str:
        """Convert postgres:// ke postgresql+asyncpg:// untuk SQLAlchemy async."""
        url = self.DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings: Settings = get_settings()

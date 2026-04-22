# ═══════════════════════════════════════════════════════════════════════════
# File    : app/core/rate_limit.py
# Desc    : Rate limiting menggunakan Redis INCR+EXPIRE pattern.
#           Rules sesuai Blueprint §2.2:
#             - guest find_papers     : 10 req/jam per IP
#             - auth find_papers      : 60 req/jam per user
#             - pipeline submit       : 20 req/jam per user
#             - chat messages         : 100 req/jam per user
# Layer   : Core / Rate Limit
# Deps    : redis, app.config
# Step    : STEP 3 — Backend Setup
# Ref     : Blueprint §2.2
# ═══════════════════════════════════════════════════════════════════════════

from dataclasses import dataclass
from typing import Optional

import redis.asyncio as aioredis

from app.config import settings
from app.core.exceptions import RateLimitExceeded

# ── Rate limit rules (requests per hour) ─────────────────────────────────


@dataclass(frozen=True)
class RateLimitRule:
    key_prefix: str
    max_requests: int
    window_seconds: int = 3600  # 1 jam default


RATE_LIMITS = {
    "guest_find_papers": RateLimitRule("rl:guest:fp", max_requests=10),
    "auth_find_papers": RateLimitRule("rl:auth:fp", max_requests=60),
    "pipeline_submit": RateLimitRule("rl:pipeline", max_requests=20),
    "chat_messages": RateLimitRule("rl:chat", max_requests=100),
}

# ── Redis client (lazy init) ─────────────────────────────────────────────

_redis_client: Optional[aioredis.Redis] = None


def get_redis() -> aioredis.Redis:
    """Lazy-init Redis client singleton."""
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


# ── Core check function ───────────────────────────────────────────────────


async def check_rate_limit(
    limit_name: str,
    identifier: str,  # IP address atau user_id
) -> None:
    """
    Cek dan increment counter rate limit.
    Raise RateLimitExceeded jika melampaui batas.

    Pattern: Redis INCR key → set EXPIRE jika baru → cek vs max_requests.
    Atomic per-key (single INCR tidak perlu transaction).
    """
    rule = RATE_LIMITS.get(limit_name)
    if rule is None:
        return  # Unknown limit — skip (fail open)

    redis = get_redis()
    key = f"{rule.key_prefix}:{identifier}"

    try:
        count = await redis.incr(key)
        if count == 1:
            # Key baru — set TTL
            await redis.expire(key, rule.window_seconds)

        if count > rule.max_requests:
            raise RateLimitExceeded(
                message=f"Terlalu banyak request. " f"Batas {rule.max_requests} per jam tercapai."
            )
    except RateLimitExceeded:
        raise
    except Exception:
        # Redis down → fail open (jangan block request karena infra issue)
        pass


async def get_remaining(limit_name: str, identifier: str) -> Optional[int]:
    """Return sisa request yang diizinkan, atau None jika Redis tidak available."""
    rule = RATE_LIMITS.get(limit_name)
    if rule is None:
        return None

    redis = get_redis()
    key = f"{rule.key_prefix}:{identifier}"
    try:
        count = await redis.get(key)
        current = int(count) if count else 0
        return max(0, rule.max_requests - current)
    except Exception:
        return None

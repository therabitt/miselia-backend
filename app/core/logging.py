# ═══════════════════════════════════════════════════════════════════════════
# File    : app/core/logging.py
# Desc    : Konfigurasi structlog — JSON formatter untuk production,
#           colored console untuk development.
#           Panggil configure_logging() sekali di app startup (main.py).
# Layer   : Core / Logging
# Deps    : structlog
# Step    : STEP 3 — Backend Setup
# Ref     : Blueprint §2.2
# ═══════════════════════════════════════════════════════════════════════════

import logging
import sys
from typing import Any

import structlog


def configure_logging(is_production: bool = False) -> None:
    """
    Inisialisasi structlog. Dipanggil sekali saat FastAPI startup.
    Production: JSON output ke stdout (Railway log aggregation).
    Development: colored + pretty output ke stdout.
    """
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if is_production:
        processors: list[Any] = shared_processors + [
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ]
    else:
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Atur stdlib logging level juga (untuk library yang pakai stdlib logging)
    log_level = logging.WARNING if is_production else logging.INFO
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )
    # Suppress noisy libraries di production
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING if is_production else logging.INFO)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Shorthand untuk mendapatkan logger bernama."""
    return structlog.get_logger(name)

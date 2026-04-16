# ═════════════════════════════════════════════════════════════════════════════
# File    : Dockerfile
# Desc    : Multi-stage Dockerfile untuk Miselia backend.
#           Stage:
#             base   — Python + system libs (shared oleh api dan worker)
#             api    — FastAPI + uvicorn (Railway API service)
#             worker — Celery worker (Railway Worker service)
#
#           System libraries yang diinstall di stage base:
#             libpango-1.0-0     — WeasyPrint text layout engine
#             libcairo2          — WeasyPrint + cairosvg rendering
#             libgdk-pixbuf2.0-0 — WeasyPrint image processing
#             libffi-dev         — C extension dependencies
#           Ref: Blueprint §16.4, PMD Fase 0 DevOps
#
#           Railway deployment:
#             API service    : target=api, CMD uvicorn (default port 8000)
#             Worker service : target=worker, CMD celery pipeline_normal+heavy
#             Beat service   : target=worker, CMD override → celery beat
#             Chat worker    : target=worker, CMD override → celery chat_realtime
#
# Step    : STEP 9 — Backend: Dockerfile
# Ref     : Blueprint §2.2, §16.4, §18.4, PMD Fase 0
# ═════════════════════════════════════════════════════════════════════════════

# ═════════════════════════════════════════════════════════════════════════════
# STAGE 1: base — Python + system libraries
# Shared oleh api dan worker — diinstall sekali, tidak diulangi
# ═════════════════════════════════════════════════════════════════════════════

FROM python:3.12-slim AS base

# Labels untuk Railway metadata
LABEL maintainer="Miselia <dev@miselia.id>"
LABEL service="miselia-backend"

# Env vars untuk Python behavior di container
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    # Pip — tidak perlu cache di container
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=100

# ── System libraries ──────────────────────────────────────────────────────
# WeasyPrint + cairosvg membutuhkan library Cairo, Pango, GDK-Pixbuf
# Ref: Blueprint §16.4 — tanpa ini WeasyPrint (P8 PDF) dan cairosvg (P7 PRISMA) crash
RUN apt-get update && apt-get install -y --no-install-recommends \
    # WeasyPrint dependencies
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libpangocairo-1.0-0 \
    # Cairo — untuk WeasyPrint dan cairosvg
    libcairo2 \
    # GDK-PixBuf — image processing di WeasyPrint
    libgdk-pixbuf2.0-0 \
    # FFI — C extension dependencies
    libffi-dev \
    # Font rendering (diperlukan WeasyPrint untuk render font di PDF)
    fontconfig \
    fonts-liberation \
    # Curl untuk healthcheck
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && fc-cache -f -v

WORKDIR /app

# ── Install Python dependencies ───────────────────────────────────────────
# Copy requirements terlebih dahulu (Docker layer caching)
# Jika requirements tidak berubah, layer ini tidak di-rebuild
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# ── Copy application code ─────────────────────────────────────────────────
# .dockerignore mengecualikan .venv, tests, .env, __pycache__, dll.
COPY . .


# ═════════════════════════════════════════════════════════════════════════════
# STAGE 2: api — FastAPI + Uvicorn
# Railway API service
# ═════════════════════════════════════════════════════════════════════════════

FROM base AS api

# Railway mengekspos port melalui environment variable PORT
# Default 8000 jika PORT tidak di-set
ENV PORT=8000

# Healthcheck untuk Railway liveness probe
# Railway juga bisa konfigurasi via dashboard, tapi ini sebagai fallback
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:${PORT}/api/v1/health || exit 1

EXPOSE ${PORT}

# CMD: uvicorn dengan workers sesuai CPU tersedia
# Railway Pro: 2 vCPU → 2 workers cukup (lebih dari ini bisa OOM)
# Gunakan --workers 1 untuk predictable memory di Railway Starter
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --log-level info"]


# ═════════════════════════════════════════════════════════════════════════════
# STAGE 3: worker — Celery
# Railway Worker service (pipeline_normal + pipeline_heavy)
#
# Railway service-level CMD override untuk tipe worker berbeda:
#   pipeline worker (default): celery -A app.workers worker --queues=pipeline_normal,pipeline_heavy --concurrency=4
#   chat worker:    celery -A app.workers worker --queues=chat_realtime --concurrency=6
#   beat scheduler: celery -A app.workers beat --loglevel=info
#
# Ref: Blueprint §18.4
# ═════════════════════════════════════════════════════════════════════════════

FROM base AS worker

# Default CMD: pipeline worker (pipeline_normal + pipeline_heavy)
# Railway Beat service dan Chat worker service override CMD ini via Railway dashboard
CMD ["celery", "-A", "app.workers", "worker", \
     "--queues=pipeline_normal,pipeline_heavy", \
     "--concurrency=4", \
     "--loglevel=info", \
     "--without-gossip", \
     "--without-mingle", \
     "--without-heartbeat"]

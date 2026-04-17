# syntax=docker/dockerfile:1.7
#
# Job Application App - Phase 1 base image.
#
# Why Playwright base NOW (even though Phase 1 does not use Playwright):
#   Phase 6 adds browser-driven ATS flows on Playwright. Shipping the Playwright
#   base image from day one avoids a mid-project rebuild of every downstream
#   layer, and keeps the system-level browser dependencies consistent with
#   STACK.md (v1.58.0-noble).
#
# Why --workers 1 is LOAD-BEARING:
#   APScheduler (3.11.x) runs in-process as an AsyncIOScheduler. Multiple uvicorn
#   workers would spawn multiple schedulers, double-firing cron jobs, corrupting
#   rate-limit counters and producing duplicate runs. This is a documented pitfall
#   in RESEARCH.md. Do NOT change --workers without also redesigning the scheduler
#   (move to an external scheduler/queue), otherwise data integrity will silently
#   break. The /health endpoint is expected to expose worker_pid for sanity checks.

FROM mcr.microsoft.com/playwright/python:v1.58.0-noble

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    ALEMBIC_DATABASE_URL=sqlite:////data/app.db

# Non-root application user (uid 1000)
# The Playwright base image may already have GID/UID 1000, so create only if missing.
RUN getent group 1000 >/dev/null || groupadd --system --gid 1000 app; \
    id -u 1000 >/dev/null 2>&1 || useradd --system --uid 1000 --gid $(getent group 1000 | cut -d: -f1) --home /app --shell /bin/bash app

WORKDIR /app

# Dependency layer first for caching
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# App source
COPY . /app

# Host-mounted data directory (SQLite, logs, uploads, browser state)
RUN mkdir -p /data && chown -R 1000:1000 /data /app

USER 1000

EXPOSE 8000

# See header: --workers 1 is required by APScheduler singleton invariant.
# Run Alembic migrations before starting the app so tables exist on first boot.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"]

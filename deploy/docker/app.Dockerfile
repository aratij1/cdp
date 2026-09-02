# Shared application image for apps/* and workers/* (Phase 1-3 CPU-only
# services). GPU/ML-heavy services (LayoutLMv3, VLM) get their own image
# in later phases (see docs/IMPLEMENTATION_PLAN.md Phase 4) built off the
# `[ml]` extras group instead of this one.
FROM python:3.11-slim AS base

# libglib2.0-0: required at import time by opencv-python-headless on slim
# Debian images even though it doesn't need a display.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY packages ./packages
COPY apps ./apps
COPY workers ./workers
COPY config ./config

RUN pip install --no-cache-dir .

# Non-root runtime user
RUN useradd --create-home --uid 1000 appuser

# /data holds append-only local sinks (OCR call audit log, correction
# memory) written by workers/apps at runtime; must be writable by appuser.
RUN mkdir -p /data && chown -R appuser:appuser /data

USER appuser

ENTRYPOINT []

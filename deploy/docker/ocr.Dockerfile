# Worker image for the two page/field OCR consumers (page_detection,
# standard_form_extraction). Built off the `[ocr]` extras group only
# (paddleocr + paddlepaddle, CPU) -- not the full `[ml]` group, which also
# pulls in torch/transformers for LayoutLMv3/Table Transformer that these
# two workers never import. Keeps this image's build time and size down
# until those later-phase workers get their own image.
FROM python:3.11-slim AS base

# libglib2.0-0: required at import time by opencv-python-headless.
# libgomp1: required at import time by paddlepaddle (OpenMP runtime).
# libgl1/libsm6/libxext6: paddleocr/paddlex pull in full `opencv-contrib-
# python` (not the `-headless` variant this project depends on directly),
# which dlopens libGL/libSM/libXext at import time even though nothing
# here ever opens a display.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgomp1 \
    libgl1 \
    libsm6 \
    libxext6 \
    tesseract-ocr \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY packages ./packages
COPY apps ./apps
COPY workers ./workers
COPY config ./config

RUN pip install --no-cache-dir ".[ocr]"

# Non-root runtime user
RUN useradd --create-home --uid 1000 appuser

# /data holds append-only local sinks (OCR call audit log, correction
# memory) written by workers/apps at runtime; must be writable by appuser.
RUN mkdir -p /data && chown -R appuser:appuser /data

USER appuser

ENTRYPOINT []

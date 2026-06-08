# SPDX-FileCopyrightText: 2026 JLay2026
# SPDX-License-Identifier: MIT

FROM python:3.11-slim-bookworm

# OpenCascade Python wheel (OCP) + matplotlib font rendering need these
# system libraries. Kept minimal vs other build123d-wrapper images.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
        libfontconfig1 \
        libfreetype6 \
    && rm -rf /var/lib/apt/lists/*

ENV MPLBACKEND=Agg \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Non-root from day 1. No /renders or /workspace write-permission gotchas
# because both are chowned to this user before we drop privileges.
RUN useradd --uid 1000 --create-home --shell /bin/bash app

WORKDIR /app

COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

RUN mkdir -p /workspace /renders && \
    chown -R 1000:1000 /workspace /renders /app

USER 1000

EXPOSE 8123

ENTRYPOINT ["./entrypoint.sh"]
CMD ["serve"]

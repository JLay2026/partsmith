#!/bin/bash
# SPDX-FileCopyrightText: 2026 JLay2026
# SPDX-License-Identifier: MIT
set -e

case "$1" in
    serve)
        # --proxy-headers + --forwarded-allow-ips: trust X-Forwarded-*
        # headers from any source. Required when running behind a reverse
        # proxy (Caddy) in a container — without this, uvicorn ignores
        # X-Forwarded-Proto from the proxy because the source IP isn't
        # 127.0.0.1, and redirects come back with http:// instead of
        # https://. Safe here because the container's port is only
        # reachable from the docker-compose network (loopback bind on
        # the host).
        exec python -m uvicorn src.server:app \
            --host "${PARTSMITH_HOST:-0.0.0.0}" \
            --port "${PARTSMITH_PORT:-8123}" \
            --proxy-headers \
            --forwarded-allow-ips "*"
        ;;
    test)
        exec python -m pytest tests/ -v
        ;;
    shell)
        exec /bin/bash
        ;;
    *)
        echo "Usage: $0 {serve|test|shell}" >&2
        exit 1
        ;;
esac

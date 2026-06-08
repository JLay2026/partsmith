#!/bin/bash
# SPDX-FileCopyrightText: 2026 JLay2026
# SPDX-License-Identifier: MIT
set -e

case "$1" in
    serve)
        exec python -m uvicorn src.server:app \
            --host "${PARTSMITH_HOST:-0.0.0.0}" \
            --port "${PARTSMITH_PORT:-8123}"
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

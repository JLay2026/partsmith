# SPDX-FileCopyrightText: 2026 JLay2026
# SPDX-License-Identifier: MIT
"""Shared fixtures for partsmith integration tests.

These tests require a running partsmith server. In CI the
``.github/workflows/integration.yml`` workflow builds a container,
starts it on ``127.0.0.1:8123``, and sets ``PARTSMITH_URL``.

Locally, run something like::

    docker run -d --rm -p 127.0.0.1:8123:8123 \\
      --name partsmith-test ghcr.io/jlay2026/partsmith:latest
    PARTSMITH_URL=http://127.0.0.1:8123 pytest tests/integration/ -v
    docker stop partsmith-test
"""

import os

import pytest


@pytest.fixture
def partsmith_url() -> str:
    """Base URL of a running partsmith server.

    Skips the test if PARTSMITH_URL isn't set, so the suite is a no-op
    in environments without a container (e.g. the lightweight pytest CI
    job that runs the same test discovery on every PR).
    """
    url = os.environ.get("PARTSMITH_URL")
    if not url:
        pytest.skip(
            "PARTSMITH_URL not set; integration tests require a running "
            "partsmith. See .github/workflows/integration.yml or "
            "tests/integration/conftest.py for setup."
        )
    return url.rstrip("/")

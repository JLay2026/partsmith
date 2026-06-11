# SPDX-FileCopyrightText: 2026 JLay2026
# SPDX-License-Identifier: MIT
"""Integration: REST /health endpoint.

The smallest possible round-trip test. If this fails, partsmith isn't
running or its FastAPI app boot failed (lifespan crash, port-bind
problem, etc.). Catches the v0.1.2-class deploy regressions.
"""

import requests


def test_health_returns_200_with_version(partsmith_url):
    """GET /health -> 200 + {"status": "ok", "version": "X.Y.Z"}."""
    r = requests.get(f"{partsmith_url}/health", timeout=10)
    assert r.status_code == 200, (
        f"GET {partsmith_url}/health returned {r.status_code}: {r.text[:200]}"
    )
    data = r.json()
    assert data.get("status") == "ok", f"Unexpected status: {data!r}"
    version = data.get("version")
    assert isinstance(version, str), f"version must be str, got {version!r}"
    # Loose semver check: X.Y.Z with numeric parts
    parts = version.split(".")
    assert len(parts) == 3, f"version {version!r} should have 3 dot-parts"
    assert all(p.isdigit() for p in parts), (
        f"version {version!r} parts should be numeric"
    )

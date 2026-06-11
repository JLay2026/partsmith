# SPDX-FileCopyrightText: 2026 JLay2026
# SPDX-License-Identifier: MIT
"""Integration: reverse-proxy header compatibility.

Catches the v0.2.1 scheme-downgrade regression. The container's
entrypoint runs uvicorn with ``--proxy-headers --forwarded-allow-ips
"*"`` so that X-Forwarded-Proto / X-Forwarded-For from a fronting
reverse proxy (Caddy) are honored. Without those flags, uvicorn uses
the raw socket scheme (http) and redirect Location headers come back
http:// even when the client arrived over https -- breaking clients
that don't follow scheme-downgrade redirects.

In CI there is no real proxy; we inject the forwarded headers directly.
uvicorn with --forwarded-allow-ips "*" trusts them from any source
(including 127.0.0.1), so the behavior is reproducible.
"""

import pytest
import requests

_FWD_HEADERS = {
    "X-Forwarded-Proto": "https",
    "X-Forwarded-For": "203.0.113.7",  # TEST-NET-3, obviously-external
    "X-Forwarded-Host": "cad.example.test",
}


def test_forwarded_headers_accepted(partsmith_url):
    """Server processes a request carrying X-Forwarded-* without error.

    Proves --forwarded-allow-ips is parsing (not rejecting) the headers.
    A regression that removed --proxy-headers would still pass THIS (it
    just ignores the headers), so the scheme assertion below is the real
    guard; this is the can't-hurt baseline.
    """
    r = requests.get(
        f"{partsmith_url}/health",
        headers=_FWD_HEADERS,
        timeout=10,
    )
    assert r.status_code == 200, (
        f"/health with forwarded headers returned {r.status_code}: "
        f"{r.text[:200]}"
    )
    assert r.json().get("status") == "ok"


def test_redirect_preserves_https_scheme(partsmith_url):
    """A slash-redirect under X-Forwarded-Proto: https must redirect to https.

    GET /mcp (no trailing slash) is expected to 307/308 redirect to
    /mcp/. With proxy-header handling active, the Location must carry
    the forwarded scheme (https), not the raw socket scheme (http).
    This is the direct guard for the v0.2.1 scheme-downgrade bug.

    If the deploy doesn't redirect that path, or emits a relative
    Location (no scheme to downgrade), the test skips rather than
    false-failing -- the regression only manifests as an absolute
    http:// Location.
    """
    r = requests.get(
        f"{partsmith_url}/mcp",
        headers=_FWD_HEADERS,
        allow_redirects=False,
        timeout=10,
    )
    if r.status_code not in (301, 302, 307, 308):
        pytest.skip(
            f"GET /mcp did not redirect (status {r.status_code}); "
            f"no Location scheme to verify on this build."
        )
    location = r.headers.get("Location", "")
    if not location.startswith(("http://", "https://")):
        pytest.skip(
            f"Redirect Location is relative ({location!r}); no scheme "
            f"to verify."
        )
    assert location.startswith("https://"), (
        f"Redirect under X-Forwarded-Proto: https produced a non-https "
        f"Location: {location!r}. This is the v0.2.1 scheme-downgrade "
        f"regression -- check uvicorn --proxy-headers "
        f"--forwarded-allow-ips in entrypoint.sh."
    )

# SPDX-FileCopyrightText: 2026 JLay2026
# SPDX-License-Identifier: MIT
"""Integration: every render path returns a verifiable PNG.

render_section and render_drawing are covered in test_mcp_tools.py; this
file exercises render_3d, render_2d and render_multiview, so the whole
matplotlib/Agg -> Pillow encode path runs against the image's locked
Pillow (0.4.3: Pillow 13). Each PNG must decode, carry the v0.3.5
integrity metadata, and have a plausible size for the view requested.
"""

import base64
import hashlib
import struct

import pytest

from .test_mcp_tools import _call, _create, _initialize

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _png_size(png: bytes) -> tuple[int, int]:
    assert png[:8] == _PNG_MAGIC, "not a PNG"
    assert png[12:16] == b"IHDR", "first chunk is not IHDR"
    w, h = struct.unpack(">II", png[16:24])
    return w, h


def _render(partsmith_url, tool, args, req_id) -> bytes:
    r = _call(partsmith_url, tool, args, req_id)
    assert "error" not in r, r
    assert r.get("inline") is True and r.get("content_type") == "image/png", r
    assert "url_path" not in r, "render PNGs travel inline only"
    png = base64.b64decode(r["data_b64"])
    assert len(png) == r["size_bytes"]
    assert hashlib.sha256(png).hexdigest() == r["sha256"]
    return png


@pytest.fixture(scope="module")
def part(partsmith_url):
    assert _initialize(partsmith_url).status_code == 200
    name = "ci-render-bracket"
    code = (
        "from build123d import *\n"
        "result = Box(60, 30, 20) - Pos(0, 0, 5) * Box(40, 18, 12)\n"
    )
    _create(partsmith_url, code, name, req_id=2)
    return name


@pytest.mark.parametrize("view", ["iso", "front", "top", "iso_back"])
def test_render_3d(partsmith_url, part, view):
    png = _render(partsmith_url, "partsmith_render_3d", {"name": part, "view": view}, 3)
    w, h = _png_size(png)
    # 800x600 at 100 dpi, less bbox_inches="tight" trimming.
    assert 500 <= w <= 800 and 350 <= h <= 600, (w, h)


@pytest.mark.parametrize("view", ["front", "right", "top", "bottom"])
def test_render_2d(partsmith_url, part, view):
    png = _render(
        partsmith_url,
        "partsmith_render_2d",
        {"name": part, "view": view, "with_dimensions": True},
        4,
    )
    w, h = _png_size(png)
    assert 500 <= w <= 800 and 350 <= h <= 600, (w, h)


def test_render_2d_without_dimensions_differs(partsmith_url, part):
    a = _render(partsmith_url, "partsmith_render_2d", {"name": part, "view": "front"}, 5)
    b = _render(
        partsmith_url,
        "partsmith_render_2d",
        {"name": part, "view": "front", "with_dimensions": False},
        6,
    )
    assert a != b, "with_dimensions had no effect on the render"


def test_render_multiview(partsmith_url, part):
    png = _render(partsmith_url, "partsmith_render_multiview", {"name": part}, 7)
    w, h = _png_size(png)
    # 1200x900 composite, tight-trimmed.
    assert 900 <= w <= 1200 and 600 <= h <= 900, (w, h)


def test_render_unknown_model_is_an_error(partsmith_url):
    assert _initialize(partsmith_url).status_code == 200
    r = _call(partsmith_url, "partsmith_render_3d", {"name": "ci-no-such-model"}, 8)
    assert "error" in r, r

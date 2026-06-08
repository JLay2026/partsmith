# SPDX-FileCopyrightText: 2026 JLay2026
# SPDX-License-Identifier: MIT
"""Smoke test — exercises create -> render -> export -> printability."""

from pathlib import Path

import pytest


def test_cube_full_pipeline(tmp_path: Path):
    """Create a 30mm cube, render 3D, export STL, validate printability."""
    from src.cad_engine import CADEngine
    from src.printability import analyze
    from src.renderer import render_3d

    engine = CADEngine(workspace=tmp_path)
    result = engine.execute_code(
        "from build123d import *\nresult = Box(30, 30, 30)",
        name="smoke-cube",
    )
    assert result["success"], result.get("error")
    assert result["geometry"] is not None

    state = engine.get("smoke-cube")
    assert state is not None and state.shape is not None

    # Render 3D
    png = render_3d(state.shape, view="iso")
    assert png[:8] == b"\x89PNG\r\n\x1a\n", "render_3d should return a PNG"
    assert len(png) > 1000, "render PNG is suspiciously small"

    # Export STL
    stl_path = engine.export("smoke-cube", "stl")
    assert stl_path.exists()
    assert stl_path.stat().st_size > 0

    # Printability
    report = analyze(state.shape)
    assert report["is_watertight"], report["issues"]
    assert report["is_volume"]
    assert report["printable"]
    assert report["volume_mm3"] == pytest.approx(27000.0, rel=0.01)


def test_invalid_code_returns_error(tmp_path: Path):
    """Syntax errors should be captured cleanly, not crash the engine."""
    from src.cad_engine import CADEngine

    engine = CADEngine(workspace=tmp_path)
    result = engine.execute_code("this is not valid python", name="bad")
    assert not result["success"]
    assert result["error"] is not None
    assert "SyntaxError" in result["error"]


def test_no_shape_warning(tmp_path: Path):
    """Code that doesn't produce a Shape should succeed but warn."""
    from src.cad_engine import CADEngine

    engine = CADEngine(workspace=tmp_path)
    result = engine.execute_code("x = 42", name="noshape")
    assert result["success"]
    assert result["geometry"] is None
    stdout_lower = result["stdout"].lower()
    assert "no shape found" in stdout_lower or "warning" in stdout_lower

# SPDX-FileCopyrightText: 2026 JLay2026
# SPDX-License-Identifier: MIT
"""Smoke tests for partsmith_helpers.

These tests verify the helper-injection wiring + helper signatures
without exercising build123d geometry deeply (the imports themselves
do load build123d). For geometric correctness, see issue #5
(integration suite, v0.3.1) which runs end-to-end against a real
container.
"""

import inspect

import pytest


def test_helpers_module_has_expected_surface():
    """partsmith_helpers exports the documented helper set + HELPERS dict."""
    from src.partsmith_helpers import HELPERS, __all__

    expected_helpers = {
        "through_hole",
        "screw_hole",
        "hex_hole",
        "slot",
        "chamfer_edges",
        "fillet_top_edges",
        "screw_pattern",
    }
    assert set(HELPERS.keys()) == expected_helpers
    assert all(callable(fn) for fn in HELPERS.values())
    assert "HELPERS" in __all__
    for name in expected_helpers:
        assert name in __all__


def test_helpers_signatures():
    """Helper signatures match the issue #1 contract."""
    from src.partsmith_helpers import (
        chamfer_edges,
        fillet_top_edges,
        hex_hole,
        screw_hole,
        screw_pattern,
        slot,
        through_hole,
    )

    # through_hole(diameter, depth)
    sig = inspect.signature(through_hole)
    assert list(sig.parameters) == ["diameter", "depth"]

    # screw_hole(diameter, depth, countersink=True, head_diameter=None, ...)
    sig = inspect.signature(screw_hole)
    params = list(sig.parameters)
    assert params[:2] == ["diameter", "depth"]
    assert "countersink" in params
    assert "head_diameter" in params

    # hex_hole(across_flats, depth)
    sig = inspect.signature(hex_hole)
    assert list(sig.parameters) == ["across_flats", "depth"]

    # slot(length, width, depth)
    sig = inspect.signature(slot)
    assert list(sig.parameters) == ["length", "width", "depth"]

    # chamfer_edges(part, radius, edges="all")
    sig = inspect.signature(chamfer_edges)
    assert list(sig.parameters) == ["part", "radius", "edges"]
    assert sig.parameters["edges"].default == "all"

    # fillet_top_edges(part, radius)
    sig = inspect.signature(fillet_top_edges)
    assert list(sig.parameters) == ["part", "radius"]

    # screw_pattern(positions, hole_func)
    sig = inspect.signature(screw_pattern)
    assert list(sig.parameters) == ["positions", "hole_func"]


def test_helpers_have_docstrings():
    """Every helper documents its convention so AI agents can use them well."""
    from src.partsmith_helpers import HELPERS

    for name, fn in HELPERS.items():
        assert fn.__doc__ is not None, f"{name} missing docstring"
        # Sanity: docstring should mention units (mm) for geometric helpers
        if name != "screw_pattern":
            assert "mm" in fn.__doc__, f"{name} docstring should reference mm"


def test_screw_pattern_rejects_empty_positions():
    """screw_pattern raises a clear error on empty input."""
    from src.partsmith_helpers import screw_pattern

    with pytest.raises(ValueError, match="empty"):
        screw_pattern([], lambda: None)


def test_slot_rejects_degenerate_geometry():
    """slot raises a clear error when length <= width."""
    from src.partsmith_helpers import slot

    with pytest.raises(ValueError, match="greater than width"):
        slot(length=5, width=10, depth=2)


def test_cad_engine_injects_helpers_into_namespace():
    """CADEngine.execute_code exposes helpers in the build123d namespace."""
    from pathlib import Path

    from src.cad_engine import CADEngine

    engine = CADEngine(workspace=Path("/tmp"))
    # Just check that a code block referencing a helper doesn't NameError.
    # The actual geometry uses through_hole + Box; if build123d is
    # broken, that's a separate (existing) issue.
    code = (
        "from build123d import Box, Location\n"
        "body = Box(10, 10, 5)\n"
        "hole = through_hole(3, 5).moved(Location((0, 0, 2.5)))\n"
        "result = body - hole\n"
    )
    result = engine.execute_code(code, name="helpers-namespace-check")
    assert result["success"], (
        f"execute_code failed: {result.get('error')}. If error is NameError "
        f"on 'through_hole', helpers aren't being injected."
    )

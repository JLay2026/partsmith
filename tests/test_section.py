# SPDX-FileCopyrightText: 2026 JLay2026
# SPDX-License-Identifier: MIT
"""Smoke tests for the cross-section renderer (issue #8).

These tests verify the render_section() contract (signature, plane
validation, request schema wiring) without exercising trimesh
mesh-plane intersection geometry. End-to-end geometric correctness is
deferred to issue #5 (integration suite, v0.3.1) which runs against
a real container.
"""

import inspect

import pytest


def test_render_section_signature():
    """render_section signature matches the issue #8 contract."""
    from src.renderer import render_section

    sig = inspect.signature(render_section)
    params = list(sig.parameters)
    assert params == ["shape", "plane", "at", "size", "with_dimensions"]
    assert sig.parameters["plane"].default == "YZ"
    assert sig.parameters["at"].default == 0.0
    assert sig.parameters["with_dimensions"].default is True


def test_render_section_rejects_invalid_plane():
    """render_section raises a clear ValueError on bad plane."""
    from src.renderer import render_section

    # Use a sentinel that won't reach the trimesh path (validation
    # happens first). Plane check is the first line of the function.
    class _Dummy:
        pass

    with pytest.raises(ValueError, match="plane must be"):
        render_section(_Dummy(), plane="XX")
    with pytest.raises(ValueError, match="plane must be"):
        render_section(_Dummy(), plane="xy")  # case-sensitive


def test_section_planes_constant_complete():
    """SECTION_PLANES has entries for all 3 valid planes."""
    from src.renderer import SECTION_PLANES

    assert set(SECTION_PLANES.keys()) == {"XY", "XZ", "YZ"}
    for plane, defn in SECTION_PLANES.items():
        normal, axis_idx, plot_axes, xlabel, ylabel, normal_name = defn
        assert len(normal) == 3, f"{plane}: normal must be 3D vector"
        assert axis_idx in (0, 1, 2), f"{plane}: axis_idx out of range"
        assert plot_axes[0] != plot_axes[1], f"{plane}: plot axes must differ"
        assert plot_axes[0] != axis_idx and plot_axes[1] != axis_idx, (
            f"{plane}: plot axes can't include the normal axis"
        )
        assert "mm" in xlabel and "mm" in ylabel
        assert normal_name in ("X", "Y", "Z")


def test_section_request_schema_validates_plane():
    """SectionRequest pydantic schema rejects invalid plane strings."""
    # Import SectionRequest from server.py module; this imports the
    # whole server side effects but is the cleanest way to verify the
    # request schema.
    pytest.importorskip("fastapi")
    pytest.importorskip("pydantic")

    from pydantic import ValidationError

    from src.server import SectionRequest

    # Valid
    req = SectionRequest(name="test", plane="YZ", at=0.0)
    assert req.plane == "YZ"
    assert req.at == 0.0
    assert req.with_dimensions is True

    # Invalid plane
    with pytest.raises(ValidationError):
        SectionRequest(name="test", plane="invalid")

    # Out-of-range `at`
    with pytest.raises(ValidationError):
        SectionRequest(name="test", plane="YZ", at=99999.0)

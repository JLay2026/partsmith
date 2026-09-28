# SPDX-FileCopyrightText: 2026 JLay2026
# SPDX-License-Identifier: MIT
"""Geometry tests for the v0.4.0 assembly fit check (issue #25).

Needs build123d, so it runs where the CAD stack is installed (local
dev, the container) rather than in the lightweight CI job.
"""

import pytest

pytest.importorskip("build123d")


def _box(x=10, y=10, z=10, at=(0, 0, 0)):
    from build123d import Box, Location

    return Box(x, y, z).moved(Location(at))


def test_overlap_reports_volume_and_region():
    from src.fit_check import check_fit

    r = check_fit(_box(), _box(at=(8, 0, 0)))
    assert r["interferes"] is True
    assert r["interference_volume_mm3"] == pytest.approx(200.0, abs=0.01)  # 2 x 10 x 10
    assert r["interference_bbox"]["size"] == pytest.approx([2.0, 10.0, 10.0], abs=1e-3)
    assert r["min_distance_mm"] == 0.0
    assert r["ok"] is False
    assert "overlap" in r["issues"][0]


def test_part_fully_inside_another_interferes():
    """Containment: the distance solver reports boundary-to-boundary
    distance (> 0) here, so the boolean must still run."""
    from src.fit_check import check_fit

    for a, b in ((_box(40, 40, 40), _box(10, 10, 10)), (_box(10, 10, 10), _box(40, 40, 40))):
        r = check_fit(a, b)
        assert r["interferes"] is True
        assert r["interference_volume_mm3"] == pytest.approx(1000.0, abs=0.01)
        assert r["min_distance_mm"] == 0.0
        assert r["ok"] is False


def test_touching_is_contact_not_interference():
    from src.fit_check import check_fit

    r = check_fit(_box(), _box(at=(10, 0, 0)), min_clearance_mm=0.0)
    assert r["interferes"] is False
    assert r["contact"] is True
    assert r["ok"] is True  # zero clearance required

    r = check_fit(_box(), _box(at=(10, 0, 0)), min_clearance_mm=0.2)
    assert r["ok"] is False
    assert "touch" in r["issues"][0]


def test_gap_measured_with_closest_points():
    from src.fit_check import check_fit

    r = check_fit(_box(), _box(at=(10.5, 0, 0)), min_clearance_mm=0.2)
    assert r["min_distance_mm"] == pytest.approx(0.5, abs=1e-4)
    assert r["closest_points"]["b"][0] - r["closest_points"]["a"][0] == pytest.approx(0.5)
    assert r["ok"] is True and r["issues"] == []

    tight = check_fit(_box(), _box(at=(10.5, 0, 0)), min_clearance_mm=1.0)
    assert tight["ok"] is False and "0.500 mm apart" in tight["issues"][0]


def test_peg_in_socket_radial_clearance():
    """rug_hanger keying: Ø4.8 peg in a Ø5.2 socket -> 0.2 mm radial."""
    from build123d import Box, Cylinder, Location

    from src.fit_check import check_fit

    block = Box(20, 20, 10) - Cylinder(2.6, 10)
    peg = Cylinder(2.4, 6)  # centered, shorter than the socket: no floor contact
    r = check_fit(block, peg, min_clearance_mm=0.15)
    assert r["interferes"] is False
    assert r["min_distance_mm"] == pytest.approx(0.2, abs=1e-3)
    assert r["ok"] is True

    # Off-center peg now hits the socket wall.
    shifted = check_fit(block, peg.moved(Location((0.3, 0, 0))))
    assert shifted["interferes"] is True


def test_offset_b_places_origin_modeled_part():
    from src.fit_check import check_fit

    a, b = _box(), _box()
    assert check_fit(a, b)["interferes"] is True  # both at origin
    r = check_fit(a, b, offset_b=[11, 0, 0])
    assert r["interferes"] is False
    assert r["min_distance_mm"] == pytest.approx(1.0, abs=1e-4)
    assert r["offset_b"] == [11.0, 0.0, 0.0]


def test_rejects_bad_inputs():
    from src.fit_check import check_fit

    with pytest.raises(ValueError):
        check_fit(_box(), _box(), min_clearance_mm=-1)
    with pytest.raises(ValueError):
        check_fit(_box(), _box(), offset_b=[1, 2])

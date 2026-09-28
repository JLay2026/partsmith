# SPDX-FileCopyrightText: 2026 JLay2026
# SPDX-License-Identifier: MIT
"""Plate export and 3MF writing (v0.4.0, issue #26).

Needs build123d, so it runs where the CAD stack is installed (local
dev, the container) rather than in the lightweight CI job.
"""

import re
import zipfile

import pytest

pytest.importorskip("build123d")

BED = [256.0, 256.0, 256.0]


def _box(x, y, z, at=(0, 0, 0)):
    from build123d import Box, Location

    return Box(x, y, z).moved(Location(at))


def _within_bed(p):
    return all(0 <= p["bbox_min_mm"][i] and p["bbox_max_mm"][i] <= BED[i] for i in range(3))


def test_arrange_packs_rows_and_centers():
    """sw2-like set: modeled 366 mm wide, arranged into rows on one plate."""
    from src.plate_export import plan_plate

    parts = [
        ("tray", _box(250, 128.5, 88)),
        ("wing", _box(135.8, 16, 88, at=(173.4, 0, 0))),
        ("bar", _box(213.8, 15, 27, at=(0, 70, 30))),
    ]
    info = plan_plate(parts, bed_mm=BED)
    pl = {p["name"]: p for p in info["placements"]}
    assert all(_within_bed(p) for p in pl.values())
    assert all(p["bbox_min_mm"][2] == pytest.approx(0.0) for p in pl.values())  # on the bed
    # three rows (none share a row), 5 mm gaps, in the given order
    assert pl["wing"]["bbox_min_mm"][1] == pytest.approx(pl["tray"]["bbox_max_mm"][1] + 5)
    assert pl["bar"]["bbox_min_mm"][1] == pytest.approx(pl["wing"]["bbox_max_mm"][1] + 5)
    assert info["layout_size_mm"][1] == pytest.approx(128.5 + 5 + 16 + 5 + 15)
    # centered on the bed
    lo = min(p["bbox_min_mm"][1] for p in pl.values())
    hi = max(p["bbox_max_mm"][1] for p in pl.values())
    assert (lo + hi) / 2 == pytest.approx(128.0)


def test_arrange_shares_a_row_when_parts_fit():
    from src.plate_export import plan_plate

    info = plan_plate([("a", _box(100, 20, 10)), ("b", _box(100, 30, 10))], bed_mm=BED)
    a, b = info["placements"]
    assert b["bbox_min_mm"][0] == pytest.approx(a["bbox_max_mm"][0] + 5)
    assert b["bbox_min_mm"][1] == pytest.approx(a["bbox_min_mm"][1])
    assert info["layout_size_mm"][:2] == pytest.approx([205, 30])


def test_arrange_rejects_layout_too_deep():
    from src.plate_export import plan_plate

    parts = [(f"p{i}", _box(200, 100, 10)) for i in range(3)]  # 3 rows x 100 > 256
    with pytest.raises(ValueError, match="Split the parts"):
        plan_plate(parts, bed_mm=BED)


def test_single_part_too_big_with_rotation_hint():
    from src.plate_export import plan_plate

    with pytest.raises(ValueError, match="fit rotated"):
        plan_plate([("long", _box(300, 20, 20))], bed_mm=[256, 256, 320])  # hint path
    with pytest.raises(ValueError, match="does not fit"):
        plan_plate([("huge", _box(300, 300, 10))], bed_mm=BED)


def test_as_modeled_keeps_relative_positions():
    from src.plate_export import plan_plate

    parts = [("l", _box(40, 20, 10)), ("r", _box(40, 20, 10, at=(60, 0, 0)))]
    info = plan_plate(parts, bed_mm=BED, layout="as_modeled")
    left, right = info["placements"]
    assert left["offset_mm"] == right["offset_mm"]  # rigid group
    assert right["bbox_min_mm"][0] - left["bbox_max_mm"][0] == pytest.approx(20.0)
    assert all(_within_bed(p) for p in info["placements"])


def test_as_modeled_rejects_assembly_overlap():
    """A retainer modeled on its peg would print fused to the mount."""
    from build123d import Cylinder, Location

    from src.plate_export import plan_plate

    mount = _box(80, 45, 120)
    retainer = Cylinder(15, 4).moved(Location((0, 10, 0)))
    with pytest.raises(ValueError, match="overlap as modeled"):
        plan_plate([("mount", mount), ("retainer", retainer)], bed_mm=BED, layout="as_modeled")
    # the default arranges them apart
    info = plan_plate([("mount", mount), ("retainer", retainer)], bed_mm=BED)
    m, r = info["placements"]
    assert r["bbox_min_mm"][0] >= m["bbox_max_mm"][0]


def test_rejects_bad_layout_and_gap():
    from src.plate_export import plan_plate

    with pytest.raises(ValueError, match="layout"):
        plan_plate([("a", _box(1, 1, 1))], layout="grid")
    with pytest.raises(ValueError, match="gap_mm"):
        plan_plate([("a", _box(1, 1, 1))], gap_mm=-1)


def test_write_3mf_named_objects_roundtrip(tmp_path):
    from build123d import Mesher

    from src.plate_export import write_3mf

    path = tmp_path / "p.3mf"
    write_3mf([("tray", _box(10, 10, 10), (5, 5, 5)), ("wing", _box(4, 4, 4), (30, 5, 2))], path)
    assert zipfile.is_zipfile(path)
    xml = zipfile.ZipFile(path).read("3D/3dmodel.model")
    assert re.findall(rb'<object [^>]*name="([^"]+)"', xml) == [b"tray", b"wing"]
    back = Mesher().read(str(path))
    assert sorted(round(s.volume, 1) for s in back) == [64.0, 1000.0]


def test_engine_3mf_export_is_real_3mf(tmp_path):
    """Regression: before v0.4.0, format='3mf' silently wrote an STL."""
    from src.cad_engine import CADEngine

    e = CADEngine(workspace=tmp_path)
    e.execute_code("result = Box(10, 10, 10)", "cube")
    path = e.export("cube", "3mf")
    assert path.suffix == ".3mf"
    assert zipfile.is_zipfile(path)
    assert b"<model" in zipfile.ZipFile(path).read("3D/3dmodel.model")

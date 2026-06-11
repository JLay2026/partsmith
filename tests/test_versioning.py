# SPDX-FileCopyrightText: 2026 JLay2026
# SPDX-License-Identifier: MIT
"""End-to-end tests for the versioned design store (issue #3, v0.2.7).

Unlike test_helpers / test_section which avoid build123d to keep CI
fast, design_store is pure stdlib + filesystem, so these tests run the
real save/load/diff flow against a tmp_path workspace.
"""

import json
from pathlib import Path

import pytest


def test_save_auto_appends_versions(tmp_path: Path):
    """save(version='auto') appends v1, v2, v3..."""
    from src.design_store import DesignStore

    s = DesignStore(workspace=tmp_path)
    m1 = s.save("bracket", "code v1", description="first")
    m2 = s.save("bracket", "code v2", description="second")
    m3 = s.save("bracket", "code v3")

    assert m1.version == 1
    assert m2.version == 2
    assert m3.version == 3
    assert s.list_versions("bracket") == [1, 2, 3]

    # Files on disk
    assert (tmp_path / "designs" / "bracket" / "v1.py").read_text() == "code v1"
    assert (tmp_path / "designs" / "bracket" / "v2.py").read_text() == "code v2"
    assert (tmp_path / "designs" / "bracket" / "v3.py").read_text() == "code v3"


def test_save_explicit_version_overwrites(tmp_path: Path):
    """save(version=N) targets that slot, overwriting any existing content."""
    from src.design_store import DesignStore

    s = DesignStore(workspace=tmp_path)
    s.save("part", "v1 original")
    s.save("part", "v2 original")
    # Overwrite v1 in place
    m = s.save("part", "v1 fixed", version=1)
    assert m.version == 1

    code, meta = s.load("part", version=1)
    assert code == "v1 fixed"
    assert meta.version == 1
    # v2 untouched
    code2, _ = s.load("part", version=2)
    assert code2 == "v2 original"


def test_load_default_is_latest(tmp_path: Path):
    """load(version=None) returns the latest version."""
    from src.design_store import DesignStore

    s = DesignStore(workspace=tmp_path)
    s.save("widget", "v1")
    s.save("widget", "v2")
    s.save("widget", "v3")

    code, meta = s.load("widget")
    assert code == "v3"
    assert meta.version == 3


def test_load_specific_version(tmp_path: Path):
    """load(version=int) returns that exact version."""
    from src.design_store import DesignStore

    s = DesignStore(workspace=tmp_path)
    s.save("part", "first")
    s.save("part", "second")

    code, meta = s.load("part", version=1)
    assert code == "first"
    assert meta.version == 1


def test_load_nonexistent_raises(tmp_path: Path):
    """load on missing design or version raises FileNotFoundError."""
    from src.design_store import DesignStore

    s = DesignStore(workspace=tmp_path)
    with pytest.raises(FileNotFoundError):
        s.load("nope")

    s.save("only_v1", "x")
    with pytest.raises(FileNotFoundError):
        s.load("only_v1", version=5)


def test_delete_specific_version(tmp_path: Path):
    """delete(version=N) removes just that version."""
    from src.design_store import DesignStore

    s = DesignStore(workspace=tmp_path)
    s.save("part", "v1")
    s.save("part", "v2")
    s.save("part", "v3")

    assert s.delete("part", version=2) is True
    assert s.list_versions("part") == [1, 3]
    # v1 and v3 still loadable
    assert s.load("part", version=1)[0] == "v1"
    assert s.load("part", version=3)[0] == "v3"


def test_delete_all_versions(tmp_path: Path):
    """delete(version=None) nukes all versions and the dir."""
    from src.design_store import DesignStore

    s = DesignStore(workspace=tmp_path)
    s.save("part", "v1")
    s.save("part", "v2")

    assert s.delete("part") is True
    assert s.list_versions("part") == []
    # Directory gone
    assert not (tmp_path / "designs" / "part").exists()


def test_legacy_layout_read_compat(tmp_path: Path):
    """Pre-v0.2.7 flat {name}.py + {name}.json reads as version 1."""
    from src.design_store import DesignStore

    s = DesignStore(workspace=tmp_path)
    # Simulate a pre-v0.2.7 flat-layout design
    (s.designs_dir / "legacy.py").write_text("legacy code")
    (s.designs_dir / "legacy.json").write_text(
        json.dumps({"name": "legacy", "description": "old"})
    )

    assert s.list_versions("legacy") == [1]
    code, meta = s.load("legacy")
    assert code == "legacy code"
    assert meta.version == 1
    assert meta.description == "old"


def test_legacy_auto_migrates_on_save(tmp_path: Path):
    """Saving to a legacy design auto-migrates it to versioned layout."""
    from src.design_store import DesignStore

    s = DesignStore(workspace=tmp_path)
    # Simulate legacy
    (s.designs_dir / "legacy.py").write_text("legacy v1")
    (s.designs_dir / "legacy.json").write_text(
        json.dumps({"name": "legacy"})
    )

    # Save a new version
    m = s.save("legacy", "new v2")
    assert m.version == 2

    # Legacy files gone; versioned layout in place
    assert not (s.designs_dir / "legacy.py").exists()
    assert (s.designs_dir / "legacy" / "v1.py").read_text() == "legacy v1"
    assert (s.designs_dir / "legacy" / "v2.py").read_text() == "new v2"
    assert s.list_versions("legacy") == [1, 2]


def test_diff_source_changes(tmp_path: Path):
    """diff returns a unified source diff between two versions."""
    from src.design_store import DesignStore

    s = DesignStore(workspace=tmp_path)
    s.save("p", "from build123d import *\nresult = Box(10, 10, 10)\n")
    s.save("p", "from build123d import *\nresult = Box(20, 20, 20)\n")

    d = s.diff("p", v1=1, v2=2)
    assert d["name"] == "p"
    assert d["v1"] == 1
    assert d["v2"] == 2
    assert "-result = Box(10, 10, 10)" in d["source_diff"]
    assert "+result = Box(20, 20, 20)" in d["source_diff"]


def test_diff_geometry_deltas(tmp_path: Path):
    """diff computes volume / surface_area / bbox deltas when both have geometry."""
    from src.design_store import DesignStore

    s = DesignStore(workspace=tmp_path)
    geo_small = {
        "volume_mm3": 1000.0,
        "surface_area_mm2": 600.0,
        "bounding_box": {"size": [10.0, 10.0, 10.0]},
    }
    geo_big = {
        "volume_mm3": 8000.0,
        "surface_area_mm2": 2400.0,
        "bounding_box": {"size": [20.0, 20.0, 20.0]},
    }
    s.save("cube", "small code", geometry=geo_small)
    s.save("cube", "big code", geometry=geo_big)

    d = s.diff("cube", v1=1, v2=2)
    assert d["volume_delta_mm3"] == 7000.0  # 8000 - 1000
    assert d["surface_area_delta_mm2"] == 1800.0  # 2400 - 600
    assert d["bbox_size_delta_mm"] == [10.0, 10.0, 10.0]


def test_diff_handles_missing_geometry(tmp_path: Path):
    """diff returns None for deltas when either side lacks geometry."""
    from src.design_store import DesignStore

    s = DesignStore(workspace=tmp_path)
    s.save("p", "v1", geometry=None)
    s.save("p", "v2", geometry={"volume_mm3": 100.0})

    d = s.diff("p", v1=1, v2=2)
    assert d["volume_delta_mm3"] is None
    assert d["surface_area_delta_mm2"] is None
    assert d["bbox_size_delta_mm"] is None


def test_list_all_returns_latest_per_design(tmp_path: Path):
    """list_all returns one entry per design (latest version)."""
    from src.design_store import DesignStore

    s = DesignStore(workspace=tmp_path)
    s.save("a", "a1")
    s.save("a", "a2")
    s.save("b", "b1")

    entries = s.list_all()
    by_name = {m.name: m for m in entries}
    assert set(by_name.keys()) == {"a", "b"}
    assert by_name["a"].version == 2
    assert by_name["b"].version == 1


def test_invalid_name_raises(tmp_path: Path):
    """Bad design names raise ValueError consistently across methods."""
    from src.design_store import DesignStore

    s = DesignStore(workspace=tmp_path)
    for bad in ("../escape", "with space", "x" * 100, ""):
        with pytest.raises(ValueError, match="Invalid design name"):
            s.save(bad, "x")


def test_diff_rejects_bad_versions(tmp_path: Path):
    """diff(v1, v2) requires positive ints."""
    from src.design_store import DesignStore

    s = DesignStore(workspace=tmp_path)
    s.save("p", "x")
    with pytest.raises(ValueError, match="v1 must be"):
        s.diff("p", v1=0, v2=1)
    with pytest.raises(ValueError, match="v2 must be"):
        s.diff("p", v1=1, v2=-1)


def test_save_request_schema_accepts_version(tmp_path: Path):
    """SaveDesignRequest pydantic schema accepts version field (REST surface)."""
    # server.py imports the full dep chain (mcp -> printability -> trimesh
    # -> renderer -> matplotlib + numpy + build123d). All of these need to
    # be present for the SaveDesignRequest schema check to even reach the
    # pydantic call. Skip cleanly in the lightweight CI which deliberately
    # doesn't install the heavy deps; the integration suite covers this
    # path against the real container.
    pytest.importorskip("fastapi")
    pytest.importorskip("pydantic")
    pytest.importorskip("trimesh")
    pytest.importorskip("matplotlib")
    pytest.importorskip("build123d")
    pytest.importorskip("mcp")

    from src.server import SaveDesignRequest

    req = SaveDesignRequest(code="x", name="ok", version="auto")
    assert req.version == "auto"
    req2 = SaveDesignRequest(code="x", name="ok", version=3)
    assert req2.version == 3

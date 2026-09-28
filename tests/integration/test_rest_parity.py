# SPDX-FileCopyrightText: 2026 JLay2026
# SPDX-License-Identifier: MIT
"""Integration: REST surface matches MCP behavior for v0.4.0 additions.

REST + MCP parity is a stated design principle (ROADMAP). These guard
the two v0.4.0 features on the REST side: the versioned-name warning on
/design/save and bed_mm validation on /analyze/printability.
"""

import requests


def _post(url, path, body):
    return requests.post(f"{url}{path}", json=body, timeout=30)


def test_rest_save_design_versioned_name_warning(partsmith_url):
    code = "from build123d import *\nresult = Box(10, 10, 10)"

    plain = _post(partsmith_url, "/design/save", {"name": "ci-rest-warn", "code": code})
    assert plain.status_code == 200, plain.text[:300]
    assert "warning" not in plain.json()

    suffixed = _post(
        partsmith_url, "/design/save", {"name": "ci-rest-warn_v2", "code": code}
    )
    assert suffixed.status_code == 200, suffixed.text[:300]
    assert "ci-rest-warn" in suffixed.json().get("warning", ""), suffixed.json()

    for n in ("ci-rest-warn", "ci-rest-warn_v2"):
        requests.delete(f"{partsmith_url}/design/{n}", timeout=30)


def test_rest_printability_bed_fit_and_validation(partsmith_url):
    r = _post(
        partsmith_url,
        "/model/create",
        {"name": "ci-rest-bed", "code": "from build123d import *\nresult = Box(260, 94, 168)"},
    )
    assert r.status_code == 200 and r.json().get("success") is True, r.text[:300]

    ok = _post(partsmith_url, "/analyze/printability", {"name": "ci-rest-bed"})
    assert ok.status_code == 200, ok.text[:300]
    assert ok.json()["bed_fit"]["fits_any_orientation"] is False

    override = _post(
        partsmith_url,
        "/analyze/printability",
        {"name": "ci-rest-bed", "bed_mm": [300, 300, 300]},
    )
    assert override.status_code == 200
    assert override.json()["bed_fit"]["fits_as_oriented"] is True

    for bad in ([0, 256, 256], [256, -5, 256], [256, 256]):
        resp = _post(
            partsmith_url, "/analyze/printability", {"name": "ci-rest-bed", "bed_mm": bad}
        )
        assert resp.status_code == 422, (bad, resp.status_code, resp.text[:200])


def test_rest_analyze_fit_matches_mcp_shape(partsmith_url):
    """v0.4.0 (#25): POST /analyze/fit returns the same payload as the MCP tool."""
    for name, code in (
        ("ci-rest-fit-a", "from build123d import *\nresult = Box(10, 10, 10)"),
        ("ci-rest-fit-b", "from build123d import *\nresult = Box(10, 10, 10)"),
    ):
        r = _post(partsmith_url, "/model/create", {"name": name, "code": code})
        assert r.status_code == 200 and r.json().get("success") is True, r.text[:300]

    body = {"name_a": "ci-rest-fit-a", "name_b": "ci-rest-fit-b", "offset_b": [10.5, 0, 0]}
    r = _post(partsmith_url, "/analyze/fit", body)
    assert r.status_code == 200, r.text[:300]
    out = r.json()
    for key in (
        "interferes", "interference_volume_mm3", "interference_bbox", "min_distance_mm",
        "closest_points", "contact", "min_clearance_mm", "offset_b", "ok", "issues",
    ):
        assert key in out, key
    assert out["ok"] is True and abs(out["min_distance_mm"] - 0.5) < 1e-3

    assert _post(partsmith_url, "/analyze/fit", {**body, "offset_b": [1, 2]}).status_code == 422
    assert _post(partsmith_url, "/analyze/fit", {**body, "min_clearance_mm": -1}).status_code == 422
    missing = _post(partsmith_url, "/analyze/fit", {"name_a": "ci-rest-fit-a", "name_b": "nope"})
    assert missing.status_code == 404


def test_rest_export_plate(partsmith_url):
    """v0.4.0 (#26): POST /export/plate returns a 3MF + placement header."""
    import io
    import json
    import zipfile

    for name, code in (
        ("ci-rest-plate-a", "from build123d import *\nresult = Box(40, 20, 10)"),
        ("ci-rest-plate-b", "from build123d import *\nresult = Box(40, 20, 10)"),
    ):
        r = _post(partsmith_url, "/model/create", {"name": name, "code": code})
        assert r.status_code == 200 and r.json().get("success") is True, r.text[:300]

    names = ["ci-rest-plate-a", "ci-rest-plate-b"]
    r = _post(partsmith_url, "/export/plate", {"names": names})
    assert r.status_code == 200, r.text[:300]
    assert zipfile.is_zipfile(io.BytesIO(r.content))
    info = json.loads(r.headers["X-Partsmith-Plate"])
    assert [p["name"] for p in info["placements"]] == names
    assert info["layout"] == "arrange"

    bad_layout = _post(partsmith_url, "/export/plate", {"names": names, "layout": "grid"})
    assert bad_layout.status_code == 422
    assert _post(partsmith_url, "/export/plate", {"names": []}).status_code == 422
    missing = _post(partsmith_url, "/export/plate", {"names": ["ci-rest-plate-a", "nope"]})
    assert missing.status_code == 400

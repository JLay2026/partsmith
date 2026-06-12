# SPDX-FileCopyrightText: 2026 JLay2026
# SPDX-License-Identifier: MIT
"""Integration: full MCP tool-call round-trip.

Initialize -> partsmith_create_model (cube) -> verify geometry ->
partsmith_export (STL) -> verify decodable STL bytes. Plus preview
opt-in (v0.3.6) and export integrity metadata (v0.3.5).
"""

import base64
import hashlib
import json

import requests

_MCP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


def _rpc(partsmith_url, method, params=None, req_id=1):
    """Send a JSON-RPC request to the MCP endpoint, return the Response."""
    payload = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        payload["params"] = params
    return requests.post(
        f"{partsmith_url}/mcp/",
        headers=_MCP_HEADERS,
        json=payload,
        timeout=30,  # build123d execution can take a few seconds
    )


def _initialize(partsmith_url):
    return _rpc(
        partsmith_url,
        "initialize",
        {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "ci-tools", "version": "0"},
        },
        req_id=1,
    )


def _tool_result_dict(rpc_response_body):
    """Extract the tool's dict result from a tools/call JSON-RPC response.

    FastMCP can surface a tool's dict return as structuredContent and/or
    a JSON string in content[0].text. Parse defensively so the test isn't
    coupled to one wrapping.
    """
    result = rpc_response_body.get("result", {})
    if isinstance(result.get("structuredContent"), dict):
        sc = result["structuredContent"]
        if set(sc.keys()) == {"result"} and isinstance(sc["result"], dict):
            return sc["result"]
        return sc
    content = result.get("content", [])
    if content and isinstance(content, list):
        first = content[0]
        text = first.get("text") if isinstance(first, dict) else None
        if text:
            try:
                return json.loads(text)
            except (json.JSONDecodeError, TypeError):
                pass
    raise AssertionError(
        f"Could not extract tool result dict from response: {rpc_response_body!r}"
    )


def test_create_model_then_export_roundtrip(partsmith_url):
    """create_model(cube) -> geometry; export(stl) -> valid STL bytes.

    As of v0.3.6 create_model does NOT embed a preview by default (see
    test_create_model_preview_optional for the opt-in path).
    """
    init = _initialize(partsmith_url)
    assert init.status_code == 200, f"initialize failed: {init.status_code}"

    create = _rpc(
        partsmith_url,
        "tools/call",
        {
            "name": "partsmith_create_model",
            "arguments": {
                "code": "from build123d import *\nresult = Box(20, 20, 20)",
                "name": "ci-roundtrip-cube",
            },
        },
        req_id=2,
    )
    assert create.status_code == 200, (
        f"create_model call returned {create.status_code}: {create.text[:300]}"
    )
    create_result = _tool_result_dict(create.json())
    assert create_result.get("success") is True, (
        f"create_model did not succeed: {create_result!r}"
    )
    geom = create_result.get("geometry")
    assert geom is not None, "create_model returned no geometry"
    assert abs(geom["volume_mm3"] - 8000.0) < 1.0, (
        f"Expected ~8000 mm^3 for a 20mm cube, got {geom.get('volume_mm3')!r}"
    )
    bbox = geom["bounding_box"]
    assert bbox["size"] == [20.0, 20.0, 20.0], (
        f"Expected 20x20x20 bbox, got {bbox.get('size')!r}"
    )
    assert "preview_data_b64" not in create_result, (
        "default create_model should not embed a preview"
    )

    export = _rpc(
        partsmith_url,
        "tools/call",
        {
            "name": "partsmith_export",
            "arguments": {"name": "ci-roundtrip-cube", "format": "stl"},
        },
        req_id=3,
    )
    assert export.status_code == 200, (
        f"export call returned {export.status_code}: {export.text[:300]}"
    )
    export_result = _tool_result_dict(export.json())
    assert export_result.get("inline") is True, (
        f"Expected inline STL for a tiny cube, got: {export_result!r}"
    )
    stl_bytes = base64.b64decode(export_result["data_b64"])
    assert len(stl_bytes) > 0, "exported STL is empty"
    is_binary_stl = len(stl_bytes) >= 84
    is_ascii_stl = stl_bytes[:5].lower() == b"solid"
    assert is_binary_stl or is_ascii_stl, (
        f"exported bytes don't look like STL (len={len(stl_bytes)}, "
        f"head={stl_bytes[:16]!r})"
    )


def test_create_model_preview_optional(partsmith_url):
    """v0.3.6 (#20): preview is opt-in. Default omits it; include_preview
    yields a capped, verifiable inline PNG.
    """
    init = _initialize(partsmith_url)
    assert init.status_code == 200

    default = _rpc(
        partsmith_url,
        "tools/call",
        {
            "name": "partsmith_create_model",
            "arguments": {
                "code": "from build123d import *\nresult = Box(15, 15, 15)",
                "name": "ci-preview-default",
            },
        },
        req_id=2,
    )
    assert default.status_code == 200
    default_result = _tool_result_dict(default.json())
    assert default_result.get("success") is True
    assert "preview_data_b64" not in default_result, (
        f"default create should carry no preview: keys={list(default_result)}"
    )

    withp = _rpc(
        partsmith_url,
        "tools/call",
        {
            "name": "partsmith_create_model",
            "arguments": {
                "code": "from build123d import *\nresult = Box(15, 15, 15)",
                "name": "ci-preview-on",
                "include_preview": True,
            },
        },
        req_id=3,
    )
    assert withp.status_code == 200, (
        f"create w/ preview returned {withp.status_code}: {withp.text[:300]}"
    )
    r = _tool_result_dict(withp.json())
    assert r.get("success") is True
    if "preview_data_b64" in r:
        png = base64.b64decode(r["preview_data_b64"])
        assert png[:8] == b"\x89PNG\r\n\x1a\n", "preview is not a PNG"
        assert r["preview_size_bytes"] == len(png), (
            "preview_size_bytes mismatch vs decoded preview length"
        )
        assert hashlib.sha256(png).hexdigest() == r["preview_sha256"], (
            "preview_sha256 does not match decoded preview bytes"
        )
    else:
        assert "preview_note" in r, (
            f"preview omitted but no preview_note explaining why: {list(r)}"
        )


def test_export_integrity_metadata(partsmith_url):
    """v0.3.5 (#18): export carries sha256 + size_bytes that match the
    decoded bytes, plus a fetchable url_path for stl/step/3mf.
    """
    init = _initialize(partsmith_url)
    assert init.status_code == 200

    _rpc(
        partsmith_url,
        "tools/call",
        {
            "name": "partsmith_create_model",
            "arguments": {
                "code": "from build123d import *\nresult = Box(12, 8, 5)",
                "name": "ci-integrity-box",
            },
        },
        req_id=2,
    )

    export = _rpc(
        partsmith_url,
        "tools/call",
        {
            "name": "partsmith_export",
            "arguments": {"name": "ci-integrity-box", "format": "stl"},
        },
        req_id=3,
    )
    assert export.status_code == 200, (
        f"export call returned {export.status_code}: {export.text[:300]}"
    )
    r = _tool_result_dict(export.json())

    assert "sha256" in r, f"export missing sha256: {r!r}"
    assert "size_bytes" in r, f"export missing size_bytes: {r!r}"
    assert r.get("inline") is True, f"expected tiny STL inline: {r!r}"

    assert r.get("url_path") == "/workspace/ci-integrity-box.stl", (
        f"expected fetchable url_path for stl, got {r.get('url_path')!r}"
    )

    data = base64.b64decode(r["data_b64"])
    assert len(data) == r["size_bytes"], (
        f"size_bytes {r['size_bytes']} != decoded len {len(data)}"
    )
    assert hashlib.sha256(data).hexdigest() == r["sha256"], (
        "sha256 does not match decoded bytes: integrity contract broken"
    )


def test_render_section_via_mcp(partsmith_url):
    """create_model -> render_section returns an inline PNG (v0.2.6 tool)."""
    init = _initialize(partsmith_url)
    assert init.status_code == 200

    _rpc(
        partsmith_url,
        "tools/call",
        {
            "name": "partsmith_create_model",
            "arguments": {
                "code": "from build123d import *\nresult = Box(30, 30, 30)",
                "name": "ci-section-cube",
            },
        },
        req_id=2,
    )

    section = _rpc(
        partsmith_url,
        "tools/call",
        {
            "name": "partsmith_render_section",
            "arguments": {"name": "ci-section-cube", "plane": "YZ", "at": 0.0},
        },
        req_id=3,
    )
    assert section.status_code == 200, (
        f"render_section call returned {section.status_code}: {section.text[:300]}"
    )
    result = _tool_result_dict(section.json())
    assert result.get("inline") is True, f"Expected inline PNG, got {result!r}"
    png = base64.b64decode(result["data_b64"])
    assert png[:8] == b"\x89PNG\r\n\x1a\n", "section render is not a PNG"
    assert "url_path" not in result, (
        f"render PNG should not advertise url_path: {result!r}"
    )


def test_render_drawing_via_mcp(partsmith_url):
    """create_model -> render_drawing returns an inline PNG (v0.3.4 tool)."""
    init = _initialize(partsmith_url)
    assert init.status_code == 200

    _rpc(
        partsmith_url,
        "tools/call",
        {
            "name": "partsmith_create_model",
            "arguments": {
                "code": "from build123d import *\nresult = Box(50, 20, 30)",
                "name": "ci-drawing-box",
            },
        },
        req_id=2,
    )

    drawing = _rpc(
        partsmith_url,
        "tools/call",
        {
            "name": "partsmith_render_drawing",
            "arguments": {
                "name": "ci-drawing-box",
                "view": "front",
                "part_name": "ci-drawing-box",
            },
        },
        req_id=3,
    )
    assert drawing.status_code == 200, (
        f"render_drawing call returned {drawing.status_code}: {drawing.text[:300]}"
    )
    result = _tool_result_dict(drawing.json())
    assert result.get("inline") is True, f"Expected inline PNG, got {result!r}"
    png = base64.b64decode(result["data_b64"])
    assert png[:8] == b"\x89PNG\r\n\x1a\n", "drawing render is not a PNG"

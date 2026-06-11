# SPDX-FileCopyrightText: 2026 JLay2026
# SPDX-License-Identifier: MIT
"""Integration: full MCP tool-call round-trip.

Initialize -> partsmith_create_model (cube) -> verify geometry +
preview -> partsmith_export (STL) -> verify decodable STL bytes.

This is the v0.3.2 completion of issue #5: where test_mcp_handshake
proves the transport + tool inventory, this proves the tools actually
*execute* end-to-end against a real build123d + trimesh stack inside
the container.
"""

import base64
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

    FastMCP can surface a tool's dict return as ``structuredContent`` and/or
    a JSON string in ``content[0].text``. Parse defensively so the test
    isn't coupled to one wrapping.
    """
    result = rpc_response_body.get("result", {})
    # Preferred: structuredContent (FastMCP puts dict returns here)
    if isinstance(result.get("structuredContent"), dict):
        sc = result["structuredContent"]
        # Some FastMCP versions wrap the dict under a "result" key
        if set(sc.keys()) == {"result"} and isinstance(sc["result"], dict):
            return sc["result"]
        return sc
    # Fallback: content[0].text as JSON
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
    """create_model(cube) -> geometry + preview; export(stl) -> valid STL bytes."""
    init = _initialize(partsmith_url)
    assert init.status_code == 200, f"initialize failed: {init.status_code}"

    # 1. Create a 20mm cube
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
    # 20mm cube => 8000 mm^3
    assert abs(geom["volume_mm3"] - 8000.0) < 1.0, (
        f"Expected ~8000 mm^3 for a 20mm cube, got {geom.get('volume_mm3')!r}"
    )
    bbox = geom["bounding_box"]
    assert bbox["size"] == [20.0, 20.0, 20.0], (
        f"Expected 20x20x20 bbox, got {bbox.get('size')!r}"
    )
    # Preview PNG should be present + look like a PNG
    preview_b64 = create_result.get("preview_data_b64")
    assert preview_b64, "create_model returned no preview_data_b64"
    preview_bytes = base64.b64decode(preview_b64)
    assert preview_bytes[:8] == b"\x89PNG\r\n\x1a\n", "preview is not a PNG"

    # 2. Export to STL
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
    # Binary STL: 80-byte header + 4-byte triangle count, then 50 bytes/tri.
    # A box is 12 triangles. ASCII STL starts with b"solid". Accept either.
    is_binary_stl = len(stl_bytes) >= 84
    is_ascii_stl = stl_bytes[:5].lower() == b"solid"
    assert is_binary_stl or is_ascii_stl, (
        f"exported bytes don't look like STL (len={len(stl_bytes)}, "
        f"head={stl_bytes[:16]!r})"
    )


def test_render_section_via_mcp(partsmith_url):
    """create_model -> render_section returns an inline PNG (v0.2.6 tool live)."""
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

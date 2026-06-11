# SPDX-FileCopyrightText: 2026 JLay2026
# SPDX-License-Identifier: MIT
"""Integration: MCP transport handshake + tool surface inventory.

Catches the four v0.2.x deploy regressions:
- v0.2.1: MCP lifespan crash (Task group not initialized)
- v0.2.1: clean /mcp/ URL (was double-prefixed /mcp/mcp/)
- v0.2.2: DNS rebinding 421 (rejected non-localhost Host)
- v0.2.3: stateful long-poll hangs (Cowork 2-17 min hang)

Plus surface-area checks for tool additions in v0.2.4, v0.2.6, v0.2.7.
"""

import requests

_MCP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


def _initialize(partsmith_url):
    """Send the MCP initialize handshake. Returns the parsed JSON-RPC response."""
    r = requests.post(
        f"{partsmith_url}/mcp/",
        headers=_MCP_HEADERS,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "ci-integration", "version": "0"},
            },
        },
        timeout=15,
    )
    return r


def test_mcp_initialize_returns_partsmith_serverinfo(partsmith_url):
    """POST /mcp/ initialize returns serverInfo.name == 'partsmith'.

    Also confirms:
    - 200 OK (not 421 from DNS rebinding nor 404 from URL double-prefix)
    - Content-Type: application/json (not text/event-stream; that would
      mean FastMCP regressed back to stateful long-poll mode)
    """
    r = _initialize(partsmith_url)
    assert r.status_code == 200, (
        f"MCP initialize returned {r.status_code}: {r.text[:300]}"
    )
    ctype = r.headers.get("Content-Type", "")
    assert "application/json" in ctype, (
        f"Expected Content-Type application/json (stateless mode), "
        f"got {ctype!r}. If text/event-stream, the server is back on "
        f"stateful long-poll mode -- this is the v0.2.3 regression."
    )
    body = r.json()
    assert body.get("jsonrpc") == "2.0"
    assert "result" in body, f"Missing result in {body!r}"
    server_info = body["result"].get("serverInfo", {})
    assert server_info.get("name") == "partsmith", (
        f"Expected serverInfo.name 'partsmith', got {server_info!r}"
    )


def test_mcp_tools_list_includes_expected_surface(partsmith_url):
    """tools/list returns the full partsmith_* tool inventory.

    Bands the test by version cohort so a new tool added in vX.Y.Z is
    a clear addition to the relevant set rather than a sweeping change
    to one big list.
    """
    # Initialize first; even in stateless mode the spec mandates it
    init_resp = _initialize(partsmith_url)
    assert init_resp.status_code == 200, (
        f"Initialize prerequisite failed: {init_resp.status_code}"
    )

    r = requests.post(
        f"{partsmith_url}/mcp/",
        headers=_MCP_HEADERS,
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        timeout=15,
    )
    assert r.status_code == 200, (
        f"tools/list returned {r.status_code}: {r.text[:300]}"
    )
    body = r.json()
    tools = body.get("result", {}).get("tools", [])
    tool_names = {t["name"] for t in tools}

    # Core tools (since v0.2.0)
    core = {
        "partsmith_health",
        "partsmith_create_model",
        "partsmith_modify_model",
        "partsmith_list_models",
        "partsmith_measure_model",
        "partsmith_render_3d",
        "partsmith_render_2d",
        "partsmith_render_multiview",
        "partsmith_export",
        "partsmith_analyze_printability",
    }
    missing_core = core - tool_names
    assert not missing_core, f"Missing v0.2.0 core tools: {missing_core}"

    # Design store (v0.2.4)
    design = {
        "partsmith_save_design",
        "partsmith_load_design",
        "partsmith_list_designs",
        "partsmith_delete_design",
    }
    missing_design = design - tool_names
    assert not missing_design, f"Missing v0.2.4 design-store tools: {missing_design}"

    # Cross-section (v0.2.6)
    assert "partsmith_render_section" in tool_names, (
        "Missing v0.2.6 partsmith_render_section"
    )

    # Versioning (v0.2.7)
    versioning = {"partsmith_list_versions", "partsmith_diff_designs"}
    missing_versioning = versioning - tool_names
    assert not missing_versioning, (
        f"Missing v0.2.7 versioning tools: {missing_versioning}"
    )

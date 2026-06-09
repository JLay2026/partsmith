# SPDX-FileCopyrightText: 2026 JLay2026
# SPDX-License-Identifier: MIT
"""
MCP Streamable-HTTP transport for partsmith.

Wraps the same CADEngine + renderer + printability functions used by the
REST layer as MCP tools, so URL-based MCP clients (e.g. Cowork's managed
MCP UI) can drive partsmith directly with no intermediate shim process.

File-returning tools (render_*, export) return small payloads inline as
base64; payloads above ``INLINE_MAX_BYTES`` (default 8 MiB) are written
to the workspace and returned as a ``url_path`` the client GETs back
through the same Authentik perimeter.

All MCP tool names are prefixed ``partsmith_`` to avoid collisions in
multi-server MCP setups (Cowork can have several servers registered).

The MCP app is mounted at ``/mcp`` on the FastAPI app and inherits the
same auth perimeter — no separate auth in this module.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from . import __version__
from .cad_engine import CADEngine
from .printability import analyze as analyze_printability
from .renderer import render_2d, render_3d, render_multiview

# Files at or under this size are inlined as base64 in the tool result.
# Larger files persist to ``workspace`` and the tool returns a relative
# ``url_path`` the client fetches via GET (same Authentik creds).
#
# 8 MiB is a deliberate sweet spot:
#   - typical STLs (cubes, brackets, simple parts) are well under 1 MiB
#   - complex prints (textured, high-poly) can reach 5-15 MiB
#   - base64 inflates ~33%, so 8 MiB raw -> ~11 MiB on the wire
#   - keeps individual tool responses well below typical client budgets
INLINE_MAX_BYTES = int(
    os.environ.get("PARTSMITH_INLINE_MAX_BYTES", str(8 * 1024 * 1024))
)


def _file_response(data: bytes, filename: str, content_type: str) -> dict:
    """Return either a base64-inlined file or a URL pointer, based on size.

    Caller is responsible for ensuring ``filename`` has already been
    persisted under ``workspace`` when the response is a URL pointer.
    """
    size = len(data)
    if size <= INLINE_MAX_BYTES:
        return {
            "filename": filename,
            "content_type": content_type,
            "size_bytes": size,
            "inline": True,
            "data_b64": base64.b64encode(data).decode("ascii"),
        }
    return {
        "filename": filename,
        "content_type": content_type,
        "size_bytes": size,
        "inline": False,
        "url_path": f"/workspace/{filename}",
        "note": (
            f"File ({size} bytes) exceeds the {INLINE_MAX_BYTES}-byte "
            "inline cap. Fetch it via GET on the partsmith base URL + "
            "url_path (same auth headers as this MCP call)."
        ),
    }


def build_mcp(engine: CADEngine, workspace_dir: Path) -> FastMCP:
    """Build a FastMCP server exposing partsmith tools.

    Tools share the same ``engine`` instance as the REST layer, so a
    model created via MCP can be measured via REST and vice versa.
    """
    mcp = FastMCP("partsmith")

    # -- helpers --------------------------------------------------

    def _do_create(code: str, name: str) -> dict:
        """Shared implementation for create + modify tools."""
        result = engine.execute_code(code, name)
        if result.get("success") and result.get("geometry"):
            state = engine.get(name)
            if state and state.shape:
                try:
                    png = render_3d(state.shape, view="iso")
                    result["preview_data_b64"] = base64.b64encode(png).decode("ascii")
                    result["preview_content_type"] = "image/png"
                except Exception as e:
                    # Render failure shouldn't fail the create -- geometry
                    # is the source of truth, preview is convenience.
                    result["preview_error"] = str(e)
        return result

    def _need_shape(name: str):
        """Return (state, error_dict_or_none). Tools call this at entry."""
        state = engine.get(name)
        if not state or not state.shape:
            return None, {"error": f"No model '{name}' found"}
        return state, None

    # -- tools ----------------------------------------------------

    @mcp.tool()
    def partsmith_health() -> dict:
        """Liveness check. Returns server status, version, and transport."""
        return {
            "status": "ok",
            "version": __version__,
            "transport": "mcp/streamable-http",
        }

    @mcp.tool()
    def partsmith_create_model(code: str, name: str = "default") -> dict:
        """Execute build123d Python code and register the resulting shape.

        The code must produce a final shape, assigned to a variable
        named ``result`` (preferred) or any Part / Solid / Compound. The
        execution namespace has ``from build123d import *`` and
        ``import numpy as np`` pre-loaded.

        Names are validated [a-zA-Z0-9_-]{1,64}. The model registry is
        in-memory and bounded at 32 entries (LRU). On success a small
        iso-view preview PNG is returned inline as ``preview_data_b64``.

        Args:
            code: build123d Python source to execute.
            name: Model identifier (default "default"). Used for export
                  filenames and cross-call retrieval.

        Returns dict with: success (bool), stdout, error, geometry
        (bounding box / volume / surface area), and optionally
        preview_data_b64.
        """
        return _do_create(code, name)

    @mcp.tool()
    def partsmith_modify_model(code: str, name: str = "default") -> dict:
        """Re-execute build123d code under an existing model name.

        Functionally identical to ``partsmith_create_model`` -- provided
        as a separate tool to express intent at the call site (the LLM
        is iterating on an existing design vs. starting fresh).
        """
        return _do_create(code, name)

    @mcp.tool()
    def partsmith_list_models() -> dict:
        """List all currently-loaded models with summary geometry.

        Registry is in-memory; container restart wipes it. Models are
        kept in a 32-entry LRU bound -- least-recently-accessed evict
        first when capacity is reached.
        """
        return {"models": engine.list_all()}

    @mcp.tool()
    def partsmith_measure_model(name: str = "default") -> dict:
        """Return bounding box, volume, surface area, and topology counts.

        Faster than create+geometry because no re-execution; relies on
        the previously-built shape. Returns ``{"error": ...}`` if the
        model isn't loaded.
        """
        return engine.measure(name)

    @mcp.tool()
    def partsmith_render_3d(name: str = "default", view: str = "iso") -> dict:
        """Render a 3D shaded view of a loaded model.

        Args:
            name: Model identifier (default "default").
            view: One of front, back, left, right, top, bottom, iso,
                  iso_back. Defaults to iso.

        Returns a PNG as base64 (inline) when small, or a URL pointer
        for files exceeding the 8 MiB cap (renders almost never do).
        """
        state, err = _need_shape(name)
        if err:
            return err
        png = render_3d(state.shape, view=view)
        return _file_response(png, f"{name}_3d_{view}.png", "image/png")

    @mcp.tool()
    def partsmith_render_2d(
        name: str = "default",
        view: str = "front",
        with_dimensions: bool = True,
    ) -> dict:
        """Render a 2D orthographic projection of a loaded model.

        Args:
            name: Model identifier (default "default").
            view: One of front, back, left, right, top, bottom. Default
                  "front". Mirrored axes are handled per view.
            with_dimensions: Overlay width/height annotation (mm) in the
                  upper-left of the image. Default True.

        Returns a PNG as base64 (inline) when small, otherwise a URL.
        """
        state, err = _need_shape(name)
        if err:
            return err
        png = render_2d(state.shape, view=view, with_dimensions=with_dimensions)
        return _file_response(png, f"{name}_2d_{view}.png", "image/png")

    @mcp.tool()
    def partsmith_render_multiview(name: str = "default") -> dict:
        """Render a 2x2 composite -- front + right + top + iso shaded.

        Useful as a single overview image for AI agents reviewing
        geometry without making three separate calls. Returns a PNG as
        base64 inline (or URL pointer if it ever exceeds 8 MiB).
        """
        state, err = _need_shape(name)
        if err:
            return err
        png = render_multiview(state.shape)
        return _file_response(png, f"{name}_multiview.png", "image/png")

    @mcp.tool()
    def partsmith_export(name: str = "default", format: str = "stl") -> dict:
        """Export a loaded model to STL, STEP, or 3MF.

        Args:
            name: Model identifier (default "default").
            format: One of "stl", "step", "3mf". 3MF falls back to STL
                   if the installed build123d lacks ``export_3mf``.

        Returns the file inline as base64 when <= 8 MiB; for larger
        files persists to the workspace and returns a ``url_path``
        the client should GET (with the same auth headers as this MCP
        call) to fetch the bytes.
        """
        if format not in ("stl", "step", "3mf"):
            return {
                "error": f"Unsupported format '{format}'. Use stl, step, or 3mf."
            }
        try:
            path = engine.export(name, format)
        except (ValueError, RuntimeError) as e:
            return {"error": str(e)}
        except OSError as e:
            return {
                "error": (
                    f"Export write failed: {e}. Check that {workspace_dir} "
                    "is writable by uid 1000."
                )
            }
        try:
            data = path.read_bytes()
        except OSError as e:
            return {"error": f"Export read-back failed: {e}"}
        content_type = {
            "stl": "model/stl",
            "step": "application/STEP",
            "3mf": "model/3mf",
        }[format]
        return _file_response(data, path.name, content_type)

    @mcp.tool()
    def partsmith_analyze_printability(
        name: str = "default",
        min_wall_thickness_mm: float = 0.8,
    ) -> dict:
        """Run a trimesh-based printability check on a loaded model.

        Checks: watertight (no holes), valid closed volume, smallest
        bounding-box dimension vs the wall-thickness floor, degenerate
        face count.

        Args:
            name: Model identifier (default "default").
            min_wall_thickness_mm: Floor for the smallest-dim check
                  (default 0.8 mm -- a reasonable PLA / 0.4 nozzle floor).

        Returns is_watertight, is_volume, euler_number, face_count,
        volume_mm3, surface_area_mm2, bounding_box_mm, min_dim_mm,
        issues (list of strings), and a ``printable`` boolean (no issues).
        """
        state, err = _need_shape(name)
        if err:
            return err
        return analyze_printability(
            state.shape, min_wall_thickness_mm=min_wall_thickness_mm
        )

    return mcp

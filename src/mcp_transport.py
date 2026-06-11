# SPDX-FileCopyrightText: 2026 JLay2026
# SPDX-License-Identifier: MIT
"""
MCP Streamable-HTTP transport for partsmith.

Wraps the same CADEngine + renderer + printability + design store
functions used by the REST layer as MCP tools, so URL-based MCP clients
(e.g. Cowork's managed MCP UI) can drive partsmith directly with no
intermediate shim process.

File-returning tools (render_*, export) return small payloads inline as
base64; payloads above ``INLINE_MAX_BYTES`` (default 8 MiB) are written
to the workspace and returned as a ``url_path`` the client GETs back
through the same auth perimeter.

All MCP tool names are prefixed ``partsmith_`` to avoid collisions in
multi-server MCP setups (Cowork can have several servers registered).

The MCP app is mounted at ``/mcp`` on the FastAPI app and inherits the
same auth perimeter — no separate auth in this module.

v0.2.4: adds 4 design-store tools (save/load/list/delete) backed by
the on-disk DesignStore.

v0.2.6 (issue #8): adds partsmith_render_section — 2D cross-section
through a loaded model. Highest-leverage move for in-line viz: see
internal cavities, wall thickness, etc. without exporting STL.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from . import __version__
from .cad_engine import CADEngine
from .design_store import DesignStore
from .printability import analyze as analyze_printability
from .renderer import render_2d, render_3d, render_multiview, render_section

INLINE_MAX_BYTES = int(
    os.environ.get("PARTSMITH_INLINE_MAX_BYTES", str(8 * 1024 * 1024))
)


def _file_response(data: bytes, filename: str, content_type: str) -> dict:
    """Return either a base64-inlined file or a URL pointer, based on size."""
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


def build_mcp(
    engine: CADEngine,
    workspace_dir: Path,
    store: DesignStore,
) -> FastMCP:
    """Build a FastMCP server exposing partsmith tools."""
    mcp = FastMCP("partsmith")

    def _do_create(code: str, name: str) -> dict:
        result = engine.execute_code(code, name)
        if result.get("success") and result.get("geometry"):
            state = engine.get(name)
            if state and state.shape:
                try:
                    png = render_3d(state.shape, view="iso")
                    result["preview_data_b64"] = base64.b64encode(png).decode("ascii")
                    result["preview_content_type"] = "image/png"
                except Exception as e:
                    result["preview_error"] = str(e)
        return result

    def _need_shape(name: str):
        state = engine.get(name)
        if not state or not state.shape:
            return None, {"error": f"No model '{name}' found"}
        return state, None

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
        ``import numpy as np`` pre-loaded, plus the partsmith_helpers
        seven functions (through_hole, screw_hole, hex_hole, slot,
        chamfer_edges, fillet_top_edges, screw_pattern).

        Names are validated [a-zA-Z0-9_-]{1,64}. The model registry is
        in-memory and bounded at 32 entries (LRU). On success a small
        iso-view preview PNG is returned inline as ``preview_data_b64``.

        Args:
            code: build123d Python source to execute.
            name: Model identifier (default "default").

        Returns dict with: success (bool), stdout, error, geometry,
        and optionally preview_data_b64.

        Note: models are in-memory only. Use partsmith_save_design to
        persist source code that survives container restart.
        """
        return _do_create(code, name)

    @mcp.tool()
    def partsmith_modify_model(code: str, name: str = "default") -> dict:
        """Re-execute build123d code under an existing model name.

        Functionally identical to ``partsmith_create_model`` -- provided
        as a separate tool to express intent at the call site.
        """
        return _do_create(code, name)

    @mcp.tool()
    def partsmith_list_models() -> dict:
        """List all currently-loaded models with summary geometry."""
        return {"models": engine.list_all()}

    @mcp.tool()
    def partsmith_measure_model(name: str = "default") -> dict:
        """Return bounding box, volume, surface area, and topology counts."""
        return engine.measure(name)

    @mcp.tool()
    def partsmith_render_3d(name: str = "default", view: str = "iso") -> dict:
        """Render a 3D shaded view of a loaded model.

        Args:
            name: Model identifier (default "default").
            view: One of front, back, left, right, top, bottom, iso,
                  iso_back. Defaults to iso.

        Returns a PNG as base64 (inline) when small.
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
            view: One of front, back, left, right, top, bottom.
            with_dimensions: Overlay W/H annotation. Default True.

        Returns a PNG as base64.
        """
        state, err = _need_shape(name)
        if err:
            return err
        png = render_2d(state.shape, view=view, with_dimensions=with_dimensions)
        return _file_response(png, f"{name}_2d_{view}.png", "image/png")

    @mcp.tool()
    def partsmith_render_multiview(name: str = "default") -> dict:
        """Render a 2x2 composite -- front + right + top + iso shaded."""
        state, err = _need_shape(name)
        if err:
            return err
        png = render_multiview(state.shape)
        return _file_response(png, f"{name}_multiview.png", "image/png")

    @mcp.tool()
    def partsmith_render_section(
        name: str = "default",
        plane: str = "YZ",
        at: float = 0.0,
        with_dimensions: bool = True,
    ) -> dict:
        """Render a 2D cross-section through a loaded model.

        Use this to see INSIDE a design -- internal cavities, wall
        thickness, snap-fit clearances, screw-hole bottoms, ribs --
        without exporting STL and opening in a slicer. Single biggest
        in-line viz lever for iterate-by-AI-chat workflows.

        Plane conventions:
            "XY" - horizontal slice (normal = Z), look down from above.
                   at = Z-coordinate of the slice.
            "XZ" - front-view vertical slice (normal = Y).
                   at = Y-coordinate.
            "YZ" - right-view vertical slice (normal = X). DEFAULT.
                   at = X-coordinate. Through-origin slice on most
                   models centered at X=0.

        Args:
            name: Model identifier (default "default").
            plane: One of "XY", "XZ", "YZ". Default "YZ".
            at: Offset along the plane's normal axis in mm. Default 0.0.
                Use partsmith_measure_model to find bbox extents and
                pick a value INSIDE the geometry.
            with_dimensions: Overlay section W/H callout (mm). Default True.

        Returns a PNG as base64. If the plane doesn't intersect the
        geometry, returns a placeholder PNG with the valid range so
        the caller can self-correct (does NOT raise).

        Tip: pair with partsmith_measure_model to pick `at` values.
        Cross-section at midpoint of a bounding axis usually reveals
        the most structural detail.
        """
        state, err = _need_shape(name)
        if err:
            return err
        try:
            png = render_section(
                state.shape,
                plane=plane,
                at=at,
                with_dimensions=with_dimensions,
            )
        except ValueError as e:
            return {"error": str(e)}
        # Encode at into filename: 0.50 -> 0p50, -3.25 -> neg3p25
        at_label = f"{at:.2f}".replace(".", "p").replace("-", "neg")
        return _file_response(
            png,
            f"{name}_section_{plane}_{at_label}.png",
            "image/png",
        )

    @mcp.tool()
    def partsmith_export(name: str = "default", format: str = "stl") -> dict:
        """Export a loaded model to STL, STEP, or 3MF."""
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
        """Run a trimesh-based printability check on a loaded model."""
        state, err = _need_shape(name)
        if err:
            return err
        return analyze_printability(
            state.shape, min_wall_thickness_mm=min_wall_thickness_mm
        )

    @mcp.tool()
    def partsmith_save_design(
        name: str,
        code: str,
        description: str = "",
    ) -> dict:
        """Save a design's source code to disk so it survives container restart."""
        geometry = None
        execution_result = engine.execute_code(code, name)
        if execution_result.get("success") and execution_result.get("geometry"):
            geometry = execution_result["geometry"]

        try:
            metadata = store.save(
                name, code, description=description, geometry=geometry
            )
        except ValueError as e:
            return {"error": f"Invalid name: {e}"}
        except OSError as e:
            return {
                "error": (
                    f"Save failed: {e}. Check that {store.designs_dir} is "
                    "writable by uid 1000 (the container user)."
                )
            }

        return {
            "saved": True,
            "execution": {
                "success": execution_result.get("success", False),
                "error": execution_result.get("error"),
                "geometry": execution_result.get("geometry"),
            },
            "metadata": metadata.to_dict(),
        }

    @mcp.tool()
    def partsmith_load_design(name: str) -> dict:
        """Load a saved design from disk and execute it as a model."""
        try:
            code, metadata = store.load(name)
        except FileNotFoundError:
            return {"error": f"Design not found: {name}"}
        except ValueError as e:
            return {"error": f"Invalid name: {e}"}

        result = _do_create(code, name)
        result["loaded_from"] = "design_store"
        result["design_metadata"] = metadata.to_dict()
        return result

    @mcp.tool()
    def partsmith_list_designs() -> dict:
        """List all saved designs with their metadata."""
        return {"designs": [m.to_dict() for m in store.list_all()]}

    @mcp.tool()
    def partsmith_delete_design(name: str) -> dict:
        """Delete a saved design from disk (both .py source + .json metadata)."""
        try:
            deleted = store.delete(name)
        except ValueError as e:
            return {"error": f"Invalid name: {e}"}
        except OSError as e:
            return {"error": f"Delete failed: {e}"}
        return {"deleted": deleted, "name": name}

    return mcp

# SPDX-FileCopyrightText: 2026 JLay2026
# SPDX-License-Identifier: MIT
"""
MCP Streamable-HTTP transport for partsmith.

v0.2.4: design store tools (save/load/list/delete).
v0.2.6 (issue #8): partsmith_render_section.
v0.2.7 (issue #3): partsmith_list_versions, partsmith_diff_designs.
                   save/load/delete tools accept optional version.
v0.3.4 (issue #12): partsmith_render_drawing (dimensioned 2D drawing).
v0.3.5 (issue #15): robust artifact delivery. Every file response now
                   carries sha256 + size_bytes so a client can verify
                   the bytes it materializes (catches silent truncation,
                   e.g. a shell-heredoc write that got cut off), and
                   exports always expose a fetchable url_path fallback,
                   not just files over the inline cap.
"""
from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
from typing import Optional, Union

from mcp.server.fastmcp import FastMCP

from . import __version__
from .cad_engine import CADEngine
from .design_store import DesignStore
from .printability import analyze as analyze_printability
from .renderer import (
    render_2d,
    render_3d,
    render_drawing,
    render_multiview,
    render_section,
)

INLINE_MAX_BYTES = int(
    os.environ.get("PARTSMITH_INLINE_MAX_BYTES", str(8 * 1024 * 1024))
)

# Extensions that GET /workspace/{filename} will actually serve (the
# server's own allow-list). url_path is only advertised for these; render
# PNGs live in the renders dir, are not persisted to the workspace, and
# must travel inline.
_FETCHABLE_EXTS = frozenset(("stl", "step", "3mf"))

# Guidance attached to every inline payload. Read by the calling agent.
_INTEGRITY_NOTE = (
    "Verify before trusting: decode data_b64 to bytes, then assert "
    "len(bytes) == size_bytes AND sha256(bytes) == sha256. Materialize "
    "with a real binary write (e.g. base64 -d, or Python "
    "open(path,'wb').write(...)). Do NOT paste via a shell heredoc / "
    "echo -- long base64 truncates silently that way. On any mismatch, "
    "call this tool again rather than keeping the partial file."
)


def _file_response(data: bytes, filename: str, content_type: str) -> dict:
    """Build a file-delivery dict for an MCP tool result.

    v0.3.5: always includes ``size_bytes`` + ``sha256`` so the caller can
    verify whatever it writes to disk; always includes ``url_path`` for
    workspace-servable exports (stl/step/3mf) as a transcription-free
    fallback. Small files still inline ``data_b64`` by default for
    back-compat; large files (> INLINE_MAX_BYTES) are url-only.
    """
    size = len(data)
    sha256 = hashlib.sha256(data).hexdigest()
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    out: dict = {
        "filename": filename,
        "content_type": content_type,
        "size_bytes": size,
        "sha256": sha256,
        "inline": size <= INLINE_MAX_BYTES,
    }

    # Fetchable fallback for anything the workspace endpoint can serve.
    if ext in _FETCHABLE_EXTS:
        out["url_path"] = f"/workspace/{filename}"

    if out["inline"]:
        out["data_b64"] = base64.b64encode(data).decode("ascii")
        out["integrity_note"] = _INTEGRITY_NOTE
    else:
        note = (
            f"File ({size} bytes) exceeds the {INLINE_MAX_BYTES}-byte "
            "inline cap. "
        )
        if "url_path" in out:
            note += (
                "Fetch it via GET on the partsmith base URL + url_path "
                "(same auth headers as this MCP call), then verify "
                "sha256 + size_bytes."
            )
        else:
            note += (
                "This artifact is not workspace-servable; re-request with "
                "a smaller output or a different format."
            )
        out["note"] = note

    return out


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

        Execution namespace includes ``from build123d import *``,
        ``import numpy as np``, plus seven partsmith_helpers
        (through_hole, screw_hole, hex_hole, slot, chamfer_edges,
        fillet_top_edges, screw_pattern).

        Models are in-memory only. Use partsmith_save_design to persist
        source code that survives container restart (versioned).
        """
        return _do_create(code, name)

    @mcp.tool()
    def partsmith_modify_model(code: str, name: str = "default") -> dict:
        """Re-execute build123d code under an existing model name."""
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
        """Render a 2D orthographic projection of a loaded model."""
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
        thickness, snap-fit clearances. Plane conventions:
            "XY" - horizontal slice (normal Z), at = Z-coord.
            "XZ" - front-view vertical slice (normal Y), at = Y-coord.
            "YZ" - right-view vertical slice (normal X), at = X-coord.
                   DEFAULT, through origin.

        Pair with partsmith_measure_model to pick `at` values from bbox.
        """
        state, err = _need_shape(name)
        if err:
            return err
        try:
            png = render_section(
                state.shape, plane=plane, at=at,
                with_dimensions=with_dimensions,
            )
        except ValueError as e:
            return {"error": str(e)}
        at_label = f"{at:.2f}".replace(".", "p").replace("-", "neg")
        return _file_response(
            png, f"{name}_section_{plane}_{at_label}.png", "image/png",
        )

    @mcp.tool()
    def partsmith_render_drawing(
        name: str = "default",
        view: str = "front",
        part_name: str = "",
    ) -> dict:
        """Render an engineering-style dimensioned 2D drawing.

        Unlike partsmith_render_2d (which overlays a plain W/H text box),
        this draws proper overall dimension lines -- extension lines,
        double-headed arrows, and the measured width/height centered on
        each -- plus a title block. Use it to confirm a part's real size
        before slicing ("is this bracket actually 50 mm wide?").

        Args:
            name: Model identifier (default "default").
            view: One of front, back, left, right, top, bottom.
                  Default "front".
            part_name: Title-block part name. Defaults to the model name.

        Overall width + height only in v0.3.4. Feature callouts (hole
        diameters, center-to-center spacing) are a planned follow-up.
        """
        state, err = _need_shape(name)
        if err:
            return err
        png = render_drawing(
            state.shape, view=view, part_name=(part_name or name),
        )
        return _file_response(png, f"{name}_drawing_{view}.png", "image/png")

    @mcp.tool()
    def partsmith_export(name: str = "default", format: str = "stl") -> dict:
        """Export a loaded model to STL, STEP, or 3MF.

        Returns a file-delivery dict (v0.3.5):
            filename, content_type, size_bytes, sha256, inline,
            url_path (for stl/step/3mf), and data_b64 when inline.

        IMPORTANT -- materialize safely: decode ``data_b64`` to bytes and
        verify ``len == size_bytes`` and ``sha256`` matches before
        trusting the file. Write the bytes with a real binary write
        (``base64 -d``, or Python ``open(p,'wb').write(...)``). Do NOT
        paste base64 through a shell heredoc / echo -- it truncates
        silently for non-trivial files. If verification fails, just call
        partsmith_export again (the server is the source of truth; never
        keep a partial file). For larger exports, fetch ``url_path`` over
        HTTP instead of transcribing inline.
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
        """Run a trimesh-based printability check on a loaded model."""
        state, err = _need_shape(name)
        if err:
            return err
        return analyze_printability(
            state.shape, min_wall_thickness_mm=min_wall_thickness_mm
        )

    # -- v0.2.4 + v0.2.7: design store tools ----------------

    @mcp.tool()
    def partsmith_save_design(
        name: str,
        code: str,
        description: str = "",
        version: Union[int, str] = "auto",
    ) -> dict:
        """Save a design version to disk.

        v0.2.7: designs are now versioned. The file layout is
        ``{workspace}/designs/{name}/v1.py``, ``v2.py``, ``v3.py``, etc.
        plus matching ``.json`` sidecars.

        Args:
            name: Design identifier (NAME_PATTERN-validated).
            code: build123d Python source. Stored verbatim.
            description: Optional free-form description (max 500 chars).
            version: "auto" (default) appends the next unused version;
                an int targets that specific version, overwriting any
                existing content at that slot. Use "auto" for normal
                iteration; use an explicit int only to fix a previously
                bad version in place.

        Side effect: also executes the code as a model under ``name`` so
        the result is immediately available for render / measure /
        export. If execution fails the save still succeeds (source is
        the source of truth; user can fix and re-save).

        Returns:
            saved (bool), execution (dict with success/error/geometry),
            metadata (dict including version, created_at, last_modified).
        """
        geometry = None
        execution_result = engine.execute_code(code, name)
        if execution_result.get("success") and execution_result.get("geometry"):
            geometry = execution_result["geometry"]

        try:
            metadata = store.save(
                name, code, description=description, geometry=geometry,
                version=version,
            )
        except ValueError as e:
            return {"error": f"Invalid name or version: {e}"}
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
    def partsmith_load_design(
        name: str,
        version: Optional[int] = None,
    ) -> dict:
        """Load a saved design from disk and execute it as a model.

        v0.2.7: optional version (default = latest). Pre-v0.2.7 designs
        in the legacy flat layout are exposed as version 1
        transparently.

        Args:
            name: Design identifier (must exist in the design store).
            version: Specific version int, or None (default) for latest.

        Returns same shape as partsmith_create_model plus:
            loaded_from: "design_store"
            design_metadata: persisted metadata (includes version)
        """
        try:
            code, metadata = store.load(name, version=version)
        except FileNotFoundError:
            return {"error": f"Design not found: {name}"}
        except ValueError as e:
            return {"error": f"Invalid name or version: {e}"}

        result = _do_create(code, name)
        result["loaded_from"] = "design_store"
        result["design_metadata"] = metadata.to_dict()
        return result

    @mcp.tool()
    def partsmith_list_designs() -> dict:
        """List all saved designs (latest version of each).

        Returns one entry per design name. Use partsmith_list_versions
        to see all versions of a specific design.
        """
        return {"designs": [m.to_dict() for m in store.list_all()]}

    @mcp.tool()
    def partsmith_list_versions(name: str) -> dict:
        """v0.2.7: list version numbers for a saved design.

        Args:
            name: Design identifier.

        Returns:
            name, versions (list[int], sorted ascending).
            Empty list if the design has no saved versions.
        """
        try:
            versions = store.list_versions(name)
        except ValueError as e:
            return {"error": f"Invalid name: {e}"}
        return {"name": name, "versions": versions}

    @mcp.tool()
    def partsmith_diff_designs(
        name: str,
        v1: int,
        v2: int,
    ) -> dict:
        """v0.2.7: diff two versions of a saved design.

        Compares v1 (older) to v2 (newer) and returns:
            source_diff: unified diff text (3 lines of context)
            volume_delta_mm3: v2 volume - v1 volume (or null)
            surface_area_delta_mm2: v2 - v1 (or null)
            bbox_size_delta_mm: [dx, dy, dz] (v2 - v1) or null
            face_count_delta / edge_count_delta / vertex_count_delta:
                B-rep topology deltas (v0.3.3; null if not captured)
            v1_metadata, v2_metadata: full metadata dicts

        Negative deltas mean v2 is smaller/lighter than v1.

        Use partsmith_list_versions(name) first to see available
        version numbers. Both v1 and v2 must already exist.

        Args:
            name: Design identifier.
            v1: From-version (older), positive int.
            v2: To-version (newer), positive int.
        """
        try:
            return store.diff(name, v1=v1, v2=v2)
        except FileNotFoundError as e:
            return {"error": str(e)}
        except ValueError as e:
            return {"error": str(e)}

    @mcp.tool()
    def partsmith_delete_design(
        name: str,
        version: Optional[int] = None,
    ) -> dict:
        """Delete a saved design version(s) from disk.

        v0.2.7: optional version param.
            version=None (default): delete ALL versions (and the
                design directory).
            version=int: delete just that version (leaves others
                intact).

        Does NOT remove any in-memory model with the same name; that
        survives until the next partsmith_create_model call overwrites
        it, container restart, or LRU eviction.

        Args:
            name: Design identifier.
            version: Specific version to delete, or None for all.

        Returns:
            deleted (bool): True if anything was removed.
            name (str): echoed back.
            version: echoed back (None means all).
        """
        try:
            deleted = store.delete(name, version=version)
        except ValueError as e:
            return {"error": f"Invalid name or version: {e}"}
        except OSError as e:
            return {"error": f"Delete failed: {e}"}
        return {"deleted": deleted, "name": name, "version": version}

    return mcp
MCPEOF
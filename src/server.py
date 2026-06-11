# SPDX-FileCopyrightText: 2026 JLay2026
# SPDX-License-Identifier: MIT
"""
FastAPI server.

REST endpoint surface intentionally matches the shape expected by
existing build123d-MCP clients (notably the cad-agent-shim pattern),
so wiring is drop-in compatible.

This server does NO authentication. See SECURITY.md.

v0.1 hardening:
- Pydantic `Field` pattern validation on `name` blocks path traversal
- Custom middleware rejects request bodies over MAX_REQUEST_BYTES
- All model names path-validated again at engine.export() boundary

v0.1.3:
- All disk-write paths catch OSError and surface meaningful 500s
  (was: bare "Internal Server Error" on permission/write failure)

v0.2.0:
- Mounts FastMCP Streamable-HTTP transport at `/mcp` (tools prefixed
  `partsmith_*`). Shares the same `engine` instance as the REST layer
  so models created via either protocol are visible to the other.
- Adds `GET /workspace/{filename}` for the MCP large-file URL-pointer
  fallback (files > 8 MiB skip the base64 inline path).

v0.2.1:
- FastMCP lifespan integration (fixes Task group RuntimeError);
  streamable_http_path="/" override (clean /mcp/ URL);
  uvicorn --proxy-headers for behind-Caddy scheme handling.

v0.2.2:
- Disable FastMCP DNS rebinding protection (was rejecting non-localhost
  Host with 421).

v0.2.3:
- Stateless + json_response MCP mode (compatible with strict-spec MCP
  clients including Cowork's managed UI).

v0.2.4:
- Persistent design store (`src/design_store.py`). Designs survive
  container restart; models don't. 5 new REST endpoints under
  `/design/...` and 4 new MCP tools.

v0.2.6 (issue #8):
- Cross-section renderer. `render_section()` + POST /render/section
  + partsmith_render_section MCP tool.

v0.2.7 (issue #3):
- Versioned designs + diff. Each design is now a versioned trail
  (v1.py + v1.json, v2.py + v2.json, ...). 2 new REST endpoints:
  GET /design/{name}/versions and GET /design/{name}/diff. Existing
  save/load/delete endpoints accept an optional version parameter.
  Backward-compatible with v0.2.4-v0.2.6 flat layout.

v0.3.4 (issue #12):
- Dimensioned engineering drawings. `render_drawing()` + POST
  /render/drawing + partsmith_render_drawing MCP tool. Overall W/H
  dimension lines + title block; the plain render_2d W/H overlay stays.
"""

from __future__ import annotations

import base64
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, Union

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from . import __version__
from .cad_engine import CADEngine
from .design_store import DesignStore
from .mcp_transport import build_mcp
from .printability import analyze as analyze_printability
from .renderer import (
    render_2d,
    render_3d,
    render_drawing,
    render_multiview,
    render_section,
)

WORKSPACE = Path(os.environ.get("PARTSMITH_WORKSPACE", "/workspace"))
RENDERS = Path(os.environ.get("PARTSMITH_RENDERS", "/renders"))
WORKSPACE.mkdir(parents=True, exist_ok=True)
RENDERS.mkdir(parents=True, exist_ok=True)

MAX_REQUEST_BYTES = int(os.environ.get("PARTSMITH_MAX_BODY_BYTES", str(1 * 1024 * 1024)))

NAME_PATTERN = r"^[a-zA-Z0-9_-]{1,64}$"
_NAME_RE = re.compile(NAME_PATTERN)

_ALLOWED_EXPORT_EXTS = frozenset(("stl", "step", "3mf"))


def _validate_name(name: str) -> str:
    if not _NAME_RE.match(name):
        raise HTTPException(400, f"Invalid name: must match {NAME_PATTERN}")
    return name


def _safe_write(path: Path, data: bytes, context: str) -> None:
    try:
        path.write_bytes(data)
    except OSError as e:
        raise HTTPException(
            500,
            f"{context} write failed: {e}. "
            f"Check that {path.parent} is writable by uid 1000 "
            f"(the container user). See README 'First-time deploy'.",
        )


# ── Middleware ───────────────────────────────────────────

class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests whose Content-Length exceeds MAX_REQUEST_BYTES."""

    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/mcp"):
            return await call_next(request)
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                size = int(content_length)
            except ValueError:
                size = 0
            if size > MAX_REQUEST_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={
                        "detail": (
                            f"Request body {size} bytes exceeds limit "
                            f"of {MAX_REQUEST_BYTES} bytes"
                        )
                    },
                )
        return await call_next(request)


# ── App initialization ──────────────────────────────────

engine = CADEngine(workspace=WORKSPACE)
store = DesignStore(workspace=WORKSPACE)
_mcp_server = build_mcp(engine, WORKSPACE, store)

_mcp_server.settings.streamable_http_path = "/"
_mcp_server.settings.transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=False,
)
_mcp_server.settings.stateless_http = True
_mcp_server.settings.json_response = True

_mcp_asgi_app = _mcp_server.streamable_http_app()


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    async with _mcp_server.session_manager.run():
        yield


app = FastAPI(title="partsmith", version=__version__, lifespan=_lifespan)
app.add_middleware(BodySizeLimitMiddleware)


# ── Request schemas ──────────────────────────────────

class CreateModelRequest(BaseModel):
    code: str = Field(..., max_length=MAX_REQUEST_BYTES)
    name: str = Field("default", pattern=NAME_PATTERN, max_length=64)


class RenderRequest(BaseModel):
    name: Optional[str] = Field(None, pattern=NAME_PATTERN, max_length=64)
    view: str = Field("iso", pattern=r"^[a-z_]{1,16}$")
    with_dimensions: bool = True
    with_hidden: bool = True


class SectionRequest(BaseModel):
    name: Optional[str] = Field(None, pattern=NAME_PATTERN, max_length=64)
    plane: str = Field("YZ", pattern=r"^(XY|XZ|YZ)$")
    at: float = Field(0.0, ge=-10000.0, le=10000.0)
    with_dimensions: bool = True


class DrawingRequest(BaseModel):
    """v0.3.4: engineering drawing with overall dimension lines."""
    name: Optional[str] = Field(None, pattern=NAME_PATTERN, max_length=64)
    view: str = Field("front", pattern=r"^(front|back|left|right|top|bottom)$")
    part_name: Optional[str] = Field(None, max_length=64)


class ExportRequest(BaseModel):
    name: Optional[str] = Field(None, pattern=NAME_PATTERN, max_length=64)
    format: str = Field("stl", pattern=r"^(stl|step|3mf)$")


class PrintabilityRequest(BaseModel):
    name: Optional[str] = Field(None, pattern=NAME_PATTERN, max_length=64)
    min_wall_thickness: float = Field(0.8, ge=0.0, le=100.0)


class SaveDesignRequest(BaseModel):
    """v0.2.4: save a design. v0.2.7: optional version param."""
    code: str = Field(..., max_length=MAX_REQUEST_BYTES)
    name: str = Field(..., pattern=NAME_PATTERN, max_length=64)
    description: str = Field("", max_length=500)
    # v0.2.7: "auto" appends next unused version; int targets that slot.
    version: Union[int, str] = Field(default="auto")


# ── Health ───────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "version": __version__}


# ── Model lifecycle ──────────────────────────────────

@app.post("/model/create")
def create_model(req: CreateModelRequest):
    result = engine.execute_code(req.code, req.name)
    if result["success"] and result["geometry"]:
        state = engine.get(req.name)
        if state and state.shape:
            try:
                png = render_3d(state.shape, view="iso")
                result["preview_base64"] = base64.b64encode(png).decode("ascii")
                preview_path = RENDERS / f"{req.name}_preview.png"
                preview_path.write_bytes(png)
                result["preview_path"] = str(preview_path)
            except OSError as e:
                result["render_error"] = (
                    f"preview write failed: {e}. "
                    f"Check that {RENDERS} is writable by uid 1000."
                )
            except Exception as e:
                result["render_error"] = str(e)
    return result


@app.post("/model/modify")
def modify_model(req: CreateModelRequest):
    return create_model(req)


@app.get("/model/list")
def list_models():
    return {"models": engine.list_all()}


@app.get("/model/{name}/measure")
def measure_model(name: str = "default"):
    _validate_name(name)
    return engine.measure(name)


# ── Rendering ──────────────────────────────────────────────

@app.post("/render/3d")
def render_3d_endpoint(req: RenderRequest):
    state = engine.get(req.name)
    if not state or not state.shape:
        raise HTTPException(404, f"No model '{req.name or 'active'}' found")
    png = render_3d(state.shape, view=req.view)
    path = RENDERS / f"{state.name}_3d_{req.view}.png"
    _safe_write(path, png, "3D render")
    return {
        "path": str(path),
        "view": req.view,
        "base64": base64.b64encode(png).decode("ascii"),
    }


@app.post("/render/2d")
def render_2d_endpoint(req: RenderRequest):
    state = engine.get(req.name)
    if not state or not state.shape:
        raise HTTPException(404, f"No model '{req.name or 'active'}' found")
    png = render_2d(state.shape, view=req.view, with_dimensions=req.with_dimensions)
    path = RENDERS / f"{state.name}_2d_{req.view}.png"
    _safe_write(path, png, "2D render")
    return {
        "path": str(path),
        "view": req.view,
        "base64": base64.b64encode(png).decode("ascii"),
    }


@app.post("/render/multiview")
def render_multiview_endpoint(req: RenderRequest):
    state = engine.get(req.name)
    if not state or not state.shape:
        raise HTTPException(404, f"No model '{req.name or 'active'}' found")
    png = render_multiview(state.shape)
    path = RENDERS / f"{state.name}_multiview.png"
    _safe_write(path, png, "multiview render")
    return {
        "path": str(path),
        "base64": base64.b64encode(png).decode("ascii"),
    }


@app.post("/render/section")
def render_section_endpoint(req: SectionRequest):
    state = engine.get(req.name)
    if not state or not state.shape:
        raise HTTPException(404, f"No model '{req.name or 'active'}' found")
    try:
        png = render_section(
            state.shape,
            plane=req.plane,
            at=req.at,
            with_dimensions=req.with_dimensions,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    at_label = f"{req.at:.2f}".replace(".", "p").replace("-", "neg")
    fname = f"{state.name}_section_{req.plane}_{at_label}.png"
    path = RENDERS / fname
    _safe_write(path, png, "section render")
    return {
        "path": str(path),
        "plane": req.plane,
        "at": req.at,
        "base64": base64.b64encode(png).decode("ascii"),
    }


@app.post("/render/drawing")
def render_drawing_endpoint(req: DrawingRequest):
    """v0.3.4 (issue #12): engineering drawing with dimension lines."""
    state = engine.get(req.name)
    if not state or not state.shape:
        raise HTTPException(404, f"No model '{req.name or 'active'}' found")
    png = render_drawing(
        state.shape,
        view=req.view,
        part_name=req.part_name or state.name,
    )
    path = RENDERS / f"{state.name}_drawing_{req.view}.png"
    _safe_write(path, png, "drawing render")
    return {
        "path": str(path),
        "view": req.view,
        "base64": base64.b64encode(png).decode("ascii"),
    }


@app.post("/render/all")
def render_all_endpoint(req: RenderRequest):
    state = engine.get(req.name)
    if not state or not state.shape:
        raise HTTPException(404, f"No model '{req.name or 'active'}' found")
    out: dict[str, str] = {}
    for view in ("front", "right", "top"):
        png = render_2d(state.shape, view=view)
        p = RENDERS / f"{state.name}_2d_{view}.png"
        _safe_write(p, png, f"2D {view} render")
        out[f"2d_{view}"] = str(p)
    png = render_3d(state.shape, view="iso")
    p = RENDERS / f"{state.name}_3d_iso.png"
    _safe_write(p, png, "3D iso render")
    out["3d_iso"] = str(p)
    png = render_multiview(state.shape)
    p = RENDERS / f"{state.name}_multiview.png"
    _safe_write(p, png, "multiview render")
    out["multiview"] = str(p)
    return out


# ── Export ───────────────────────────────────────────────────

@app.post("/export")
def export_model(req: ExportRequest):
    try:
        path = engine.export(req.name, req.format)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e))
    except OSError as e:
        raise HTTPException(
            500,
            f"Export write failed: {e}. "
            f"Check that {engine.workspace} is writable by uid 1000.",
        )
    return FileResponse(
        path,
        filename=path.name,
        media_type="application/octet-stream",
    )


# ── Printability ─────────────────────────────────────────────

@app.post("/analyze/printability")
def analyze_printability_endpoint(req: PrintabilityRequest):
    state = engine.get(req.name)
    if not state or not state.shape:
        raise HTTPException(404, f"No model '{req.name or 'active'}' found")
    return analyze_printability(state.shape, min_wall_thickness_mm=req.min_wall_thickness)


# ── v0.2: workspace file serving ────

@app.get("/workspace/{filename}")
def serve_workspace_file(filename: str):
    safe = Path(filename).name
    if safe != filename or not safe:
        raise HTTPException(400, "Invalid filename")
    p = Path(safe)
    stem = p.stem
    ext = p.suffix.lstrip(".").lower()
    if not _NAME_RE.match(stem) or ext not in _ALLOWED_EXPORT_EXTS:
        raise HTTPException(400, "Invalid filename")
    target = (WORKSPACE / safe).resolve()
    try:
        target.relative_to(WORKSPACE.resolve())
    except ValueError:
        raise HTTPException(400, "Path escapes workspace")
    if not target.exists():
        raise HTTPException(404, "Not found")
    return FileResponse(
        target,
        filename=safe,
        media_type="application/octet-stream",
    )


# ── v0.2.4 + v0.2.7: persistent design store (REST) ──────────────

@app.post("/design/save")
def save_design(req: SaveDesignRequest):
    """Save a design version. v0.2.7: optional version param."""
    geometry = None
    execution_result = engine.execute_code(req.code, req.name)
    if execution_result.get("success") and execution_result.get("geometry"):
        geometry = execution_result["geometry"]

    try:
        metadata = store.save(
            req.name,
            req.code,
            description=req.description,
            geometry=geometry,
            version=req.version,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except OSError as e:
        raise HTTPException(
            500,
            f"Save failed: {e}. Check that {store.designs_dir} is writable by uid 1000.",
        )

    return {
        "saved": True,
        "execution": {
            "success": execution_result.get("success", False),
            "error": execution_result.get("error"),
            "geometry": execution_result.get("geometry"),
        },
        "metadata": metadata.to_dict(),
    }


@app.get("/design/list")
def list_designs():
    """List all saved designs (latest version of each)."""
    return {"designs": [m.to_dict() for m in store.list_all()]}


@app.get("/design/{name}/versions")
def list_design_versions(name: str):
    """v0.2.7: list all version numbers for a design."""
    _validate_name(name)
    try:
        versions = store.list_versions(name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not versions:
        raise HTTPException(404, f"Design not found: {name}")
    return {"name": name, "versions": versions}


@app.get("/design/{name}/diff")
def diff_design(
    name: str,
    v1: int = Query(..., ge=1),
    v2: int = Query(..., ge=1),
):
    """v0.2.7: diff two versions of a design.

    Returns unified source diff + geometry deltas (volume, surface area,
    bbox size). Both versions must exist; use ``/design/{name}/versions``
    to list available ones first.
    """
    _validate_name(name)
    try:
        return store.diff(name, v1=v1, v2=v2)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/design/{name}")
def get_design(
    name: str,
    version: Optional[int] = Query(None, ge=1),
):
    """Load a design's source code + metadata. v0.2.7: optional version
    (default = latest)."""
    _validate_name(name)
    try:
        code, metadata = store.load(name, version=version)
    except FileNotFoundError:
        raise HTTPException(404, f"Design not found: {name}")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"code": code, "metadata": metadata.to_dict()}


@app.delete("/design/{name}")
def delete_design(
    name: str,
    version: Optional[int] = Query(None, ge=1),
):
    """Delete design version(s). v0.2.7: optional version (default =
    nuke all versions)."""
    _validate_name(name)
    try:
        deleted = store.delete(name, version=version)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except OSError as e:
        raise HTTPException(500, f"Delete failed: {e}")
    if not deleted:
        raise HTTPException(404, f"Design not found: {name}")
    return {"deleted": True, "name": name, "version": version}


@app.post("/design/{name}/load")
def load_and_execute_design(
    name: str,
    version: Optional[int] = Query(None, ge=1),
):
    """Load a design from disk + execute it (register as a model).
    v0.2.7: optional version (default = latest)."""
    _validate_name(name)
    try:
        code, metadata = store.load(name, version=version)
    except FileNotFoundError:
        raise HTTPException(404, f"Design not found: {name}")
    except ValueError as e:
        raise HTTPException(400, str(e))

    result = engine.execute_code(code, name)
    if result["success"] and result["geometry"]:
        state = engine.get(name)
        if state and state.shape:
            try:
                png = render_3d(state.shape, view="iso")
                result["preview_base64"] = base64.b64encode(png).decode("ascii")
                preview_path = RENDERS / f"{name}_preview.png"
                preview_path.write_bytes(png)
                result["preview_path"] = str(preview_path)
            except OSError as e:
                result["render_error"] = (
                    f"preview write failed: {e}. "
                    f"Check that {RENDERS} is writable by uid 1000."
                )
            except Exception as e:
                result["render_error"] = str(e)
    result["loaded_from"] = "design_store"
    result["design_metadata"] = metadata.to_dict()
    return result


# ── v0.2: MCP transport mount ───────────────────

app.mount("/mcp", _mcp_asgi_app)

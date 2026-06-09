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
"""

from __future__ import annotations

import base64
import os
import re
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from . import __version__
from .cad_engine import CADEngine
from .printability import analyze as analyze_printability
from .renderer import render_2d, render_3d, render_multiview


WORKSPACE = Path(os.environ.get("PARTSMITH_WORKSPACE", "/workspace"))
RENDERS = Path(os.environ.get("PARTSMITH_RENDERS", "/renders"))
WORKSPACE.mkdir(parents=True, exist_ok=True)
RENDERS.mkdir(parents=True, exist_ok=True)

# v0.1: reject request bodies above this size before they ever touch
# the engine. 1 MiB is plenty for build123d code; legitimate models
# rarely exceed a few KB. Tune via PARTSMITH_MAX_BODY_BYTES.
MAX_REQUEST_BYTES = int(os.environ.get("PARTSMITH_MAX_BODY_BYTES", str(1 * 1024 * 1024)))

# v0.1: model name pattern — alphanumeric, dash, underscore only, 1-64 chars.
# Prevents path traversal in engine.export() and keeps filenames sane.
NAME_PATTERN = r"^[a-zA-Z0-9_-]{1,64}$"
_NAME_RE = re.compile(NAME_PATTERN)


def _validate_name(name: str) -> str:
    """Belt-and-braces name validation for path params not covered by Pydantic."""
    if not _NAME_RE.match(name):
        raise HTTPException(400, f"Invalid name: must match {NAME_PATTERN}")
    return name


def _safe_write(path: Path, data: bytes, context: str) -> None:
    """Write bytes; surface OSError as a meaningful 500 instead of bare 'Internal Server Error'.

    The most common cause in practice is bind-mount perm misalignment:
    the host-side workspace/ or renders/ dir is owned by root but the
    container runs as uid 1000. See README "First-time deploy".
    """
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


app = FastAPI(title="partsmith", version=__version__)
app.add_middleware(BodySizeLimitMiddleware)
engine = CADEngine(workspace=WORKSPACE)


# ── Request schemas ──────────────────────────────────

class CreateModelRequest(BaseModel):
    code: str = Field(..., max_length=MAX_REQUEST_BYTES)
    name: str = Field("default", pattern=NAME_PATTERN, max_length=64)


class RenderRequest(BaseModel):
    name: Optional[str] = Field(None, pattern=NAME_PATTERN, max_length=64)
    view: str = Field("iso", pattern=r"^[a-z_]{1,16}$")
    with_dimensions: bool = True
    with_hidden: bool = True  # accepted for API compat; not used in v0


class ExportRequest(BaseModel):
    name: Optional[str] = Field(None, pattern=NAME_PATTERN, max_length=64)
    format: str = Field("stl", pattern=r"^(stl|step|3mf)$")


class PrintabilityRequest(BaseModel):
    name: Optional[str] = Field(None, pattern=NAME_PATTERN, max_length=64)
    min_wall_thickness: float = Field(0.8, ge=0.0, le=100.0)


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
                # Most likely: bind-mount perm mismatch on /renders
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


# ── Rendering ─────────────────────────────────────────────

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


# ── Export ────────────────────────────────────────────────────

@app.post("/export")
def export_model(req: ExportRequest):
    try:
        path = engine.export(req.name, req.format)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e))
    except OSError as e:
        # build123d's exporter (or our final relative_to check) hit a
        # filesystem permission/space issue. Bind-mount perm misalignment
        # is the most common cause.
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

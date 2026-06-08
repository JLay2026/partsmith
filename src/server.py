# SPDX-FileCopyrightText: 2026 JLay2026
# SPDX-License-Identifier: MIT
"""
FastAPI server.

REST endpoint surface intentionally matches the shape expected by
existing build123d-MCP clients (notably the cad-agent-shim pattern),
so wiring is drop-in compatible.

This server does NO authentication. See SECURITY.md.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import __version__
from .cad_engine import CADEngine
from .printability import analyze as analyze_printability
from .renderer import render_2d, render_3d, render_multiview


WORKSPACE = Path(os.environ.get("PARTSMITH_WORKSPACE", "/workspace"))
RENDERS = Path(os.environ.get("PARTSMITH_RENDERS", "/renders"))
WORKSPACE.mkdir(parents=True, exist_ok=True)
RENDERS.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="partsmith", version=__version__)
engine = CADEngine(workspace=WORKSPACE)


# ── Request schemas ──────────────────────────────────

class CreateModelRequest(BaseModel):
    code: str
    name: str = "default"


class RenderRequest(BaseModel):
    name: Optional[str] = None
    view: str = "iso"
    with_dimensions: bool = True
    with_hidden: bool = True  # accepted for API compat; not used in v0


class ExportRequest(BaseModel):
    name: Optional[str] = None
    format: str = "stl"


class PrintabilityRequest(BaseModel):
    name: Optional[str] = None
    min_wall_thickness: float = 0.8


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
    return engine.measure(name)


# ── Rendering ────────────────────────────────────────────

@app.post("/render/3d")
def render_3d_endpoint(req: RenderRequest):
    state = engine.get(req.name)
    if not state or not state.shape:
        raise HTTPException(404, f"No model '{req.name or 'active'}' found")
    png = render_3d(state.shape, view=req.view)
    path = RENDERS / f"{state.name}_3d_{req.view}.png"
    path.write_bytes(png)
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
    path.write_bytes(png)
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
    path.write_bytes(png)
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
        p.write_bytes(png)
        out[f"2d_{view}"] = str(p)
    png = render_3d(state.shape, view="iso")
    p = RENDERS / f"{state.name}_3d_iso.png"
    p.write_bytes(png)
    out["3d_iso"] = str(p)
    png = render_multiview(state.shape)
    p = RENDERS / f"{state.name}_multiview.png"
    p.write_bytes(png)
    out["multiview"] = str(p)
    return out


# ── Export ────────────────────────────────────────────────────

@app.post("/export")
def export_model(req: ExportRequest):
    try:
        path = engine.export(req.name, req.format)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e))
    return FileResponse(
        path,
        filename=path.name,
        media_type="application/octet-stream",
    )


# ── Printability ────────────────────────────────────────────

@app.post("/analyze/printability")
def analyze_printability_endpoint(req: PrintabilityRequest):
    state = engine.get(req.name)
    if not state or not state.shape:
        raise HTTPException(404, f"No model '{req.name or 'active'}' found")
    return analyze_printability(state.shape, min_wall_thickness_mm=req.min_wall_thickness)

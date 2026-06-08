# SPDX-FileCopyrightText: 2026 JLay2026
# SPDX-License-Identifier: MIT
"""Trimesh-based printability check: manifold/watertight + sanity bounds."""

from __future__ import annotations

import os
import tempfile
from typing import Any

import numpy as np
import trimesh


def analyze(shape: Any, min_wall_thickness_mm: float = 0.8) -> dict:
    """
    Run a quick printability check on a build123d Shape.

    Returns a dict with watertight/volume/euler/face/volume/area
    fields, plus an `issues` list and `printable` boolean.
    """
    from build123d import export_stl

    issues: list[str] = []

    fd, tmp_path = tempfile.mkstemp(suffix=".stl")
    os.close(fd)
    try:
        export_stl(shape, tmp_path)
        mesh = trimesh.load(tmp_path, force="mesh")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    if isinstance(mesh, trimesh.Scene):
        mesh = trimesh.util.concatenate(mesh.dump())

    bb = mesh.bounds
    dims = (bb[1] - bb[0]).tolist()
    min_dim = float(min(dims))

    if not mesh.is_watertight:
        issues.append(
            "Model is not watertight (has holes). May print with gaps or fail slicing."
        )
    if not mesh.is_volume:
        issues.append("Model does not form a valid closed volume.")
    if min_dim < min_wall_thickness_mm:
        issues.append(
            f"Smallest bounding-box dimension ({min_dim:.2f} mm) is below the "
            f"min wall thickness threshold ({min_wall_thickness_mm} mm)."
        )
    if hasattr(mesh, "face_normals"):
        degenerate = int(np.sum(np.isnan(mesh.face_normals).any(axis=1)))
        if degenerate > 0:
            issues.append(f"{degenerate} degenerate faces detected.")

    return {
        "is_watertight": bool(mesh.is_watertight),
        "is_volume": bool(mesh.is_volume),
        "euler_number": int(mesh.euler_number),
        "face_count": int(len(mesh.faces)),
        "volume_mm3": round(float(mesh.volume), 3),
        "surface_area_mm2": round(float(mesh.area), 3),
        "bounding_box_mm": [round(d, 3) for d in dims],
        "min_dim_mm": round(min_dim, 3),
        "min_wall_thickness_mm": min_wall_thickness_mm,
        "issues": issues,
        "printable": len(issues) == 0,
    }

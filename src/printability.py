# SPDX-FileCopyrightText: 2026 JLay2026
# SPDX-License-Identifier: MIT
"""Trimesh-based printability check: manifold/watertight + sanity bounds.

v0.3.7: build-volume fit check (``bed_fit``), see ``src/bed_fit.py``.
"""

from __future__ import annotations

import os
import tempfile
from typing import Any, Optional, Sequence

import numpy as np
import trimesh

from .bed_fit import check_bed_fit


def analyze(
    shape: Any,
    min_wall_thickness_mm: float = 0.8,
    bed_mm: Optional[Sequence[float]] = None,
) -> dict:
    """
    Run a quick printability check on a build123d Shape.

    Returns a dict with watertight/volume/euler/face/volume/area
    fields, plus an `issues` list and `printable` boolean.

    ``min_wall_thickness_mm`` is compared against the smallest
    bounding-box dimension, not against true local wall thickness --
    it catches a part that is thin overall, not a thin wall on a thick
    part.

    v0.3.7: ``bed_mm`` (x, y, z) overrides the ``PARTSMITH_BED_MM``
    env / X1C default for the build-volume fit check. A part that fits
    in no 90-degree orientation is reported as an issue.
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
    fit = check_bed_fit(dims, bed_mm=bed_mm)
    if not fit["fits_any_orientation"]:
        over = ", ".join(
            f"{axis}+{o:.1f}" for axis, o in zip("XYZ", fit["overage_mm"]) if o > 0
        )
        issues.append(
            f"Part ({dims[0]:.1f} x {dims[1]:.1f} x {dims[2]:.1f} mm) exceeds "
            f"the build volume {fit['bed_mm']} in every 90-degree orientation "
            f"(over by {over} mm as oriented)."
        )
    elif not fit["fits_as_oriented"]:
        # Advisory, not a defect: the slicer can rotate it.
        fit["note"] = (
            "Exceeds the build volume as oriented but fits if rotated to "
            f"{fit['best_orientation']} mm (x, y, z)."
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
        "bed_fit": fit,
        "issues": issues,
        "printable": len(issues) == 0,
    }

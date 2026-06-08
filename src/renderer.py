# SPDX-FileCopyrightText: 2026 JLay2026
# SPDX-License-Identifier: MIT
"""
Headless renderer.

3D and 2D views via matplotlib's Agg backend. No Xvfb, no VTK, no
OSMesa — works in any vanilla container. Renders are utilitarian
(intended for AI agents verifying geometry), not photorealistic.
"""

from __future__ import annotations

import io
import os
import tempfile
from typing import Any

import matplotlib

matplotlib.use("Agg")  # noqa: E402 — must precede pyplot import

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import trimesh  # noqa: E402
from matplotlib.collections import PolyCollection  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: E402


# View name -> (elev, azim) for mpl_toolkits.mplot3d.view_init
VIEW_ANGLES_3D = {
    "front":    (0, -90),
    "back":     (0,  90),
    "left":     (0, 180),
    "right":    (0,   0),
    "top":      (90, -90),
    "bottom":   (-90, -90),
    "iso":      (30, -60),
    "iso_back": (30, 120),
}

# 2D orthographic projections: which two axes to keep, optional mirror
VIEW_PROJECTIONS_2D = {
    "front":  ((0, 2), (+1, +1), "X (mm)", "Z (mm)"),
    "back":   ((0, 2), (-1, +1), "X (mm)", "Z (mm)"),
    "right":  ((1, 2), (+1, +1), "Y (mm)", "Z (mm)"),
    "left":   ((1, 2), (-1, +1), "Y (mm)", "Z (mm)"),
    "top":    ((0, 1), (+1, +1), "X (mm)", "Y (mm)"),
    "bottom": ((0, 1), (+1, -1), "X (mm)", "Y (mm)"),
}


def _shape_to_trimesh(shape: Any) -> trimesh.Trimesh:
    """Build123d Shape -> trimesh.Trimesh via STL round-trip on a temp file."""
    from build123d import export_stl

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
    return mesh


def _fig_to_png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=100)
    plt.close(fig)
    return buf.getvalue()


def render_3d(shape: Any, view: str = "iso", size: tuple[int, int] = (800, 600)) -> bytes:
    """Render a 3D view of a build123d Shape. Returns PNG bytes."""
    mesh = _shape_to_trimesh(shape)
    elev, azim = VIEW_ANGLES_3D.get(view, VIEW_ANGLES_3D["iso"])

    fig = plt.figure(figsize=(size[0] / 100, size[1] / 100), dpi=100)
    ax = fig.add_subplot(111, projection="3d")

    tris = mesh.vertices[mesh.faces]
    poly = Poly3DCollection(
        tris,
        alpha=0.85,
        facecolor="#9bb0c9",
        edgecolor="#3a4a5e",
        linewidth=0.2,
    )
    ax.add_collection3d(poly)

    bbox = mesh.bounds
    ax.set_xlim(bbox[0, 0], bbox[1, 0])
    ax.set_ylim(bbox[0, 1], bbox[1, 1])
    ax.set_zlim(bbox[0, 2], bbox[1, 2])
    try:
        ax.set_box_aspect((bbox[1] - bbox[0]))
    except Exception:
        pass

    ax.view_init(elev=elev, azim=azim)
    ax.set_xlabel("X (mm)")
    ax.set_ylabel("Y (mm)")
    ax.set_zlabel("Z (mm)")
    ax.set_title(f"{view.upper()} view")

    return _fig_to_png(fig)


def render_2d(
    shape: Any,
    view: str = "front",
    size: tuple[int, int] = (800, 600),
    with_dimensions: bool = True,
) -> bytes:
    """Render a 2D orthographic view. Returns PNG bytes."""
    mesh = _shape_to_trimesh(shape)
    axes, mirror, xlabel, ylabel = VIEW_PROJECTIONS_2D.get(
        view, VIEW_PROJECTIONS_2D["front"]
    )

    verts2d = mesh.vertices[:, list(axes)] * np.array(mirror)

    fig, ax = plt.subplots(figsize=(size[0] / 100, size[1] / 100), dpi=100)

    tris = verts2d[mesh.faces]
    pc = PolyCollection(
        tris,
        alpha=0.35,
        facecolor="#9bb0c9",
        edgecolor="#3a4a5e",
        linewidth=0.3,
    )
    ax.add_collection(pc)

    ax.set_aspect("equal", adjustable="datalim")
    ax.autoscale_view()
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(f"{view.upper()} view")
    ax.grid(True, alpha=0.3, linestyle="--")

    if with_dimensions:
        xmin, xmax = ax.get_xlim()
        ymin, ymax = ax.get_ylim()
        width = xmax - xmin
        height = ymax - ymin
        ax.text(
            0.02, 0.98,
            f"W: {width:.2f} mm\nH: {height:.2f} mm",
            transform=ax.transAxes,
            va="top", ha="left",
            bbox=dict(boxstyle="round", facecolor="white", alpha=0.8),
        )

    return _fig_to_png(fig)


def render_multiview(shape: Any, size: tuple[int, int] = (1200, 900)) -> bytes:
    """Composite: front + right + top + iso. Returns PNG bytes."""
    mesh = _shape_to_trimesh(shape)
    fig = plt.figure(figsize=(size[0] / 100, size[1] / 100), dpi=100)

    def _ortho(ax, axes, title, xl, yl):
        verts2d = mesh.vertices[:, list(axes)]
        tris = verts2d[mesh.faces]
        pc = PolyCollection(
            tris,
            alpha=0.35,
            facecolor="#9bb0c9",
            edgecolor="#3a4a5e",
            linewidth=0.3,
        )
        ax.add_collection(pc)
        ax.set_aspect("equal", adjustable="datalim")
        ax.autoscale_view()
        ax.set_xlabel(xl)
        ax.set_ylabel(yl)
        ax.set_title(title)
        ax.grid(True, alpha=0.3, linestyle="--")

    _ortho(fig.add_subplot(2, 2, 1), (0, 2), "Front", "X", "Z")
    _ortho(fig.add_subplot(2, 2, 2), (1, 2), "Right", "Y", "Z")
    _ortho(fig.add_subplot(2, 2, 3), (0, 1), "Top",   "X", "Y")

    ax4 = fig.add_subplot(2, 2, 4, projection="3d")
    tris = mesh.vertices[mesh.faces]
    poly = Poly3DCollection(
        tris,
        alpha=0.85,
        facecolor="#9bb0c9",
        edgecolor="#3a4a5e",
        linewidth=0.2,
    )
    ax4.add_collection3d(poly)
    bbox = mesh.bounds
    ax4.set_xlim(bbox[0, 0], bbox[1, 0])
    ax4.set_ylim(bbox[0, 1], bbox[1, 1])
    ax4.set_zlim(bbox[0, 2], bbox[1, 2])
    try:
        ax4.set_box_aspect((bbox[1] - bbox[0]))
    except Exception:
        pass
    ax4.view_init(elev=30, azim=-60)
    ax4.set_title("Iso")

    fig.tight_layout()
    return _fig_to_png(fig)

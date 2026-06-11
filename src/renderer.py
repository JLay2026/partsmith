# SPDX-FileCopyrightText: 2026 JLay2026
# SPDX-License-Identifier: MIT
"""
Headless renderer.

3D and 2D views via matplotlib's Agg backend. No Xvfb, no VTK, no
OSMesa — works in any vanilla container. 3D renders use per-face
Lambertian shading (computed from mesh.face_normals) so geometry has
real depth cues; not photorealistic, but readable.

v0.2.6 (issue #8): adds render_section() — 2D cross-section through a
shape on the XY/XZ/YZ planes at a given offset. Highest-leverage move
for the iterate-by-AI-chat workflow: see inside designs without leaving
the chat.

v0.3.3 (issue #13): render_section() now fills the cut material so
solid vs. void reads at a glance. Fill is best-effort — any failure
falls back to the v0.2.6 outline-only render rather than erroring.
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
from matplotlib.colors import to_rgb  # noqa: E402
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

# v0.2.6: cross-section plane definitions. For each plane:
#   normal: unit vector perpendicular to the slice
#   axis_idx: index into a 3D point (X=0, Y=1, Z=2) corresponding to the
#             normal axis -- used to position the slice at `at` mm along it
#   plot_axes: (x_idx, y_idx) of the remaining axes to project for the
#              2D plot. Order matters: x_idx is plotted on horizontal,
#              y_idx on vertical.
#   xlabel, ylabel: axis labels for the 2D plot
#   normal_name: human label for the axis perpendicular to the slice
SECTION_PLANES = {
    "XY": ([0.0, 0.0, 1.0], 2, (0, 1), "X (mm)", "Y (mm)", "Z"),
    "XZ": ([0.0, 1.0, 0.0], 1, (0, 2), "X (mm)", "Z (mm)", "Y"),
    "YZ": ([1.0, 0.0, 0.0], 0, (1, 2), "Y (mm)", "Z (mm)", "X"),
}

# Default 3D look: muted blue-grey body, dark edges, subtle ambient
DEFAULT_BASE_COLOR = "#9bb0c9"
DEFAULT_EDGE_COLOR = "#3a4a5e"
# Fill color for cut material in cross-sections (v0.3.3). Warmer than
# the body so a section reads as "this is the cut face" at a glance.
DEFAULT_SECTION_FILL = "#c98f6b"
# Light from upper-right-front; normalized below.
DEFAULT_LIGHT_DIR = np.array([0.5, -0.3, 0.85])
DEFAULT_AMBIENT = 0.30  # 30% floor so back-facing tris aren't black


def _shade_faces(
    mesh: trimesh.Trimesh,
    base_color: str = DEFAULT_BASE_COLOR,
    light_dir: np.ndarray = DEFAULT_LIGHT_DIR,
    ambient: float = DEFAULT_AMBIENT,
) -> np.ndarray:
    """
    Per-face Lambertian shading.

    Returns an (N, 4) RGBA array suitable for Poly3DCollection's
    facecolors argument. NaN normals (degenerate faces) fall back to
    ambient-only color so the renderer doesn't error on bad geometry.
    """
    light = light_dir / np.linalg.norm(light_dir)
    normals = mesh.face_normals

    # Safe dot product — replace NaN normals with zero contribution
    nan_mask = np.isnan(normals).any(axis=1)
    safe_normals = np.where(nan_mask[:, None], 0.0, normals)
    intensity = np.clip(safe_normals @ light, 0.0, 1.0)
    intensity = ambient + (1.0 - ambient) * intensity

    base_rgb = np.array(to_rgb(base_color))
    face_rgb = intensity[:, None] * base_rgb[None, :]
    # Constant alpha; 1.0 looks crisper than the old 0.85
    alpha = np.full((len(face_rgb), 1), 1.0)
    return np.hstack([face_rgb, alpha])


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


def _draw_3d(ax, mesh: trimesh.Trimesh) -> None:
    """Add a shaded Poly3DCollection to a 3D axis."""
    tris = mesh.vertices[mesh.faces]
    face_colors = _shade_faces(mesh)
    poly = Poly3DCollection(
        tris,
        facecolors=face_colors,
        edgecolor=DEFAULT_EDGE_COLOR,
        linewidth=0.15,
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


def render_3d(shape: Any, view: str = "iso", size: tuple[int, int] = (800, 600)) -> bytes:
    """Render a 3D view of a build123d Shape. Returns PNG bytes."""
    mesh = _shape_to_trimesh(shape)
    elev, azim = VIEW_ANGLES_3D.get(view, VIEW_ANGLES_3D["iso"])

    fig = plt.figure(figsize=(size[0] / 100, size[1] / 100), dpi=100)
    ax = fig.add_subplot(111, projection="3d")

    _draw_3d(ax, mesh)
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
        facecolor=DEFAULT_BASE_COLOR,
        edgecolor=DEFAULT_EDGE_COLOR,
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
    """Composite: front + right + top + iso (shaded). Returns PNG bytes."""
    mesh = _shape_to_trimesh(shape)
    fig = plt.figure(figsize=(size[0] / 100, size[1] / 100), dpi=100)

    def _ortho(ax, axes, title, xl, yl):
        verts2d = mesh.vertices[:, list(axes)]
        tris = verts2d[mesh.faces]
        pc = PolyCollection(
            tris,
            alpha=0.35,
            facecolor=DEFAULT_BASE_COLOR,
            edgecolor=DEFAULT_EDGE_COLOR,
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
    _draw_3d(ax4, mesh)
    ax4.view_init(elev=30, azim=-60)
    ax4.set_title("Iso (shaded)")

    fig.tight_layout()
    return _fig_to_png(fig)


def _fill_section(ax, section_path3d, plot_axes) -> bool:
    """Fill the interior of a cross-section (v0.3.3, issue #13).

    Builds a compound matplotlib Path from the section's discrete closed
    loops, projected to 2D via ``plot_axes``, and adds a translucent
    PathPatch so cut material reads as solid. Inner loops (holes, e.g. a
    tube's bore) come back as separate loops; the translucent fill keeps
    them legible even if winding doesn't perfectly cut them, and the
    crisp outline drawn on top always marks the true boundary.

    Best-effort: returns True if a fill patch was added, False if there
    was nothing fillable. Any exception is left to the caller's
    try/except so a fill failure degrades to outline-only.
    """
    from matplotlib.patches import PathPatch
    from matplotlib.path import Path as MplPath

    loops = getattr(section_path3d, "discrete", None)
    if not loops:
        return False

    verts: list = []
    codes: list = []
    for loop in loops:
        pts = np.asarray(loop, dtype=float)
        if pts.ndim != 2 or pts.shape[0] < 3:
            continue
        loop2d = pts[:, list(plot_axes)]
        verts.append(loop2d[0])
        codes.append(MplPath.MOVETO)
        for p in loop2d[1:]:
            verts.append(p)
            codes.append(MplPath.LINETO)
        verts.append(loop2d[0])
        codes.append(MplPath.CLOSEPOLY)

    if not verts:
        return False

    compound = MplPath(np.asarray(verts), codes)
    ax.add_patch(
        PathPatch(
            compound,
            facecolor=DEFAULT_SECTION_FILL,
            edgecolor="none",
            alpha=0.45,
        )
    )
    return True


def render_section(
    shape: Any,
    plane: str = "YZ",
    at: float = 0.0,
    size: tuple[int, int] = (800, 600),
    with_dimensions: bool = True,
) -> bytes:
    """Render a 2D cross-section through a build123d Shape.

    Slices the mesh on the chosen plane at offset ``at`` and renders the
    resulting cut as a 2D PNG. Use to see inside designs without
    exporting STL + opening in a slicer — verify wall thickness,
    internal cavities, snap-fit clearances, screw-hole bottoms, ribs.

    Args:
        shape: build123d Shape / Part / Solid / Compound to section.
        plane: One of "XY" (horizontal slice, normal Z), "XZ" (vertical
            slice, normal Y), or "YZ" (vertical slice, normal X).
            Default "YZ" = right-side cross-section.
        at: Offset along the normal axis (mm). Default 0.0 = through
            origin. Use the geometry's bbox to pick interior values.
        size: Output PNG (width, height) in pixels.
        with_dimensions: Overlay W/H callout in the upper-left.

    Returns:
        PNG bytes.

    Raises:
        ValueError: If ``plane`` is not one of "XY"/"XZ"/"YZ".

    Notes:
        - If the plane doesn't intersect the geometry, returns a
          placeholder PNG with the bbox extent so the caller can pick
          a valid ``at``. Does not raise.
        - v0.3.3: the cut material is filled (translucent) so solid vs.
          void reads at a glance; the section outline is drawn on top.
          Holes (e.g. a tube bore) are marked by their outline and read
          as lighter regions. Fill is best-effort — if it fails the
          render degrades to outline-only (v0.2.6 behavior) rather than
          erroring.
    """
    if plane not in SECTION_PLANES:
        raise ValueError(
            f"plane must be 'XY', 'XZ', or 'YZ', got {plane!r}"
        )

    normal, axis_idx, plot_axes, xlabel, ylabel, normal_name = SECTION_PLANES[plane]
    mesh = _shape_to_trimesh(shape)

    plane_origin = [0.0, 0.0, 0.0]
    plane_origin[axis_idx] = float(at)

    fig, ax = plt.subplots(figsize=(size[0] / 100, size[1] / 100), dpi=100)

    # Compute the cross-section using trimesh's mesh-plane intersection.
    # Returns a Path3D (or None if the plane doesn't cut the mesh).
    section_path3d = mesh.section(
        plane_origin=plane_origin,
        plane_normal=normal,
    )

    if section_path3d is None:
        # No intersection — give a helpful placeholder rather than 500.
        # The caller (LLM) can re-run with a valid `at` from the bbox.
        bbox = mesh.bounds
        axis_min = bbox[0, axis_idx]
        axis_max = bbox[1, axis_idx]
        ax.text(
            0.5, 0.5,
            (
                f"No intersection at {normal_name}={at:.2f} mm.\n"
                f"Geometry spans {normal_name}={axis_min:.2f} to "
                f"{axis_max:.2f} mm.\nPick `at` within that range."
            ),
            transform=ax.transAxes,
            ha="center", va="center",
            fontsize=11,
            bbox=dict(boxstyle="round", facecolor="lightyellow", alpha=0.9),
        )
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_title(
            f"{plane} cross-section at {normal_name}={at:.2f} mm "
            f"(no intersection)"
        )
        return _fig_to_png(fig)

    # v0.3.3: fill the cut material first so the outline draws on top of
    # it. Best-effort — never let a fill failure break the render.
    try:
        _fill_section(ax, section_path3d, plot_axes)
    except Exception:
        pass

    # Project section vertices to 2D using the plot_axes indices.
    # This avoids trimesh.Path3D.to_planar()'s rotation matrix surprises;
    # axes stay aligned with the user's expectation.
    verts3d = section_path3d.vertices
    plotted_any = False
    for entity in section_path3d.entities:
        # entity.points is an index array into vertices
        idx = entity.points
        if len(idx) < 2:
            continue
        x_data = verts3d[idx, plot_axes[0]]
        y_data = verts3d[idx, plot_axes[1]]
        ax.plot(
            x_data, y_data,
            color=DEFAULT_EDGE_COLOR,
            linewidth=0.8,
        )
        plotted_any = True

    if not plotted_any:
        # Should be rare (plane tangent to a single face); handle anyway
        ax.text(
            0.5, 0.5,
            f"Section at {normal_name}={at:.2f} produced no edges.\n"
            f"Try a slightly different `at`.",
            transform=ax.transAxes,
            ha="center", va="center",
            fontsize=11,
            bbox=dict(boxstyle="round", facecolor="lightyellow", alpha=0.9),
        )
        ax.set_xticks([])
        ax.set_yticks([])
    else:
        ax.set_aspect("equal", adjustable="datalim")
        ax.autoscale_view()

    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(f"{plane} cross-section at {normal_name}={at:.2f} mm")
    ax.grid(True, alpha=0.3, linestyle="--")

    if with_dimensions and plotted_any:
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

# SPDX-FileCopyrightText: 2026 JLay2026
# SPDX-License-Identifier: MIT
"""
partsmith_helpers -- reusable build123d patterns for common 3D-printing
tasks.

These helpers are auto-injected into the build123d execution namespace
by ``CADEngine.execute_code``, so any tool call can use them without an
explicit import. They are intentionally thin wrappers around build123d
primitives -- they compose with raw build123d, they don't replace it.

Convention for hole-shaped helpers (``through_hole``, ``screw_hole``,
``hex_hole``, ``slot``, ``screw_pattern``): the returned Part is
positioned with its TOP face at Z=0, extending in -Z. To use, position
it at the top face of your body and subtract::

    body = Box(100, 50, 10)
    hole = through_hole(3.2, 10).moved(Location((25, 15, 10)))  # top of body
    result = body - hole

Edge-treatment helpers (``chamfer_edges``, ``fillet_top_edges``) return
the modified Part directly.

Pattern criterion (from issue #1): a helper earns its place if it has
appeared in >=2 designs OR is unambiguously universal (M-series
hardware, common edge treatments).
"""

from __future__ import annotations

import math
from typing import Any, Callable, Optional, Union

from build123d import (
    Align,
    Axis,
    Box,
    Cone,
    Cylinder,
    Location,
    Part,
    RegularPolygon,
    chamfer,
    extrude,
    fillet,
)

# -- Hole helpers --------------------------------------------------


def through_hole(diameter: float, depth: float) -> Part:
    """Simple cylindrical through-hole.

    Positioned with top face at Z=0, extending in -Z. Pair with body
    subtraction::

        body = Box(50, 30, 10)
        hole = through_hole(3.2, 10).moved(Location((25, 15, 10)))
        result = body - hole

    Args:
        diameter: Hole diameter in mm.
        depth: Hole depth in mm.

    Returns:
        Part suitable for subtraction.
    """
    return Cylinder(
        radius=diameter / 2,
        height=depth,
        align=(Align.CENTER, Align.CENTER, Align.MAX),
    )


def screw_hole(
    diameter: float,
    depth: float,
    countersink: bool = True,
    head_diameter: Optional[float] = None,
    countersink_angle: float = 90.0,
) -> Part:
    """Machine-screw hole with optional 90-degree countersink.

    Defaults match common M-series machine screws (head ~ 1.8x shaft
    diameter). Top of countersink at Z=0; shaft extends in -Z.

    Args:
        diameter: Shaft diameter in mm (e.g. 3.2 for M3 clearance).
        depth: Total hole depth in mm (includes countersink).
        countersink: If True, add a conical countersink at the top.
            If False, equivalent to ``through_hole(diameter, depth)``.
        head_diameter: Diameter of the countersink top. Defaults to
            ``1.8 * diameter`` if not provided.
        countersink_angle: Included angle of countersink in degrees.
            90 is standard for machine screws.

    Returns:
        Part suitable for subtraction.
    """
    if not countersink:
        return through_hole(diameter, depth)

    if head_diameter is None:
        head_diameter = diameter * 1.8

    half_angle_rad = math.radians(countersink_angle / 2.0)
    if half_angle_rad <= 0:
        raise ValueError("countersink_angle must be positive")
    cs_depth = (head_diameter - diameter) / (2.0 * math.tan(half_angle_rad))
    cs_depth = min(cs_depth, depth)

    countersink_part = Cone(
        bottom_radius=diameter / 2,
        top_radius=head_diameter / 2,
        height=cs_depth,
        align=(Align.CENTER, Align.CENTER, Align.MAX),
    )

    if cs_depth >= depth:
        return countersink_part

    shaft = Cylinder(
        radius=diameter / 2,
        height=depth - cs_depth,
        align=(Align.CENTER, Align.CENTER, Align.MAX),
    ).moved(Location((0, 0, -cs_depth)))

    return countersink_part + shaft


def hex_hole(across_flats: float, depth: float) -> Part:
    """Hex nut pocket sized by across-flats dimension.

    Sized to receive M-series nuts. Common AF dimensions:
    M3=5.5, M4=7, M5=8, M6=10 mm. Add 0.1-0.2mm clearance for
    FDM print tolerance. Top at Z=0, extending in -Z.

    Args:
        across_flats: Nut size in mm, flat-to-flat (NOT corner-to-corner).
        depth: Pocket depth in mm.

    Returns:
        Part suitable for subtraction.
    """
    circumradius = across_flats / math.sqrt(3)
    hex_sketch = RegularPolygon(radius=circumradius, side_count=6)
    return extrude(hex_sketch, amount=-depth)


# -- Slot helper ----------------------------------------------


def slot(length: float, width: float, depth: float) -> Part:
    """Stadium-shaped slot (rectangle with semicircular ends).

    Aligned along the X-axis: total X extent = length, Y extent = width.
    Top at Z=0, extending in -Z. Useful for adjustable mounts.

    Args:
        length: Total length (overall X extent) in mm. Must be > width.
        width: Width (overall Y extent) in mm.
        depth: Depth in mm.

    Returns:
        Part suitable for subtraction.

    Raises:
        ValueError: If length <= width (degenerate slot).
    """
    if length <= width:
        raise ValueError(
            f"slot: length ({length}) must be greater than width ({width}). "
            f"For a circular hole use through_hole(diameter={width}, "
            f"depth={depth})."
        )

    inner = length - width
    body = Box(
        inner, width, depth,
        align=(Align.CENTER, Align.CENTER, Align.MAX),
    )
    end1 = Cylinder(
        radius=width / 2, height=depth,
        align=(Align.CENTER, Align.CENTER, Align.MAX),
    ).moved(Location((inner / 2, 0, 0)))
    end2 = Cylinder(
        radius=width / 2, height=depth,
        align=(Align.CENTER, Align.CENTER, Align.MAX),
    ).moved(Location((-inner / 2, 0, 0)))
    return body + end1 + end2


# -- Edge treatment helpers ----------------------------------


def chamfer_edges(
    part: Part,
    radius: float,
    edges: Union[str, Any] = "all",
) -> Part:
    """Apply a chamfer to selected edges of a part.

    Args:
        part: build123d Part to chamfer.
        radius: Chamfer size in mm.
        edges: Selection. ``"all"`` chamfers every edge. ``"top"`` /
            ``"bottom"`` select edges on the top / bottom face (highest
            / lowest Z bbox extent). ``"side"`` selects vertical edges
            (parallel to Z axis). Or pass an explicit edge collection
            from ``part.edges()`` for full control.

    Returns:
        Part with chamfered edges.

    Raises:
        ValueError: If ``edges`` is an unknown string preset.
    """
    if isinstance(edges, str):
        if edges == "all":
            edge_list = part.edges()
        elif edges == "top":
            edge_list = part.edges().group_by(Axis.Z)[-1]
        elif edges == "bottom":
            edge_list = part.edges().group_by(Axis.Z)[0]
        elif edges == "side":
            edge_list = part.edges().filter_by(Axis.Z)
        else:
            raise ValueError(
                f"chamfer_edges: unknown preset {edges!r}. "
                f"Use 'all', 'top', 'bottom', 'side', or pass an explicit "
                f"edge collection from part.edges()."
            )
    else:
        edge_list = edges

    return chamfer(edge_list, length=radius)


def fillet_top_edges(part: Part, radius: float) -> Part:
    """Fillet (round) all edges on the top face of a part.

    Common cosmetic finish for the visible face of a printed part.
    Top face = highest-Z group of edges per ``group_by(Axis.Z)[-1]``.

    Args:
        part: build123d Part to fillet.
        radius: Fillet radius in mm.

    Returns:
        Part with top edges filleted.
    """
    top_edges = part.edges().group_by(Axis.Z)[-1]
    return fillet(top_edges, radius=radius)


# -- Pattern helper -----------------------------------------


def screw_pattern(
    positions: list[tuple[float, float]],
    hole_func: Callable[[], Part],
) -> Part:
    """Apply a hole pattern at given (x, y) positions on the XY plane.

    Returns a unioned Part suitable for subtraction::

        positions = [(10, 10), (90, 10), (10, 40), (90, 40)]
        holes = screw_pattern(positions, lambda: through_hole(3.2, 10))
        result = body - holes

    Args:
        positions: List of (x, y) tuples in mm.
        hole_func: Callable returning a Part (the hole shape). Called
            once per position; result is positioned with
            ``Location((x, y, 0))``.

    Returns:
        Unioned Part of all positioned holes.

    Raises:
        ValueError: If ``positions`` is empty.
    """
    if not positions:
        raise ValueError("screw_pattern: positions list is empty")

    result: Optional[Part] = None
    for x, y in positions:
        h = hole_func().moved(Location((x, y, 0)))
        result = h if result is None else result + h
    return result  # type: ignore[return-value]


# Auto-injection into CADEngine's build123d execution namespace.
# Add new helpers here when shipping them.
HELPERS: dict[str, Callable[..., Any]] = {
    "through_hole": through_hole,
    "screw_hole": screw_hole,
    "hex_hole": hex_hole,
    "slot": slot,
    "chamfer_edges": chamfer_edges,
    "fillet_top_edges": fillet_top_edges,
    "screw_pattern": screw_pattern,
}


__all__ = [
    "HELPERS",
    "chamfer_edges",
    "fillet_top_edges",
    "hex_hole",
    "screw_hole",
    "screw_pattern",
    "slot",
    "through_hole",
]

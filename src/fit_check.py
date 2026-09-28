# SPDX-FileCopyrightText: 2026 JLay2026
# SPDX-License-Identifier: MIT
"""Assembly fit check between two models (v0.4.0, issue #25).

Answers "do these two parts collide, and if not, how much room is
there?" before both are printed. Built on the B-rep kernel already in
the image (build123d / OCP) -- no new dependency.

Frame convention: parts are compared in the coordinates they were
modeled in. Mating parts designed in a shared assembly frame (the sw2
tray + wing) need nothing else; a part modeled at the origin can be
placed with ``offset_b`` (translation only, by design -- see #25).
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

# Below these, a result is numerical noise from the boolean / distance
# solvers, not real geometry.
_VOLUME_EPS_MM3 = 1e-6
_DISTANCE_EPS_MM = 1e-6


def _bbox_dict(shape: Any) -> dict:
    bb = shape.bounding_box()
    return {
        "min": [round(bb.min.X, 3), round(bb.min.Y, 3), round(bb.min.Z, 3)],
        "max": [round(bb.max.X, 3), round(bb.max.Y, 3), round(bb.max.Z, 3)],
        "size": [round(bb.size.X, 3), round(bb.size.Y, 3), round(bb.size.Z, 3)],
    }


def check_fit(
    shape_a: Any,
    shape_b: Any,
    min_clearance_mm: float = 0.2,
    offset_b: Optional[Sequence[float]] = None,
) -> dict:
    """Interference and clearance between two build123d shapes.

    Returns:
        interferes: True if the solids overlap by more than numerical noise.
        interference_volume_mm3: overlap volume (0 when they don't overlap).
        interference_bbox: where the overlap is (min/max/size), or None.
        min_distance_mm: smallest gap between the parts (0 if touching
            or overlapping).
        closest_points: {"a": [x, y, z], "b": [x, y, z]} realizing it.
        contact: True if the parts touch without overlapping.
        min_clearance_mm / offset_b: echoed inputs.
        ok: no interference and min_distance_mm >= min_clearance_mm.
        issues: plain-language problems, empty when ok.
    """
    from build123d import Location

    if min_clearance_mm < 0:
        raise ValueError("min_clearance_mm must be >= 0")
    offset = None
    if offset_b is not None:
        if len(offset_b) != 3:
            raise ValueError("offset_b must be [x, y, z] in mm")
        offset = [float(v) for v in offset_b]
        shape_b = shape_b.moved(Location(tuple(offset)))

    dist, pa, pb = shape_a.distance_to_with_closest_points(shape_b)
    dist = float(dist)

    volume = 0.0
    overlap_bbox = None
    if dist <= _DISTANCE_EPS_MM:
        # Touching or overlapping: only a boolean tells them apart.
        common = shape_a & shape_b
        volume = float(getattr(common, "volume", 0.0) or 0.0)
        if volume > _VOLUME_EPS_MM3:
            overlap_bbox = _bbox_dict(common)

    interferes = volume > _VOLUME_EPS_MM3
    contact = dist <= _DISTANCE_EPS_MM and not interferes
    ok = (not interferes) and dist + _DISTANCE_EPS_MM >= min_clearance_mm

    issues: list[str] = []
    if interferes:
        size = overlap_bbox["size"]
        issues.append(
            f"Parts overlap by {volume:.3f} mm^3 in a region "
            f"{size[0]:.2f} x {size[1]:.2f} x {size[2]:.2f} mm "
            f"at {overlap_bbox['min']}..{overlap_bbox['max']}."
        )
    elif dist + _DISTANCE_EPS_MM < min_clearance_mm:
        what = "touch" if contact else f"are only {dist:.3f} mm apart"
        issues.append(
            f"Parts {what}; required clearance is {min_clearance_mm} mm. "
            f"Closest points: a={_pt(pa)}, b={_pt(pb)}."
        )

    return {
        "interferes": interferes,
        "interference_volume_mm3": round(volume, 3),
        "interference_bbox": overlap_bbox,
        "min_distance_mm": round(dist, 4),
        "closest_points": {"a": _pt(pa), "b": _pt(pb)},
        "contact": contact,
        "min_clearance_mm": min_clearance_mm,
        "offset_b": offset,
        "ok": ok,
        "issues": issues,
    }


def _pt(v: Any) -> list[float]:
    return [round(v.X, 3), round(v.Y, 3), round(v.Z, 3)]

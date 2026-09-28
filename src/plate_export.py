# SPDX-FileCopyrightText: 2026 JLay2026
# SPDX-License-Identifier: MIT
"""Standard multi-part 3MF export: one print plate, several parts (v0.4.0, #26).

Scope (decided on #26): a plain, spec-compliant 3MF -- one named object
per model. No slicer-vendor project settings, no filament/colour hints;
slicers (Bambu Studio, OrcaSlicer, PrusaSlicer) import it as separate
objects and filament assignment happens there.

Layout:
- ``arrange`` (default): parts are laid out side by side for printing --
  each dropped to the bed, placed left to right in the given order with
  ``gap_mm`` between them, wrapping to a new row when a row is full;
  the whole layout is centered on the bed. Nothing is rotated.
  Mating parts are usually modeled in their *assembly* positions (a
  retainer sitting on its peg), which is exactly where they can't be
  printed; ``partsmith_check_fit`` is the tool that cares about
  assembled alignment, not the plate.
- ``as_modeled``: keep modeled positions as one rigid group centered on
  the bed, for parts already arranged for printing. Rejected if any two
  parts overlap.

One call = one plate. Parts that don't fit one bed go in separate calls.
"""

from __future__ import annotations

import os
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Optional, Sequence

from .bed_fit import bed_from_env, check_bed_fit

_MODEL_PATH = "3D/3dmodel.model"
LAYOUTS = ("arrange", "as_modeled")


def write_3mf(parts: Sequence[tuple[str, Any, Sequence[float]]], path: Path) -> None:
    """Write ``parts`` ([(name, shape, offset_xyz), ...]) as named objects."""
    from build123d import Location, Mesher

    mesher = Mesher()
    for name, shape, offset in parts:
        loc = Location(tuple(float(v) for v in offset))
        mesher.add_shape(shape.moved(loc), part_number=name)
    mesher.write(str(path))
    _name_objects(path)


def _name_objects(path: Path) -> None:
    """Add the core-spec ``name`` attribute next to build123d's ``partnumber``.

    Slicers label objects by ``name``; build123d only writes
    ``partnumber``. Names are NAME_PATTERN-validated upstream
    ([A-Za-z0-9_-]), so no XML escaping is needed.
    """
    with zipfile.ZipFile(path) as zin:
        entries = [(info, zin.read(info.filename)) for info in zin.infolist()]
    fd, tmp = tempfile.mkstemp(suffix=".3mf", dir=str(path.parent))
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
            for info, data in entries:
                if info.filename == _MODEL_PATH:
                    data = re.sub(
                        rb'partnumber="([A-Za-z0-9_-]+)"',
                        rb'name="\1" partnumber="\1"',
                        data,
                    )
                zout.writestr(info, data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _bounds(shape: Any) -> tuple[list[float], list[float]]:
    bb = shape.bounding_box()
    return [bb.min.X, bb.min.Y, bb.min.Z], [bb.max.X, bb.max.Y, bb.max.Z]


def plan_plate(
    parts: Sequence[tuple[str, Any]],
    bed_mm: Optional[Sequence[float]] = None,
    layout: str = "arrange",
    gap_mm: float = 5.0,
) -> dict:
    """Compute where each part goes on the bed.

    Returns layout, bed_mm, layout_size_mm, and placements
    [{name, offset_mm, bbox_min_mm, bbox_max_mm}] in bed coordinates
    (bed spans 0..X, 0..Y). Raises ValueError when the parts can't be
    placed on this bed.
    """
    if layout not in LAYOUTS:
        raise ValueError(f"layout must be one of {LAYOUTS}, got {layout!r}")
    if gap_mm < 0:
        raise ValueError("gap_mm must be >= 0")
    bed = tuple(float(b) for b in (bed_mm if bed_mm is not None else bed_from_env()))
    bounds = [(name, *_bounds(shape)) for name, shape in parts]

    for name, lo, hi in bounds:
        size = [hi[i] - lo[i] for i in range(3)]
        fit = check_bed_fit(size, bed_mm=bed)
        if not fit["fits_as_oriented"]:
            hint = (
                " It would fit rotated; rotate it in the model (the plate "
                "export never rotates parts)."
                if fit["fits_any_orientation"]
                else ""
            )
            raise ValueError(
                f"Part '{name}' ({size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm) "
                f"does not fit the {list(bed)} mm bed on its own.{hint}"
            )

    if layout == "as_modeled":
        offsets = _plan_as_modeled(parts, bounds, bed)
    else:
        offsets = _plan_arrange(bounds, bed, gap_mm)

    placements = []
    all_lo, all_hi = [float("inf")] * 3, [float("-inf")] * 3
    for (name, lo, hi), off in zip(bounds, offsets):
        plo = [lo[i] + off[i] for i in range(3)]
        phi = [hi[i] + off[i] for i in range(3)]
        for i in range(3):
            all_lo[i] = min(all_lo[i], plo[i])
            all_hi[i] = max(all_hi[i], phi[i])
        placements.append({
            "name": name,
            "offset_mm": [round(v, 3) for v in off],
            "bbox_min_mm": [round(v, 3) for v in plo],
            "bbox_max_mm": [round(v, 3) for v in phi],
        })
    return {
        "layout": layout,
        "bed_mm": [round(b, 3) for b in bed],
        "layout_size_mm": [round(all_hi[i] - all_lo[i], 3) for i in range(3)],
        "placements": placements,
    }


def _plan_arrange(bounds, bed, gap) -> list[list[float]]:
    """Shelf packing in the given order; the finished layout is centered."""
    raw = []  # (x0, y0) target for each part's bbox min corner, pre-centering
    x = y = row_depth = 0.0
    max_width = 0.0
    for name, lo, hi in bounds:
        w, d = hi[0] - lo[0], hi[1] - lo[1]
        if x > 0 and x + w > bed[0]:
            x = 0.0
            y += row_depth + gap
            row_depth = 0.0
        raw.append((x, y))
        x += w + gap
        max_width = max(max_width, x - gap)
        row_depth = max(row_depth, d)
    total = (max_width, y + row_depth)
    if total[1] > bed[1]:
        raise ValueError(
            f"Arranged layout needs {total[0]:.1f} x {total[1]:.1f} mm, more than "
            f"the {bed[0]:.0f} x {bed[1]:.0f} mm bed. Split the parts across "
            "more than one plate export."
        )
    shift = ((bed[0] - total[0]) / 2, (bed[1] - total[1]) / 2)
    return [
        [x0 + shift[0] - lo[0], y0 + shift[1] - lo[1], -lo[2]]
        for (x0, y0), (_, lo, _hi) in zip(raw, bounds)
    ]


def _plan_as_modeled(parts, bounds, bed) -> list[list[float]]:
    """One rigid group, centered on the bed, dropped to Z=0; no overlaps."""
    from .fit_check import check_fit

    for i in range(len(parts)):
        for j in range(i + 1, len(parts)):
            (na, la, ha), (nb, lb, hb) = bounds[i], bounds[j]
            boxes_touch = all(la[k] <= hb[k] and lb[k] <= ha[k] for k in range(3))
            if boxes_touch and check_fit(parts[i][1], parts[j][1], 0.0)["interferes"]:
                raise ValueError(
                    f"Parts '{na}' and '{nb}' overlap as modeled (they are "
                    "probably in assembly positions). Use layout='arrange'."
                )
    lo = [min(b[1][k] for b in bounds) for k in range(3)]
    hi = [max(b[2][k] for b in bounds) for k in range(3)]
    size = [hi[k] - lo[k] for k in range(3)]
    fit = check_bed_fit(size, bed_mm=bed)
    if not fit["fits_as_oriented"]:
        raise ValueError(
            f"Group ({size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm) doesn't fit "
            f"the {list(bed)} mm bed as modeled. Use layout='arrange' or split "
            "the parts across plates."
        )
    off = [bed[0] / 2 - (lo[0] + hi[0]) / 2, bed[1] / 2 - (lo[1] + hi[1]) / 2, -lo[2]]
    return [list(off) for _ in bounds]


def plate_filename(names: Sequence[str]) -> str:
    """Workspace filename for a plate; stem stays within NAME_PATTERN (<=64)."""
    stem = f"plate_{names[0]}_{len(names)}"
    return f"{stem[:64]}.3mf"

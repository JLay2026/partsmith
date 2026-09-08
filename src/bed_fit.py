# SPDX-FileCopyrightText: 2026 JLay2026
# SPDX-License-Identifier: MIT
"""Build-volume fit check (v0.3.7, ROADMAP Theme 3).

Pure stdlib so it can be unit-tested in the lightweight CI job without
build123d / trimesh. Consumed by ``printability.analyze``.

Motivation: vise_hanger_v4 (2026-07-05) was authored at 260 mm wide,
exported, and only rejected by the slicer for a 256 mm X1C bed --
costing a v4.1 iteration whose only change was "fit the bed".
"""

from __future__ import annotations

import itertools
import os
from typing import Sequence

# Bambu Lab X1C build volume (X, Y, Z) in mm.
DEFAULT_BED_MM = (256.0, 256.0, 256.0)


def bed_from_env(default: Sequence[float] = DEFAULT_BED_MM) -> tuple[float, float, float]:
    """Read ``PARTSMITH_BED_MM`` ("x,y,z") or fall back to ``default``.

    Malformed values fall back silently; the check must never take the
    analyzer down.
    """
    raw = os.environ.get("PARTSMITH_BED_MM", "").strip()
    if raw:
        try:
            parts = [float(p) for p in raw.split(",")]
            if len(parts) == 3 and all(p > 0 for p in parts):
                return (parts[0], parts[1], parts[2])
        except ValueError:
            pass
    return (float(default[0]), float(default[1]), float(default[2]))


def check_bed_fit(
    dims_mm: Sequence[float],
    bed_mm: Sequence[float] | None = None,
    tolerance_mm: float = 0.0,
) -> dict:
    """Does a part with bounding box ``dims_mm`` (x, y, z) fit ``bed_mm``?

    Returns:
        bed_mm: the volume checked against.
        fits_as_oriented: every axis of the part <= the same bed axis.
        fits_any_orientation: some axis permutation of the part fits.
            Rotations are 90-degree axis swaps only -- a part that only
            fits diagonally is reported as not fitting.
        best_orientation: the (x, y, z) dims of a fitting permutation
            (the as-oriented dims when those fit), or None.
        overage_mm: per-axis mm over the bed as oriented (0 when within).
    """
    bed = tuple(float(b) for b in (bed_mm if bed_mm is not None else bed_from_env()))
    dims = tuple(float(d) for d in dims_mm)
    if len(dims) != 3 or len(bed) != 3:
        raise ValueError("dims_mm and bed_mm must each have exactly 3 entries")

    def _fits(candidate: Sequence[float]) -> bool:
        return all(c <= b + tolerance_mm for c, b in zip(candidate, bed))

    as_oriented = _fits(dims)
    best = None
    if as_oriented:
        best = dims
    else:
        for perm in itertools.permutations(dims):
            if _fits(perm):
                best = perm
                break

    return {
        "bed_mm": [round(b, 3) for b in bed],
        "fits_as_oriented": as_oriented,
        "fits_any_orientation": best is not None,
        "best_orientation": [round(d, 3) for d in best] if best else None,
        "overage_mm": [round(max(0.0, d - b), 3) for d, b in zip(dims, bed)],
    }

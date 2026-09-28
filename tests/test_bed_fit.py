# SPDX-FileCopyrightText: 2026 JLay2026
# SPDX-License-Identifier: MIT
"""Unit tests for the v0.3.7 build-volume fit check.

``src.bed_fit`` is pure stdlib, so this runs in the lightweight CI job.
The two anchor cases are the real vise_hanger_v4 (260 mm, rejected by
the X1C) and vise_hanger_v4_1 (250 mm, the fix).
"""

import pytest


def test_x1c_default_bed(monkeypatch):
    from src.bed_fit import DEFAULT_BED_MM, bed_from_env

    monkeypatch.delenv("PARTSMITH_BED_MM", raising=False)
    assert bed_from_env() == DEFAULT_BED_MM == (256.0, 256.0, 256.0)


def test_bed_from_env_parses_and_falls_back(monkeypatch):
    from src.bed_fit import bed_from_env

    monkeypatch.setenv("PARTSMITH_BED_MM", "220,220,250")
    assert bed_from_env() == (220.0, 220.0, 250.0)
    monkeypatch.setenv("PARTSMITH_BED_MM", "garbage")
    assert bed_from_env() == (256.0, 256.0, 256.0)
    monkeypatch.setenv("PARTSMITH_BED_MM", "1,2")
    assert bed_from_env() == (256.0, 256.0, 256.0)


def test_vise_hanger_v4_does_not_fit():
    """260 x 94 x 168 exceeds a 256 mm cube in every orientation."""
    from src.bed_fit import check_bed_fit

    fit = check_bed_fit([260.0, 94.095, 168.0], bed_mm=[256, 256, 256])
    assert fit["fits_as_oriented"] is False
    assert fit["fits_any_orientation"] is False
    assert fit["best_orientation"] is None
    assert fit["overage_mm"] == [4.0, 0.0, 0.0]


def test_vise_hanger_v4_1_fits():
    from src.bed_fit import check_bed_fit

    fit = check_bed_fit([250.0, 94.095, 168.0], bed_mm=[256, 256, 256])
    assert fit["fits_as_oriented"] is True
    assert fit["fits_any_orientation"] is True
    assert fit["best_orientation"] == [250.0, 94.095, 168.0]


def test_fits_only_when_rotated():
    """Tall part on a short bed: fails as oriented, fits laid down."""
    from src.bed_fit import check_bed_fit

    fit = check_bed_fit([50, 50, 300], bed_mm=[256, 256, 256])
    assert fit["fits_as_oriented"] is False
    assert fit["fits_any_orientation"] is False  # 300 > 256 on every axis

    fit = check_bed_fit([50, 50, 240], bed_mm=[256, 256, 200])
    assert fit["fits_as_oriented"] is False
    assert fit["fits_any_orientation"] is True
    assert fit["best_orientation"] in ([240.0, 50.0, 50.0], [50.0, 240.0, 50.0])


def test_tolerance():
    from src.bed_fit import check_bed_fit

    assert check_bed_fit([256.5, 10, 10], bed_mm=[256, 256, 256])["fits_as_oriented"] is False
    assert (
        check_bed_fit([256.5, 10, 10], bed_mm=[256, 256, 256], tolerance_mm=1.0)[
            "fits_as_oriented"
        ]
        is True
    )


def test_rejects_bad_shapes():
    from src.bed_fit import check_bed_fit

    with pytest.raises(ValueError):
        check_bed_fit([1, 2], bed_mm=[256, 256, 256])

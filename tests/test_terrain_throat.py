"""brc_tools.terrain.throat: clearance width and minimum-cut area against analytic channels."""

from __future__ import annotations

import numpy as np
import pytest

from brc_tools.terrain import throat


def basins_and_channel(width_cells=5, depth=100.0, ny=61, nx=121, res=50.0, floor=1000.0, wall=2000.0):
    """Two basins joined by a straight flat-bottomed channel ``width_cells`` wide, 20 cells long."""
    z = np.full((ny, nx), wall)
    z[10:51, 5:50] = floor
    z[10:51, 71:116] = floor
    j0 = 30 - width_cells // 2
    z[j0:j0 + width_cells, 50:71] = floor
    a = np.zeros(z.shape, bool)
    a[10:51, 5:30] = True
    b = np.zeros(z.shape, bool)
    b[10:51, 91:116] = True
    return z, a, b, res, floor + depth


@pytest.mark.parametrize("w", [1, 2, 3, 5, 9])
def test_clearance_width_of_a_straight_channel(w):
    z, a, b, res, stage = basins_and_channel(width_cells=w)
    got = throat.clearance_width(z, res, stage, a, b)
    assert got == pytest.approx(w * res, abs=1.01 * res), (w, got)
    if w % 2 == 1:                                   # odd widths have a centre line: exact
        assert got == pytest.approx(w * res, abs=0.3 * res)


def test_clearance_is_zero_when_the_pool_is_below_the_channel():
    z, a, b, res, _ = basins_and_channel()
    z[:, 50:71] = np.where(z[:, 50:71] < 1500.0, 1200.0, z[:, 50:71])     # raise the channel bed to 1200 m
    assert throat.clearance_width(z, res, 1100.0, a, b) == 0.0
    assert throat.min_cut_area(z, res, 1100.0, a, b) == 0.0


@pytest.mark.parametrize("w,depth", [(5, 100.0), (9, 40.0), (3, 250.0)])
def test_min_cut_area_of_a_rectangular_channel(w, depth):
    z, a, b, res, stage = basins_and_channel(width_cells=w, depth=depth)
    area = throat.min_cut_area(z, res, stage, a, b)
    # the Cauchy-Crofton weights measure an axis-aligned cut ~8 % long and miss half a cell of
    # width at each wall: accept 12 % plus a cell
    expect = w * res * depth
    assert area == pytest.approx(expect, rel=0.12, abs=res * depth)


def test_min_cut_area_of_a_diagonal_channel_within_ten_percent_of_an_axis_one():
    res, depth = 25.0, 80.0
    n = 161
    jj, ii = np.indices((n, n))
    z = np.full((n, n), 3000.0)
    band = np.abs(jj - ii) <= 6                       # a 45-degree channel, 13 cells across the diagonal
    z[band] = 1000.0
    z[:30, :30] = 1000.0
    z[-30:, -30:] = 1000.0
    a = np.zeros((n, n), bool)
    a[:20, :20] = True
    b = np.zeros((n, n), bool)
    b[-20:, -20:] = True
    area = throat.min_cut_area(z, res, 1000.0 + depth, a, b)
    width = 13 * res / np.sqrt(2.0)                  # the band's width measured across it
    assert area == pytest.approx(width * depth, rel=0.15)


def test_min_cut_sums_parallel_channels_and_ignores_dead_ends():
    z, a, b, res, stage = basins_and_channel(width_cells=5)
    one = throat.min_cut_area(z, res, stage, a, b)
    z2 = z.copy()
    z2[45:50, 50:71] = 1000.0                         # a second, identical channel
    two = throat.min_cut_area(z2, res, stage, a, b)
    assert two == pytest.approx(2.0 * one, rel=0.03)
    z3 = z.copy()
    z3[12:20, 55:60] = 1000.0                         # a side pocket off nothing: not connected to the channel
    z3[20:28, 57] = 1000.0                            # ... joined to it by a dead-end arm
    assert throat.min_cut_area(z3, res, stage, a, b) == pytest.approx(one, rel=0.03)


def test_return_cut_separates_the_basins():
    z, a, b, res, stage = basins_and_channel(width_cells=5)
    area, up = throat.min_cut_area(z, res, stage, a, b, return_cut=True)
    assert area > 0
    assert up[a].all() and not up[b].any()
    line = throat.cut_cells(up, throat.flooded(z, stage))
    assert 3 <= line.sum() <= 12                      # about one channel width of cells


def test_area_grows_with_stage_in_a_v_notch():
    ny, nx, res = 61, 121, 50.0
    jj, ii = np.indices((ny, nx))
    z = 1000.0 + 2.0 * np.abs(jj - 30) * res * 0.2    # a V-shaped valley along the middle row
    a = np.zeros(z.shape, bool)
    a[:, :10] = True
    b = np.zeros(z.shape, bool)
    b[:, -10:] = True
    curve = throat.throat_curve(z, res, [1050.0, 1100.0, 1200.0], a, b)
    assert np.all(np.diff(curve["area_m2"]) > 0)
    assert np.all(np.diff(curve["width_m"]) > 0)
    # triangle: half-width = h / 0.4, area = h^2 / 0.4
    assert curve["area_m2"][-1] == pytest.approx(200.0 ** 2 / 0.4, rel=0.15)


def test_overlapping_masks_are_an_error():
    z, a, b, res, stage = basins_and_channel()
    with pytest.raises(ValueError):
        throat.min_cut_area(z, res, stage, a, a)

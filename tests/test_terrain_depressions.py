"""brc_tools.terrain.depressions on synthetic terrain with known answers (numpy + scipy)."""

from __future__ import annotations

import numpy as np
import pytest

from brc_tools.terrain import depressions as dp
from brc_tools.terrain.dem import Grid


def two_basins(ny=41, nx=81, res=100.0, floor_a=1000.0, floor_b=900.0, wall=1500.0, pass_z=1180.0):
    """Two flat-floored basins separated by a wall with one notch (the pass)."""
    z = np.full((ny, nx), wall)
    z[5:36, 5:35] = floor_a
    z[5:36, 46:76] = floor_b
    z[20, 35:46] = pass_z                     # a one-cell notch through the wall
    return z


def test_sill_between_two_basins_is_the_notch():
    z = two_basins()
    sill = dp.sill_between(z, (20, 10), (20, 60), tol=0.5)
    assert sill == pytest.approx(1180.0, abs=0.5)


def test_sill_is_the_higher_floor_when_the_basins_are_open_to_each_other():
    z = two_basins(pass_z=800.0)
    assert dp.sill_between(z, (20, 10), (20, 60)) == pytest.approx(1000.0)


def test_sill_is_inf_when_a_nan_wall_separates_them():
    z = two_basins()
    z[:, 40] = np.nan
    assert dp.sill_between(z, (20, 10), (20, 60)) == float("inf")


def test_sill_accepts_masks():
    z = two_basins()
    a = np.zeros(z.shape, bool)
    a[10:30, 8:30] = True
    b = np.zeros(z.shape, bool)
    b[10:30, 50:70] = True
    assert dp.sill_between(z, a, b, tol=0.5) == pytest.approx(1180.0, abs=0.5)


def test_volume_stage_of_a_flat_floor_is_area_times_depth():
    z = np.full(100, 1000.0)
    vol, area = dp.volume_stage(z, 100.0 * 100.0, [1000.0, 1010.0, 1100.0])
    assert vol == pytest.approx([0.0, 100 * 1e4 * 10.0, 100 * 1e4 * 100.0])
    assert area == pytest.approx([0.0, 1e6, 1e6])


def test_volume_stage_of_a_cone_matches_the_integral():
    # a linear ramp of cell elevations 0..99 m: V(Z) = sum(max(Z - z, 0)) * area
    z = np.arange(100.0)
    vol, _ = dp.volume_stage(z, 1.0, [50.0])
    assert vol[0] == pytest.approx(sum(50.0 - k for k in range(50)))


def test_stage_for_volume_inverts_volume_stage():
    rng = np.random.default_rng(0)
    z = rng.uniform(1000.0, 1300.0, 5000)
    stages = np.array([1005.0, 1100.0, 1250.0, 1400.0])
    vol, _ = dp.volume_stage(z, 900.0, stages)
    back = dp.stage_for_volume(z, 900.0, vol)
    assert back == pytest.approx(stages, abs=1e-6)


def test_inventory_finds_a_bowl_with_its_volume_and_spill():
    ny = nx = 41
    res = 50.0
    jj, ii = np.indices((ny, nx))
    r = np.hypot(jj - 20, ii - 20) * res
    z = 2000.0 + 0.1 * r                          # a cone rising outward ...
    depth = np.maximum(2040.0 - z, 0.0)           # ... filled to 2040 m: a bowl of radius 400 m
    lab, deps = dp.inventory(z, depth, res * res, min_depth_m=1.0, min_cells=4)
    assert len(deps) == 1
    d = deps[0]
    assert d.max_depth_m == pytest.approx(40.0)
    assert d.spill_m == pytest.approx(2040.0)
    assert d.floor_m == pytest.approx(2000.0)
    assert d.volume_m3 == pytest.approx(float(depth[depth > 1.0].sum()) * res * res)
    assert d.deepest_ji == (20, 20)
    assert lab[20, 20] == 1 and lab[0, 0] == 0


def test_inventory_orders_by_volume_and_drops_small_pits():
    z = np.full((30, 30), 100.0)
    depth = np.zeros_like(z)
    depth[2:6, 2:6] = 5.0            # 16 cells x 5 m
    depth[10:20, 10:20] = 3.0        # 100 cells x 3 m: the larger volume
    depth[25, 25] = 9.0              # a single-cell pit: dropped
    _, deps = dp.inventory(z - depth, depth, 100.0, min_depth_m=2.0, min_cells=4)
    assert [d.n_cells for d in deps] == [100, 16]
    assert deps[0].id == 1


def test_lowest_cell_finds_the_floor_near_a_point():
    pytest.importorskip("pyproj")
    z = np.full((50, 50), 500.0)
    z[30, 22] = 300.0
    grid = Grid(x0=500000.0, y1=4500000.0, res=100.0, ny=50, nx=50)
    lon, lat = grid.lonlat(28, 20)
    assert dp.lowest_cell(z, grid, float(lat), float(lon), radius_m=500.0) == (30, 22)

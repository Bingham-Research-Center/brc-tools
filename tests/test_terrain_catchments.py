"""brc_tools.terrain.catchments on a synthetic basin (numpy/scipy only)."""

from __future__ import annotations

import numpy as np

from brc_tools.terrain import catchments as ct
from brc_tools.terrain import d8
from brc_tools.terrain.dem import Grid


def bowl_with_outlet(ny=21, nx=21, res=100.0):
    """A bowl whose floor is at 1000 m, walls rising to ~1700 m, and one outlet notch
    on the east side so the floor drains out through the rim: the Uinta Basin in a
    sandbox."""
    jj, ii = np.indices((ny, nx))
    r = np.hypot(jj - ny // 2, ii - nx // 2)
    z = 1000.0 + np.clip(r - 4.0, 0.0, None) ** 2 * 6.0           # flat floor, parabolic walls
    z = np.minimum(z, 1700.0)
    z[ny // 2, nx // 2:] = 1000.0 - 0.5 * (ii[ny // 2, nx // 2:] - nx // 2)   # a river to the east edge
    return z.astype(np.float32), Grid(0.0, ny * res, res, ny, nx)


def test_basin_floor_is_the_sink_component_only():
    z, grid = bowl_with_outlet()
    ny, nx = z.shape
    rcv = d8.d8_receivers(z, grid.res)
    fo = d8.flow_accumulation(rcv)
    outlet = ny // 2 * nx + (nx - 1)
    hydro = ct.hydro_mask(rcv, fo.order, fo.starts, outlet, {})
    assert hydro.reshape(ny, nx)[ny // 2, ny // 2]
    floor = ct.basin_floor(z, 1150.0, (ny // 2, nx // 2), hydro)
    assert floor[ny // 2, nx // 2] and not floor[0, 0]
    assert floor.sum() < (z < 1150.0).sum() + 1
    # a rim below the sink raises
    import pytest
    with pytest.raises(RuntimeError):
        ct.basin_floor(z, 900.0, (ny // 2, nx // 2), hydro)


def test_rim_crossings_receiver_inside():
    z, grid = bowl_with_outlet()
    ny, nx = z.shape
    rcv = d8.d8_receivers(z, grid.res)
    fo = d8.flow_accumulation(rcv)
    outlet = ny // 2 * nx + (nx - 1)
    hydro = ct.hydro_mask(rcv, fo.order, fo.starts, outlet, {})
    floor = ct.basin_floor(z, 1150.0, (ny // 2, nx // 2), hydro)
    xc = ct.rim_crossings(floor, rcv)
    ff = floor.ravel()
    assert xc.size > 0
    assert np.all(~ff[xc]) and np.all(ff[rcv[xc]])
    # every catchment behind a crossing lies off the floor
    lab = d8.label_upstream(rcv, fo.order, fo.starts, xc, np.arange(xc.size, dtype=np.int32))
    leak = ct.floor_leak_fraction(lab, floor, xc.size, grid.cell_area_m2,
                                  np.bincount(lab[lab >= 0], minlength=xc.size) * grid.cell_area_m2)
    assert np.all(leak == 0.0)


def test_aggregate_hypsometry_sums_to_area():
    z, grid = bowl_with_outlet()
    ny, nx = z.shape
    rcv = d8.d8_receivers(z, grid.res)
    fo = d8.flow_accumulation(rcv)
    lab = np.where(np.arange(z.size) % 2 == 0, 0, 1).astype(np.int32)   # two arbitrary labels
    slope = d8.slope_deg(z, grid.res)
    zb = ct.elevation_bins(z, 50.0)
    h = ct.aggregate(lab, 2, grid.cell_area_m2, z, slope, zb)
    np.testing.assert_allclose(h.hyps_m2.sum(axis=1), h.area_m2)
    assert h.area_m2.sum() == z.size * grid.cell_area_m2
    assert h.z_max_m.max() == z.max() and 1000.0 <= h.z_mean_m.min() <= 1700.0
    assert 0.0 <= h.steep_fraction.min() <= h.steep_fraction.max() <= 1.0
    fl = ct.flow_length(lab, np.ones(z.size, np.float32) * 7.0, 2)
    assert fl.tolist() == [7.0, 7.0]


def test_area_above_and_supply_curve_monotone():
    z, grid = bowl_with_outlet()
    lab = np.zeros(z.size, dtype=np.int32)
    slope = d8.slope_deg(z, grid.res)
    zb = ct.elevation_bins(z, 50.0)
    h = ct.aggregate(lab, 1, grid.cell_area_m2, z, slope, zb)
    assert ct.area_above(h.hyps_m2, zb, zb[0])[0] == h.area_m2[0]
    assert ct.area_above(h.hyps_m2, zb, 1700.0)[0] < ct.area_above(h.hyps_m2, zb, 1100.0)[0]
    zs, phi = ct.supply_curve(h.hyps_m2, zb, 25.0)
    assert np.all(np.diff(phi) <= 0.0) and phi[0] == 25.0 * h.area_m2[0]
    assert zs.size == phi.size


def test_hydro_mask_excludes_cut_upstream():
    z, grid = bowl_with_outlet()
    ny, nx = z.shape
    rcv = d8.d8_receivers(z, grid.res)
    fo = d8.flow_accumulation(rcv)
    outlet = ny // 2 * nx + (nx - 1)
    cut = ny // 2 * nx + (nx - 4)                        # a cut on the river, 3 cells upstream of the outlet
    hydro = ct.hydro_mask(rcv, fo.order, fo.starts, outlet, {"river": cut}).reshape(ny, nx)
    assert not hydro[ny // 2, nx - 4] and not hydro[ny // 2, nx // 2]
    assert hydro[ny // 2, nx - 2]


def test_touches_edge_or_nodata_flags_truncation():
    z, grid = bowl_with_outlet()
    ny, nx = z.shape
    lab = np.full(z.size, -1, dtype=np.int32)
    lab[:nx] = 0                                        # a label along the north edge
    lab[10 * nx + 10] = 1                               # one interior cell
    t = ct.touches_edge_or_nodata(lab, 2, z)
    assert t.tolist() == [True, False]
    z2 = z.copy()
    z2[10, 11] = np.nan
    assert ct.touches_edge_or_nodata(lab, 2, z2).tolist() == [True, True]


def test_line_max_acc_cell_finds_the_river():
    z, grid = bowl_with_outlet()
    ny, nx = z.shape
    rcv = d8.d8_receivers(z, grid.res)
    acc = d8.flow_accumulation(rcv).acc
    # a north-south line at x = 18 cells crosses the river in row ny//2
    x = grid.x0 + 18.5 * grid.res
    lon0, lat0 = grid.lonlat_xy(x, grid.y1 - 2 * grid.res)
    lon1, lat1 = grid.lonlat_xy(x, grid.y1 - (ny - 2) * grid.res)
    c = ct.line_max_acc_cell(grid, acc, (lat0, lon0, lat1, lon1))
    assert c // nx == ny // 2 and c % nx == 18

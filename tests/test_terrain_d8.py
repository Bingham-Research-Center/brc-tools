"""brc_tools.terrain.d8 on tiny synthetic DEMs (numpy only; richdem tests skip without it)."""

from __future__ import annotations

import numpy as np
import pytest

from brc_tools.terrain import d8
from brc_tools.terrain.dem import Grid


def tilted_plane(ny=6, nx=8, res=10.0):
    jj, ii = np.indices((ny, nx))
    return (100.0 - 2.0 * ii - 0.5 * jj).astype(np.float32)      # falls east and south


def v_valley(ny=7, nx=9, res=10.0):
    """A valley along the centre row (j = 3) that drains east: walls rise 5 m per row
    away from the axis, the floor falls 1 m per column."""
    jj, ii = np.indices((ny, nx))
    return (50.0 - 1.0 * ii + 5.0 * np.abs(jj - 3)).astype(np.float32)


def test_receivers_on_a_tilted_plane_all_point_downhill():
    z = tilted_plane()
    ny, nx = z.shape
    rcv = d8.d8_receivers(z, 10.0)
    zf = z.ravel()
    own = np.arange(z.size)
    moved = rcv != own
    assert np.all(zf[rcv[moved]] < zf[moved])
    # only the east column and the south-east corner can be sinks
    sinks = np.flatnonzero(~moved)
    assert set(sinks % nx) <= {nx - 1} or set(sinks // nx) <= {ny - 1}


def test_diagonal_step_length_is_res_sqrt2():
    z = tilted_plane()
    rcv = d8.d8_receivers(z, 10.0)
    step = d8.step_length(rcv, z.shape[1], 10.0)
    dd = np.abs(rcv - np.arange(z.size))
    assert np.allclose(step[(dd == z.shape[1] + 1) | (dd == z.shape[1] - 1)], 10.0 * np.sqrt(2))
    assert np.allclose(step[(dd == 1) | (dd == z.shape[1])], 10.0)


def test_accumulation_of_a_v_valley_equals_column_count():
    z = v_valley()
    ny, nx = z.shape
    rcv = d8.d8_receivers(z, 10.0)
    fo = d8.flow_accumulation(rcv)
    acc = fo.acc.reshape(ny, nx)
    # the valley axis at the east end drains every cell of the grid
    assert acc[3, nx - 1] == ny * nx
    # along the axis the count is a whole number of columns: (i+1) columns x ny rows
    for i in range(nx - 1):
        assert acc[3, i] == (i + 1) * ny
    assert fo.n_levels >= nx


def test_kahn_order_places_receivers_after_donors():
    z = v_valley()
    rcv = d8.d8_receivers(z, 10.0)
    fo = d8.flow_accumulation(rcv)
    pos = np.empty(rcv.size, dtype=int)
    pos[fo.order] = np.arange(rcv.size)
    moved = rcv != np.arange(rcv.size)
    assert np.all(pos[rcv[moved]] > pos[moved])
    assert sorted(fo.order.tolist()) == list(range(rcv.size))


def test_cycle_raises():
    rcv = np.array([1, 0, 2], dtype=np.int32)          # 0 <-> 1 is a cycle
    with pytest.raises(RuntimeError):
        d8.flow_accumulation(rcv)


def test_label_upstream_and_flow_distance():
    z = v_valley()
    ny, nx = z.shape
    rcv = d8.d8_receivers(z, 10.0)
    fo = d8.flow_accumulation(rcv)
    step = d8.step_length(rcv, nx, 10.0)
    root = 3 * nx + 4                                    # axis cell in column 4
    lab, dist = d8.label_upstream(rcv, fo.order, fo.starts, np.array([root]), np.array([7]), step=step)
    lab = lab.reshape(ny, nx)
    assert lab[3, 4] == 7
    assert np.all(lab[:, :5] == 7)                       # everything at or west of column 4 drains through it
    assert np.all(lab[:, 5:] == -1)                      # downstream of the root is not part of it
    d = dist.reshape(ny, nx)
    assert d[3, 4] == 0.0 and d[3, 0] == pytest.approx(40.0)
    assert d[0, 4] > d[1, 4] > d[2, 4] > 0.0


def test_walks_follow_the_main_stem():
    z = v_valley()
    ny, nx = z.shape
    rcv = d8.d8_receivers(z, 10.0)
    fo = d8.flow_accumulation(rcv)
    c = 3 * nx + 4
    assert d8.walk_downstream(rcv, c, 2) == 3 * nx + 6
    assert d8.walk_upstream_main(rcv, fo.acc, c, 2, nx) == 3 * nx + 2
    # from the valley head the largest donor is the wall column above it, up to the corner
    assert d8.walk_upstream_main(rcv, fo.acc, 3 * nx, 5, nx) == 0
    assert d8.walk_upstream_main(rcv, fo.acc, 0, 5, nx) == 0                # no donor: stays put


def test_channel_mask_threshold():
    z = v_valley()
    rcv = d8.d8_receivers(z, 10.0)
    acc = d8.flow_accumulation(rcv).acc.reshape(z.shape)
    m = d8.channel_mask(acc, 100.0, 0.002)               # 2000 m2 = 20 cells
    assert m[3, 8] and not m[0, 0]
    assert m.sum() == (acc >= 20).sum()


def test_slope_deg_of_a_plane():
    z = np.fromfunction(lambda j, i: 10.0 * i, (5, 5), dtype=float)   # 10 m rise per 10 m
    s = d8.slope_deg(z, 10.0)
    assert np.allclose(s[1:-1, 1:-1], 45.0)


def test_fill_depressions_removes_a_pit():
    rd = pytest.importorskip("richdem")  # noqa: F841
    z = tilted_plane()
    z[3, 3] = 0.0                                        # a pit well below its neighbours
    grid = Grid(0.0, 60.0, 10.0, *z.shape)
    zf = d8.fill_depressions(z, grid)
    # D8 drains through diagonals too: the spill point is the lowest of all EIGHT neighbours
    spill = min(z[j, i] for j in (2, 3, 4) for i in (2, 3, 4) if (j, i) != (3, 3))
    assert zf[3, 3] >= spill - 1e-3 and zf[3, 3] < spill + 1.0
    rcv = d8.d8_receivers(zf, 10.0)
    assert rcv[3 * z.shape[1] + 3] != 3 * z.shape[1] + 3   # the pit now drains
    assert np.isnan(d8.fill_depressions(np.where(np.arange(z.size).reshape(z.shape) == 0, np.nan, z), grid)[0, 0])

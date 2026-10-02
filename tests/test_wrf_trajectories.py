"""Unit tests for brc_tools.nwp.wrf_trajectories (synthetic frames; no real wrfout).

The integrator works on plain arrays, so most tests build :class:`Frame` objects by hand
with answers that can be written down: a uniform wind, a solid-body rotation that must
close, a flow parallel to sloping model levels that must stay on its level.  One test goes
through files written from the shared synthetic wrfout to cover the reading path.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest
from _wrf_synthetic import make_synthetic_wrf

from brc_tools.nwp import wrf_trajectories as wt

T0 = datetime(2025, 1, 27, 6, 0, 0)
DX = 600.0


def _statics(ny=60, nx=60, slope_m_per_cell=0.0):
    jj, ii = np.meshgrid(np.arange(ny), np.arange(nx), indexing="ij")
    return wt.Statics(lat=40.0 + 0.005 * jj, lon=-110.0 + 0.007 * ii, hgt=500.0 + slope_m_per_cell * ii,
                      msf=np.ones((ny, nx)), dx=DX, dy=DX)


def _frames(statics, u, v, w, *, nz=6, n=7, step_s=600, dz=100.0, rise_m_s=0.0):
    """``n`` frames ``step_s`` apart; u, v, w are scalars or (nz, ny, nx) arrays (or callables of the frame number)."""
    ny, nx = statics.shape
    out = []
    for m in range(n):
        z_w = statics.hgt[np.newaxis] + dz * np.arange(nz + 1).reshape(-1, 1, 1) + rise_m_s * m * step_s
        fields = [np.broadcast_to(np.asarray(f(m) if callable(f) else f, dtype=float), (nz, ny, nx)) for f in (u, v, w)]
        theta = np.broadcast_to(280.0 + 2.0 * np.arange(nz).reshape(-1, 1, 1), (nz, ny, nx))
        out.append(wt.frame_from_fields(T0 + timedelta(seconds=m * step_s), *fields, z_w, statics, theta=theta))
    return out


def test_uniform_flow_displacement_is_exact():
    st = _statics()
    fr = _frames(st, 3.0, -1.5, 0.0)
    res = wt.integrate(fr, np.array([[10.0, 30.0, 2.0]]), T0, 1.0)
    assert res["time"].size == 7                       # the start and six frame times
    np.testing.assert_allclose(res["i"][-1, 0], 10.0 + 3.0 * 3600 / DX, atol=1e-6)
    np.testing.assert_allclose(res["j"][-1, 0], 30.0 - 1.5 * 3600 / DX, atol=1e-6)
    np.testing.assert_allclose(res["k"][:, 0], 2.0, atol=1e-9)
    np.testing.assert_allclose(res["z"][:, 0], 500.0 + 250.0, atol=1e-3)     # mass level 2 on flat ground
    np.testing.assert_allclose(res["theta"][:, 0], 284.0, atol=1e-4)


def test_solid_body_rotation_closes():
    st = _statics()
    omega = 2.0 * np.pi / 3600.0                      # one turn per hour, about the grid centre
    jj, ii = np.meshgrid(np.arange(60), np.arange(60), indexing="ij")
    u = (-omega * (jj - 30.0) * DX)[np.newaxis]
    v = (omega * (ii - 30.0) * DX)[np.newaxis]
    fr = _frames(st, u, v, 0.0)
    start = np.array([[40.0, 30.0, 1.0], [30.0, 18.0, 3.0]])
    res = wt.integrate(fr, start, T0, 1.0, dt_s=20.0)
    np.testing.assert_allclose(res["i"][-1], start[:, 0], atol=1e-3)
    np.testing.assert_allclose(res["j"][-1], start[:, 1], atol=1e-3)
    half = res["i"][3], res["j"][3]                    # after half a turn the parcel is opposite
    np.testing.assert_allclose(half[0][0], 20.0, atol=1e-3)
    np.testing.assert_allclose(half[1][0], 30.0, atol=1e-3)
    rk2 = wt.integrate(fr, start, T0, 1.0, dt_s=20.0, scheme="rk2")
    err4 = np.hypot(res["i"][-1] - start[:, 0], res["j"][-1] - start[:, 1]).max()
    err2 = np.hypot(rk2["i"][-1] - start[:, 0], rk2["j"][-1] - start[:, 1]).max()
    assert err4 < err2 < 0.05


def test_flow_parallel_to_sloping_levels_stays_on_its_level():
    st = _statics(slope_m_per_cell=50.0)               # 50 m rise per 600 m cell
    u = 4.0
    fr = _frames(st, u, 0.0, u * 50.0 / DX)            # w = u * dz/dx: parallel to the levels
    res = wt.integrate(fr, np.array([[10.0, 30.0, 3.0]]), T0, 0.5)
    np.testing.assert_allclose(res["k"][:, 0], 3.0, atol=1e-5)
    np.testing.assert_allclose(res["i"][-1, 0], 10.0 + u * 1800 / DX, atol=1e-6)
    # it climbed with the terrain: 12 cells * 50 m
    np.testing.assert_allclose(res["z"][-1, 0] - res["z"][0, 0], 600.0, atol=0.05)


def test_horizontal_flow_over_a_slope_crosses_levels_at_constant_height():
    st = _statics(slope_m_per_cell=50.0)
    fr = _frames(st, 4.0, 0.0, 0.0)                    # w = 0: the parcel must keep its height, not its level
    res = wt.integrate(fr, np.array([[10.0, 30.0, 3.0]]), T0, 300.0 / 3600.0)
    np.testing.assert_allclose(res["k"][-1, 0], 2.0, atol=1e-4)     # 2 cells * 50 m = one 100 m level down
    np.testing.assert_allclose(res["z"][-1, 0], res["z"][0, 0], atol=0.05)


def test_levels_that_rise_with_the_air_do_not_move_the_parcel():
    st = _statics()
    fr = _frames(st, 0.0, 0.0, 0.1, rise_m_s=0.1)      # the air rises at 0.1 m/s and so do the levels
    res = wt.integrate(fr, np.array([[20.0, 20.0, 2.0]]), T0, 1.0)
    np.testing.assert_allclose(res["k"][:, 0], 2.0, atol=1e-6)
    off = wt.integrate(fr, np.array([[20.0, 20.0, 2.0]]), T0, 1.0, level_motion=False)
    assert off["k"][-1, 0] > 4.0                        # without the term the parcel is carried through the levels


def test_backward_undoes_forward_in_an_unsteady_flow():
    st = _statics()
    omega = 2.0 * np.pi / 7200.0
    jj, ii = np.meshgrid(np.arange(60), np.arange(60), indexing="ij")
    fr = _frames(st, lambda m: (-omega * (jj - 30.0) * DX)[np.newaxis] * (1.0 + 0.2 * m),
                 lambda m: (omega * (ii - 30.0) * DX)[np.newaxis] * (1.0 + 0.2 * m), 0.0)
    start = np.array([[38.0, 33.0, 1.0]])
    fwd = wt.integrate(fr, start, T0, 1.0, dt_s=10.0)
    end = np.array([[fwd["i"][-1, 0], fwd["j"][-1, 0], fwd["k"][-1, 0]]])
    back = wt.integrate(fr, end, T0 + timedelta(hours=1), -1.0, dt_s=10.0)
    np.testing.assert_allclose([back["i"][-1, 0], back["j"][-1, 0]], start[0, :2], atol=1e-3)
    assert back["time"][0] > back["time"][-1]           # recorded in the order travelled


def test_parcel_leaving_the_grid_is_dropped_and_others_survive():
    st = _statics()
    fr = _frames(st, 8.0, 0.0, 0.0)                     # 48 cells per hour eastward
    res = wt.integrate(fr, np.array([[40.0, 30.0, 1.0], [5.0, 30.0, 1.0]]), T0, 1.0)
    assert np.isnan(res["i"][-1, 0]) and np.isnan(res["z"][-1, 0])
    np.testing.assert_allclose(res["i"][-1, 1], 53.0, atol=1e-6)


def test_parcels_are_held_at_the_lowest_level():
    st = _statics()
    fr = _frames(st, 0.0, 0.0, -1.0)                    # subsidence into the ground
    res = wt.integrate(fr, np.array([[20.0, 20.0, 1.0]]), T0, 0.5)
    assert res["k"][-1, 0] == pytest.approx(0.0)


def test_release_points_invert_the_grid():
    st = _statics()
    rel = wt.release_points(st, [40.0 + 0.005 * 12.5], [-110.0 + 0.007 * 7.25], levels=(0, 2))
    np.testing.assert_allclose(rel, [[7.25, 12.5, 0.0], [7.25, 12.5, 2.0]], atol=1e-6)
    with pytest.raises(ValueError):
        wt.release_points(st, [39.0], [-110.0])


def test_integrate_rejects_times_outside_the_frames():
    st = _statics()
    fr = _frames(st, 1.0, 0.0, 0.0, n=3)
    with pytest.raises(ValueError):
        wt.integrate(fr, np.array([[10.0, 10.0, 1.0]]), T0, 1.0)             # only 20 minutes of frames
    with pytest.raises(ValueError):
        wt.integrate(lambda n: fr[n], np.array([[10.0, 10.0, 1.0]]), T0, 0.2)  # a loader needs frame_times


def test_file_driver_reads_both_filename_conventions(tmp_path):
    # U = 5, V = 2, W = 0.1 on a grid with DX = 333.333 and levels 100 m apart over terrain rising
    # 20 m per cell in i and 10 m per cell in j: after 120 s a parcel has risen w*t = 12 m.
    for m, fmt in enumerate(("%Y-%m-%d_%H_%M_%S", "%Y-%m-%d_%H:%M:%S", "%Y-%m-%d_%H_%M_%S")):
        ds = make_synthetic_wrf(nz=8, ny=12, nx=12)
        t = T0 + timedelta(seconds=60 * m)
        ds.to_netcdf(tmp_path / f"auxhist2_d02_{t:{fmt}}")
        if m == 0:
            ds.to_netcdf(tmp_path / f"wrfout_d02_{t:{fmt}}")
    listing = wt.stream_times(tmp_path, 2, "auxhist2")
    assert [t for t, _ in listing] == [T0, T0 + timedelta(seconds=60), T0 + timedelta(seconds=120)]
    ds = wt.forward_trajectories(tmp_path, 2, np.array([[40.3, -109.7, 4.0]]), T0, 120.0 / 3600.0, stream="auxhist2")
    assert ds.sizes == {"time": 3, "parcel": 1}
    np.testing.assert_allclose(ds["i"].values[:, 0], 3.0 + 5.0 / 333.333 * np.array([0.0, 60.0, 120.0]), atol=1e-4)
    np.testing.assert_allclose(ds["j"].values[:, 0], 3.0 + 2.0 / 333.333 * np.array([0.0, 60.0, 120.0]), atol=1e-4)
    np.testing.assert_allclose(ds["z_msl"].values[-1, 0] - ds["z_msl"].values[0, 0], 12.0, atol=0.05)
    np.testing.assert_allclose(ds["lat"].values[-1, 0], 40.3 + 0.1 * 2.0 / 333.333 * 120.0, atol=1e-5)
    back = wt.back_trajectories(tmp_path, 2, np.array([[40.3, -109.7, 4.0]]), T0 + timedelta(seconds=120), 120.0 / 3600.0,
                                stream="auxhist2")
    np.testing.assert_allclose(back["i"].values[-1, 0], 3.0 - 5.0 / 333.333 * 120.0, atol=1e-4)
    coarse = wt.forward_trajectories(tmp_path, 2, np.array([[40.3, -109.7, 4.0]]), T0, 120.0 / 3600.0, stream="auxhist2", every=2)
    sep = wt.sampling_separation(ds, coarse)
    assert sep["horizontal_km"][0] < 1e-3 and sep["vertical_m"][0] < 0.05     # a steady flow does not care about sampling
    with pytest.raises(KeyError):
        wt.load_frame(_without(tmp_path, listing[0][1], "W"), T0, wt.read_statics(listing[0][1]))


def _without(tmp_path, src, var):
    import xarray as xr

    ds = xr.open_dataset(src, engine="netcdf4", decode_times=False).load()
    out = tmp_path / "no_w.nc"
    ds.drop_vars(var).to_netcdf(out)
    return out

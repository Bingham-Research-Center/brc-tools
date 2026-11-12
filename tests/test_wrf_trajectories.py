"""Unit tests for brc_tools.nwp.wrf_trajectories (synthetic frames; no real wrfout).

The integrator works on plain arrays, so most tests build :class:`Frame` objects by hand
with answers that can be written down: a uniform wind, a solid-body rotation that must
close, a flow parallel to sloping model levels that must stay on its level.  The file-driver
tests go through files written from the shared synthetic wrfout to cover the reading path,
including an auxiliary stream that packs several frames into one file.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

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


def _one_minute_run(tmp_path):
    """Three one-frame auxhist2 files a minute apart and one wrfout: the synthetic steady flow."""
    for m in range(3):
        t = T0 + timedelta(seconds=60 * m)
        make_synthetic_wrf(nz=8, ny=12, nx=12).to_netcdf(tmp_path / f"auxhist2_d02_{t:%Y-%m-%d_%H:%M:%S}")
    make_synthetic_wrf(nz=8, ny=12, nx=12).to_netcdf(tmp_path / f"wrfout_d02_{T0:%Y-%m-%d_%H:%M:%S}")
    return tmp_path


def test_a_file_still_being_written_does_not_stop_the_listing(tmp_path):
    """Opening every file to count frames must not let one truncated file (a run still
    writing) break the listing: it is listed at its filename time, with a warning."""
    run = _one_minute_run(tmp_path)
    last = sorted(run.glob("auxhist2_d02_*"))[-1]
    last.write_bytes(last.read_bytes()[: last.stat().st_size // 3])
    with pytest.warns(RuntimeWarning, match="could not be opened"):
        listing = wt.stream_times(run, 2, "auxhist2")
    assert [t for t, _ in listing] == [T0 + timedelta(seconds=60 * m) for m in range(3)]


def _multi_frame_file(path, times, u_values, *, with_times=True):
    """One auxhist-style file holding a frame per entry of ``times``, frame n with U = u_values[n], V = 0."""
    import xarray as xr

    frames = []
    for u in u_values:
        ds = make_synthetic_wrf(nz=6, ny=12, nx=12)
        ds["U"] = ds["U"] * 0.0 + u
        ds["V"] = ds["V"] * 0.0
        frames.append(ds)
    big = xr.concat(frames, dim="Time")
    if with_times:
        big["Times"] = ("Time", np.array([f"{t:%Y-%m-%d_%H:%M:%S}".encode() for t in times], dtype="S19"))
    big.to_netcdf(path)


def test_a_file_holding_several_frames_is_read_frame_by_frame(tmp_path):
    """Regression: an auxiliary stream packs many frames per file (frames_per_auxhist2), but the
    listing took one time per file NAME and load_frame read frame 0 of each, so every inner frame
    was skipped without a word and the winds were interpolated across the gap."""
    step = timedelta(minutes=10)
    t1 = T0 + 3 * step
    _multi_frame_file(tmp_path / f"auxhist2_d02_{T0:%Y-%m-%d_%H:%M:%S}", [T0, T0 + step, T0 + 2 * step], [0.5, 1.5, 0.5])
    _multi_frame_file(tmp_path / f"auxhist2_d02_{t1:%Y-%m-%d_%H:%M:%S}", [t1, t1 + step, t1 + 2 * step], [0.5, 0.5, 0.5])
    make_synthetic_wrf(nz=6, ny=12, nx=12).to_netcdf(tmp_path / f"wrfout_d02_{T0:%Y-%m-%d_%H:%M:%S}")
    listing = wt.stream_times(tmp_path, 2, "auxhist2")
    assert [t for t, _ in listing] == [T0 + k * step for k in range(6)]
    # u goes 0.5 -> 1.5 -> 0.5 m/s over the first 20 min and stays 0.5: 600, 600 and 300 m
    # (frame 0 of each file alone would say 0.5 throughout: 900 m)
    ds = wt.forward_trajectories(tmp_path, 2, np.array([[40.3, -109.7, 1.0]]), T0, 0.5, stream="auxhist2")
    assert ds.sizes["time"] == 4 and ds.attrs["frame_interval_s"] == 600.0
    np.testing.assert_allclose(ds["i"].values[:, 0], 3.0 + np.array([0.0, 600.0, 1200.0, 1500.0]) / 333.333, atol=1e-4)
    inner = wt.forward_trajectories(tmp_path, 2, np.array([[40.3, -109.7, 1.0]]), T0 + step, 10.0 / 60.0, stream="auxhist2")
    np.testing.assert_allclose(inner["i"].values[-1, 0], 3.0 + 600.0 / 333.333, atol=1e-4)   # an inner frame is a t0
    st = wt.read_statics(tmp_path / f"wrfout_d02_{T0:%Y-%m-%d_%H:%M:%S}")
    with pytest.raises(ValueError, match="none is valid"):
        wt.load_frame(listing[0][1], T0 + timedelta(minutes=5), st)
    bad = tmp_path / "no_times"
    bad.mkdir()
    _multi_frame_file(bad / f"auxhist2_d02_{T0:%Y-%m-%d_%H:%M:%S}", [T0, T0 + step], [0.5, 0.5], with_times=False)
    with pytest.raises(ValueError, match="holds 2 frames"):
        wt.stream_times(bad, 2, "auxhist2")


def test_map_factors_along_x_and_y_are_kept_apart(tmp_path):
    """Regression: MAPFAC_M was applied to both axes; on a lat-lon grid MAPFAC_MX and MAPFAC_MY differ."""
    st = dataclasses.replace(_statics(), msf=np.full((60, 60), 2.0), msf_y=np.full((60, 60), 0.5))
    fr = _frames(st, 3.0, 4.0, 0.0, n=1)[0]
    np.testing.assert_allclose(fr.idot, 3.0 * 2.0 / DX, rtol=1e-6)
    np.testing.assert_allclose(fr.jdot, 4.0 * 0.5 / DX, rtol=1e-6)
    ds = make_synthetic_wrf(nz=4, ny=6, nx=6)
    sfc = ("Time", "south_north", "west_east")
    for name, value in (("MAPFAC_M", 1.0), ("MAPFAC_MX", 1.25), ("MAPFAC_MY", 0.8)):
        ds[name] = (sfc, np.full((1, 6, 6), value))
    ds.to_netcdf(tmp_path / "latlon.nc")
    st = wt.read_statics(tmp_path / "latlon.nc")
    assert np.all(st.msf == 1.25) and np.all(st.msf_y == 0.8)
    ds.drop_vars(["MAPFAC_MX", "MAPFAC_MY"]).assign(MAPFAC_M=(sfc, np.full((1, 6, 6), 1.1))).to_netcdf(tmp_path / "lambert.nc")
    st = wt.read_statics(tmp_path / "lambert.nc")
    assert np.all(st.msf == 1.1) and st.msf_y is None                  # one factor for both axes


def test_the_file_driver_refuses_releases_it_cannot_honour(tmp_path):
    """Regression: release_points returns (i, j, k), and passed without release_is_index it was
    read as (lat, lon, level) -- far off the grid -- and came back as all-NaN parcels; a release
    above kmax was clipped down to the top level read, also without a word."""
    run = _one_minute_run(tmp_path)
    st = wt.read_statics(run / f"wrfout_d02_{T0:%Y-%m-%d_%H:%M:%S}")
    rel = wt.release_points(st, [40.3], [-109.7], levels=(1,))
    hours = 120.0 / 3600.0
    with pytest.raises(ValueError, match="release_is_index=True"):
        wt.forward_trajectories(run, 2, rel, T0, hours, stream="auxhist2")
    with pytest.raises(ValueError, match="outside the grid"):
        wt.forward_trajectories(run, 2, np.array([[45.0, -100.0, 1.0]]), T0, hours, stream="auxhist2")
    with pytest.raises(ValueError, match="outside the 12 x 12"):
        wt.forward_trajectories(run, 2, np.array([[30.0, 3.0, 1.0]]), T0, hours, stream="auxhist2", release_is_index=True)
    with pytest.raises(ValueError, match="kmax=3"):
        wt.forward_trajectories(run, 2, np.array([[40.3, -109.7, 6.5]]), T0, hours, stream="auxhist2", kmax=3)
    ok = wt.forward_trajectories(run, 2, rel, T0, hours, stream="auxhist2", release_is_index=True, kmax=3)
    assert np.isfinite(ok["i"].values).all()


def test_an_aware_t0_is_converted_to_utc(tmp_path):
    """Regression: an aware t0 never equalled a (naive UTC) frame time and was refused as
    "not a frame time"."""
    import xarray as xr

    run = _one_minute_run(tmp_path)
    release = np.array([[40.3, -109.7, 4.0]])
    naive = wt.forward_trajectories(run, 2, release, T0, 120.0 / 3600.0, stream="auxhist2")
    t0_mst = T0.replace(tzinfo=timezone.utc).astimezone(ZoneInfo("America/Denver"))
    xr.testing.assert_identical(wt.forward_trajectories(run, 2, release, t0_mst, 120.0 / 3600.0, stream="auxhist2"), naive)

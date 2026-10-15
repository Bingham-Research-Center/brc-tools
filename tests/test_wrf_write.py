"""brc_tools.nwp.wrf_write: files that WRF readers read back unchanged."""
from __future__ import annotations

import re
from datetime import datetime, timedelta

import numpy as np
import pytest

from brc_tools.nwp import wrf_output, wrf_write

# brc-voxel-viz's filename pattern (wrf.py TIME_RE) and its height constant
VOXEL_TIME_RE = re.compile(r"wrfout_(?P<domain>d\d\d)_(?P<date>\d{4}-\d{2}-\d{2})"
                           r"_(?P<hour>\d{2})[:_](?P<minute>\d{2})[:_](?P<second>\d{2})$")
VOXEL_G = 9.81


def _fields(ny=6, nx=8):
    jj, ii = np.mgrid[0:ny, 0:nx]
    hgt = 1500.0 + 40.0 * ii + 15.0 * jj
    z_w = wrf_write.terrain_following_levels(hgt, 3000.0, dz_bottom=20.0, fine_depth=200.0, stretch=1.2)
    zm = 0.5 * (z_w[:-1] + z_w[1:])
    theta = 280.0 + 0.003 * (zm - 1500.0)
    u = 5.0 + 0.001 * zm + 0.1 * ii[None]
    v = -2.0 + 0.2 * jj[None] + 0.0 * zm
    w = 0.01 * (z_w - hgt[None]) / 1000.0
    xlat = 40.3 + 0.001 * jj + 0.0 * ii
    xlong = -109.8 + 0.0013 * ii + 0.0 * jj
    return dict(hgt=hgt, z_w=z_w, theta=theta, u=u, v=v, w=w, xlat=xlat, xlong=xlong)


def test_levels_are_terrain_following_with_a_fine_bottom():
    hgt = np.array([[1433.0, 2942.0]])
    z_w = wrf_write.terrain_following_levels(hgt, 4000.0)
    assert np.all(np.diff(z_w, axis=0) > 0)
    assert np.allclose(z_w[0], hgt) and np.allclose(z_w[-1], 4000.0)
    assert np.allclose(0.5 * (z_w[0] + z_w[1]) - hgt, 7.5)              # first mass level 7.5 m up
    assert np.allclose(np.diff(z_w[:20], axis=0), 15.0)                  # same fine layers in both columns


def test_stagger_destaggers_exactly_for_linear_fields():
    x = np.linspace(0.0, 9.0, 10)
    a = 3.0 * x + 2.0
    s = wrf_write.stagger(a, 0)
    assert s.shape == (11,)
    assert np.allclose(0.5 * (s[:-1] + s[1:]), a)
    q = x ** 2
    back = 0.5 * (wrf_write.stagger(q, 0)[:-1] + wrf_write.stagger(q, 0)[1:])
    assert back[0] == pytest.approx(q[0]) and back[-1] == pytest.approx(q[-1])


def test_grid_rotation_points_grid_north_east_of_true_north_in_east_utm12():
    from pyproj import Transformer
    to_geo = Transformer.from_crs("EPSG:26912", "EPSG:4269", always_xy=True)
    to_utm = Transformer.from_crs("EPSG:4269", "EPSG:26912", always_xy=True)
    x, y = to_utm.transform(-109.5, 40.45)
    lon, lat = to_geo.transform(x, y)
    lon_up, lat_up = to_geo.transform(x, y + 100.0)
    cosa, sina = wrf_write.grid_rotation(lon, lat, lon_up, lat_up)
    gamma = np.degrees(np.arcsin(-sina))                 # convergence: grid north east of true north
    assert gamma == pytest.approx((111.0 - 109.5) * np.sin(np.radians(40.45)), abs=0.02)
    ue = 0.0 * cosa - 1.0 * sina                         # a grid-north wind blows a little east of north
    assert ue > 0


def test_round_trip_through_wrf_output(tmp_path):
    f = _fields()
    t0 = datetime(2000, 1, 1)
    cosa = np.full(f["hgt"].shape, np.cos(-0.015))
    sina = np.full(f["hgt"].shape, np.sin(-0.015))
    for k in range(2):
        t = t0 + timedelta(minutes=10 * k)
        wrf_write.write_wrfout(wrf_output.wrfout_path(tmp_path, 1, t), valid_time=t, start_time=t0,
                               dx=90.0, dy=90.0, title="test: idealised, NOT WRF", cosalpha=cosa, sinalpha=sina,
                               attrs={"BRC_PROVENANCE": "unit test"}, **f)
    assert wrf_output.list_valid_times(tmp_path, 1) == [t0, t0 + timedelta(minutes=10)]
    assert wrf_output.init_time(tmp_path, 1) == t0
    ds = wrf_output.open_wrfout(wrf_output.wrfout_path(tmp_path, 1, t0))
    try:
        assert np.allclose(wrf_output.potential_temperature(ds), f["theta"], atol=1e-4)
        assert np.allclose(wrf_output.geopotential_height_w(ds), f["z_w"] * VOXEL_G / wrf_output.G, atol=1e-2)
        u, v = wrf_output.grid_relative_winds(ds)
        assert np.allclose(u, f["u"], atol=1e-5) and np.allclose(v, f["v"], atol=1e-5)   # linear fields: exact
        ue, ve = wrf_output.earth_relative_winds(ds)
        assert np.allclose(ue, f["u"] * cosa - f["v"] * sina, atol=1e-5)
        assert np.allclose(wrf_output.vertical_velocity(ds), 0.5 * (f["w"][:-1] + f["w"][1:]), atol=1e-6)
        sec = wrf_output.build_section(ds, "EW", index=2)
        assert np.allclose(sec.terrain1d, f["hgt"][2]) and sec.theta2d.shape == (f["theta"].shape[0], 8)
        assert "NOT WRF" in ds.attrs["TITLE"] and ds.attrs["BRC_PROVENANCE"] == "unit test"
    finally:
        ds.close()


def test_files_meet_the_brc_voxel_viz_contract(tmp_path):
    from netCDF4 import Dataset
    f = _fields()
    t = datetime(2000, 1, 1, 0, 10)
    path = wrf_write.write_wrfout(wrf_output.wrfout_path(tmp_path, 1, t), valid_time=t, start_time=datetime(2000, 1, 1),
                                  dx=60.0, dy=60.0, title="idealised", **f)
    m = VOXEL_TIME_RE.search(path.name)
    assert m and m.group("domain") == "d01"
    with Dataset(path) as ds:
        need = {"HGT", "PH", "PHB", "XLAT", "XLONG", "T", "U", "V", "W", "COSALPHA", "SINALPHA"}
        assert need <= set(ds.variables)
        for name in ("west_east", "south_north", "bottom_top", "bottom_top_stag", "west_east_stag", "south_north_stag"):
            assert name in ds.dimensions
        for name in ("DX", "DY", "CEN_LAT", "CEN_LON", "MAP_PROJ_CHAR", "TITLE", "MP_PHYSICS"):
            assert hasattr(ds, name)
        assert float(ds.DX) == 60.0
        zm = 0.5 * ((ds["PH"][0] + ds["PHB"][0])[:-1] + (ds["PH"][0] + ds["PHB"][0])[1:]) / VOXEL_G
        assert np.allclose(zm, 0.5 * (f["z_w"][:-1] + f["z_w"][1:]), atol=1e-2)
        assert np.allclose(ds["T"][0] + 300.0, f["theta"], atol=1e-4)


def test_writer_refuses_bad_input(tmp_path):
    f = _fields()
    t = datetime(2000, 1, 1)
    kw = dict(valid_time=t, start_time=t, dx=90.0, dy=90.0, title="x")
    bad = dict(f, theta=np.where(f["theta"] > 282.0, np.nan, f["theta"]))
    with pytest.raises(ValueError, match="non-finite"):
        wrf_write.write_wrfout(tmp_path / "a", **kw, **bad)
    flipped = dict(f, z_w=f["z_w"][::-1])
    with pytest.raises(ValueError):
        wrf_write.write_wrfout(tmp_path / "b", **kw, **flipped)
    partial = dict(f, w=None)
    with pytest.raises(ValueError, match="together"):
        wrf_write.write_wrfout(tmp_path / "c", **kw, **partial)
    assert not list(tmp_path.iterdir())                     # nothing half-written is left behind

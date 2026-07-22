"""Smoke tests for brc_tools.visualize.nwp_maps (plan-view + NWP cross-section)."""

import numpy as np
import xarray as xr

from brc_tools.nwp.section import extract_nwp_section
from brc_tools.visualize import basemap
from brc_tools.visualize.nwp_maps import plot_nwp_section, plot_nwp_surface_map


def _synth(levels=(850, 800, 750, 700), ny=12, nx=16):
    lat1d = np.linspace(39.9, 41.1, ny)
    lon1d = np.linspace(248.0, 251.6, nx)  # 0..360
    lon2d, lat2d = np.meshgrid(lon1d, lat1d)
    rng = np.arange(ny * nx).reshape(ny, nx) % 7
    data = {
        "wind_u_10m": (("y", "x"), 3.0 + 0.1 * rng),
        "wind_v_10m": (("y", "x"), -2.0 + 0.1 * rng),
        "wind_speed_10m": (("y", "x"), 4.0 + 0.2 * rng),
        "terrain_height": (("y", "x"), 1400.0 + 30.0 * rng),
    }
    for i, lev in enumerate(levels):
        data[f"wind_u_{lev}"] = (("y", "x"), np.full((ny, nx), 5.0 + i))
        data[f"wind_v_{lev}"] = (("y", "x"), np.zeros((ny, nx)))
        data[f"temp_{lev}"] = (("y", "x"), np.full((ny, nx), 278.0 - 4.0 * i))
        data[f"height_{lev}"] = (("y", "x"), np.full((ny, nx), 1500.0 + 500.0 * i))
        data[f"omega_{lev}"] = (("y", "x"), np.full((ny, nx), 0.01))
    ds = xr.Dataset(data, coords={"latitude": (("y", "x"), lat2d),
                                  "longitude": (("y", "x"), lon2d)})
    return ds.expand_dims("time")


_TOWNS = {"Duchesne": {"lat": 40.16, "lon": -110.40},
          "Vernal": {"lat": 40.46, "lon": -109.53}}


def test_counties_layer_registered():
    assert "counties" in basemap._LAYERS
    assert basemap._LAYERS["counties"] == ("cultural", "admin_2_counties")


def test_surface_map_smoke(tmp_path):
    ds = _synth()
    out = plot_nwp_surface_map(
        ds, "wind_speed_10m", tmp_path / "map.png",
        waypoints=_TOWNS, extent=(-112.0, -108.5, 39.9, 41.1),
        overlays={"states": True, "counties": True, "roads": True,
                  "rivers": True, "lakes": True},
        title="smoke")
    assert out.exists() and out.stat().st_size > 0


def test_section_smoke(tmp_path):
    ds = _synth()
    sec = extract_nwp_section(ds, (40.3, -111.4), (40.06, -108.8),
                              [850, 800, 750, 700], n_points=60)
    lon2d = np.where(ds.longitude.values > 180, ds.longitude.values - 360,
                     ds.longitude.values)
    out = plot_nwp_section(
        sec, tmp_path / "sec.png", title="smoke", waypoints=_TOWNS, y_top_m=3000.0,
        locator=dict(lon2d=lon2d, lat2d=ds.latitude.values,
                     terrain2d=ds["terrain_height"].isel(time=0).values,
                     extent=(-112.0, -108.5, 39.9, 41.1), waypoints=_TOWNS))
    assert out.exists() and out.stat().st_size > 0

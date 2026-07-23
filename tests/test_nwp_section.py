"""Unit tests for brc_tools.nwp.section (arbitrary lat/lon NWP cross-sections)."""

import numpy as np
import xarray as xr

from brc_tools.nwp.section import NWPSection, extract_nwp_section


def _synth(levels=(850, 800, 750, 700), ny=10, nx=12, terrain=1200.0, with_time=True):
    """Small synthetic HRRR-like dataset: 0..360 lon, flat per-level vars."""
    lat1d = np.linspace(40.0, 41.0, ny)
    lon1d = np.linspace(248.0, 251.5, nx)  # 0..360 (i.e. -112 .. -108.5)
    lon2d, lat2d = np.meshgrid(lon1d, lat1d)
    data = {}
    for i, lev in enumerate(levels):
        h = 1000.0 + i * 500.0  # height rises as pressure falls
        data[f"wind_u_{lev}"] = (("y", "x"), np.full((ny, nx), 5.0))
        data[f"wind_v_{lev}"] = (("y", "x"), np.zeros((ny, nx)))
        data[f"temp_{lev}"] = (("y", "x"), np.full((ny, nx), 280.0 - 5.0 * i))
        data[f"height_{lev}"] = (("y", "x"), np.full((ny, nx), h))
        data[f"omega_{lev}"] = (("y", "x"), np.zeros((ny, nx)))
    data["terrain_height"] = (("y", "x"), np.full((ny, nx), terrain))
    ds = xr.Dataset(data, coords={"latitude": (("y", "x"), lat2d),
                                  "longitude": (("y", "x"), lon2d)})
    return ds.expand_dims("time") if with_time else ds


class TestExtract:
    def test_shapes_and_distance(self):
        ds = _synth()
        sec = extract_nwp_section(ds, (40.1, -111.5), (40.9, -108.6),
                                  [850, 800, 750, 700], n_points=50)
        assert isinstance(sec, NWPSection)
        assert sec.height2d.shape == (4, 50)
        assert sec.speed2d.shape == (4, 50)
        assert sec.distance_km[0] == 0.0
        assert np.all(np.diff(sec.distance_km) >= 0.0)
        assert sec.distance_km[-1] > 100.0  # hundreds of km across the basin

    def test_speed_and_along_sign(self):
        ds = _synth()
        # due-east transect + eastward 5 m/s wind -> speed 5, along ~ +5
        sec = extract_nwp_section(ds, (40.5, -111.5), (40.5, -108.6),
                                  [850, 800, 750, 700])
        np.testing.assert_allclose(np.nanmax(sec.speed2d), 5.0, atol=1e-6)
        assert np.nanmean(sec.along2d) > 4.5

    def test_below_ground_masked(self):
        ds = _synth(terrain=1500.0)  # above the 850 hPa height (1000 m)
        sec = extract_nwp_section(ds, (40.1, -111.5), (40.9, -108.6),
                                  [850, 800, 750, 700])
        assert np.all(np.isnan(sec.speed2d[0]))       # lowest level underground
        assert np.any(np.isfinite(sec.speed2d[-1]))   # 700 hPa (2500 m) above ground

    def test_longitude_wrapped(self):
        ds = _synth()  # coords in 0..360
        sec = extract_nwp_section(ds, (40.5, -111.0), (40.5, -109.0),
                                  [850, 800, 750, 700])
        assert np.all(sec.lon_line < 0.0)  # wrapped to -180..180

    def test_omega_to_w_and_theta(self):
        ds = _synth()
        sec = extract_nwp_section(ds, (40.1, -111.5), (40.9, -108.6),
                                  [850, 800, 750, 700])
        # zero omega -> zero vertical velocity; theta > temperature above 850 hPa
        assert np.allclose(np.nan_to_num(sec.w2d), 0.0)
        assert np.nanmin(sec.theta2d) > 280.0


class TestLookups:
    def test_terrain_height_alias(self):
        from brc_tools.nwp.source import load_lookups
        lu = load_lookups()
        assert "terrain_height" in lu["aliases"]
        assert lu["aliases"]["terrain_height"]["search"]["hrrr"] == "HGT:surface"

    def test_basin_landmarks_group(self):
        from brc_tools.nwp.source import load_lookups
        lu = load_lookups()
        assert "basin_landmarks" in lu["waypoint_groups"]
        for town in ("salt_lake_city", "rangely", "duchesne"):
            assert town in lu["waypoints"]

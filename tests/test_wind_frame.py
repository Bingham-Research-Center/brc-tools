"""HRRR grid-relative winds rotated to east/north (BasinWX ask P17).

The expected answer is derived independently of the formula under test: project the
HRRR Lambert grid with pyproj, step a short way due north from each point, and read
the direction that step takes on the grid. Earth-relative components are then the
projections of a grid wind onto true east and true north.
"""

import numpy as np
import pytest
import xarray as xr

from brc_tools.nwp.derived import (
    HRRR_LCC_LATIN_DEG,
    HRRR_LCC_LOV_DEG,
    grid_rotation_deg,
    grid_to_earth_winds,
    rotate_winds_to_earth,
    wind_direction,
    wind_speed,
)

pyproj = pytest.importorskip("pyproj")

HRRR_CRS = pyproj.CRS.from_proj4(
    f"+proj=lcc +lat_1={HRRR_LCC_LATIN_DEG} +lat_2={HRRR_LCC_LATIN_DEG} "
    f"+lat_0={HRRR_LCC_LATIN_DEG} +lon_0={HRRR_LCC_LOV_DEG} +R=6371229 +units=m"
)
TO_GRID = pyproj.Transformer.from_crs("EPSG:4326", HRRR_CRS, always_xy=True)

PLACES = {  # lat, lon
    "KVEL": (40.4409, -109.5099),
    "Daniels Summit": (40.30, -111.26),
    "Dinosaur": (40.244, -108.972),
    "on LoV": (38.5, -97.5),
    "east of LoV": (42.0, -80.0),
}


def _true_north_on_grid(lat, lon, step_deg=1e-3):
    x0, y0 = TO_GRID.transform(lon, lat)
    x1, y1 = TO_GRID.transform(lon, lat + step_deg)
    n = np.array([x1 - x0, y1 - y0])
    return n / np.hypot(*n)


@pytest.mark.parametrize("name", PLACES)
def test_rotation_matches_the_projection(name):
    lat, lon = PLACES[name]
    north = _true_north_on_grid(lat, lon)
    east = np.array([north[1], -north[0]])
    for u_g, v_g in ((1.0, 0.0), (0.0, 1.0), (3.0, -4.0), (-7.5, 2.0)):
        u_e, v_e = grid_to_earth_winds(np.float64(u_g), np.float64(v_g), lon)
        grid_wind = np.array([u_g, v_g])
        assert u_e == pytest.approx(grid_wind @ east, abs=1e-6)
        assert v_e == pytest.approx(grid_wind @ north, abs=1e-6)


def test_basin_rotation_size_and_sign():
    # The website measured "about 8 deg" placing the grid; west of LoV it is negative.
    assert grid_rotation_deg(-109.51) == pytest.approx(-7.48, abs=0.01)
    assert grid_rotation_deg(-111.26) == pytest.approx(-8.57, abs=0.01)
    assert grid_rotation_deg(-97.5) == 0.0
    # 0-360 longitudes (raw GRIB) give the same answer.
    assert grid_rotation_deg(360 - 109.51) == pytest.approx(grid_rotation_deg(-109.51))


def test_speed_kept_direction_turned():
    u_g, v_g = np.array([0.0]), np.array([-5.0])  # from grid-north at 5 m/s
    u_e, v_e = grid_to_earth_winds(u_g, v_g, -109.51)
    assert wind_speed(u_e, v_e)[0] == pytest.approx(5.0)
    # At KVEL the grid's y axis points 7.48 deg west of true north, so a wind from
    # grid-north is from 352.5 deg true: an unrotated direction reads 7.5 deg too high.
    assert wind_direction(u_e, v_e)[0] == pytest.approx(360 - 7.48, abs=0.01)


def _grid_ds():
    lon = np.array([[-110.4, -109.5], [-110.4, -109.5]])
    lat = np.array([[40.0, 40.0], [40.3, 40.3]])
    return xr.Dataset(
        {
            "wind_u_10m": (("time", "y", "x"), np.zeros((2, 2, 2))),
            "wind_v_10m": (("time", "y", "x"), np.full((2, 2, 2), 10.0)),
        },
        coords={"longitude": (("y", "x"), lon), "latitude": (("y", "x"), lat)},
    )


def test_dataset_rotation_once_only():
    ds = rotate_winds_to_earth(_grid_ds(), "wind_u_10m", "wind_v_10m")
    assert ds["wind_u_10m"].dims == ("time", "y", "x")
    assert ds["wind_u_10m"].attrs["wind_frame"] == "earth"
    first = ds["wind_u_10m"].values.copy()
    # A grid-north wind gains a westward component west of LoV.
    assert (first < 0).all()
    ds = rotate_winds_to_earth(ds, "wind_u_10m", "wind_v_10m")
    np.testing.assert_array_equal(ds["wind_u_10m"].values, first)


def test_dataset_without_winds_is_left_alone():
    ds = _grid_ds().drop_vars("wind_v_10m")
    out = rotate_winds_to_earth(ds, "wind_u_10m", "wind_v_10m")
    assert "wind_frame" not in out["wind_u_10m"].attrs

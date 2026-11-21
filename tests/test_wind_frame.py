"""Grid-relative winds rotated to east/north (BasinWX ask P17; any-model grid, GH #80).

The expected answer is derived independently of the formula under test: project the
Lambert grid with pyproj, step a short way due north from each point, and read the
direction that step takes on the grid. Earth-relative components are then the
projections of a grid wind onto true east and true north.

The grid always comes from what the GRIB declares (``WindGrid``), never from the
model's name: the attribute dicts below are copied from real messages.
"""

import numpy as np
import pytest
import xarray as xr

from brc_tools.nwp import NWPSource
from brc_tools.nwp.derived import (
    HRRR_GRID,
    WindGrid,
    grid_rotation_deg,
    grid_to_earth_winds,
    rotate_winds_to_earth,
    wind_direction,
    wind_speed,
)

pyproj = pytest.importorskip("pyproj")

# A secant Lambert grid (two distinct standard parallels), unlike HRRR's tangent one.
SECANT_GRID = WindGrid(
    grid_type="lambert", uv_relative_to_grid=True,
    lov_deg=-97.0, latin1_deg=33.0, latin2_deg=45.0,
)
GRIDS = {"hrrr": HRRR_GRID, "secant": SECANT_GRID}

# cfgrib attributes of real messages, trimmed to the grid keys.
# RRFS CONUS 3 km: rrfs.20261120/12 2dfld f006 UGRD:10 m (HRRR's sfc files say the same).
RRFS_CONUS_ATTRS = {
    "GRIB_gridType": "lambert", "GRIB_uvRelativeToGrid": 1,
    "GRIB_LaDInDegrees": 38.5, "GRIB_Latin1InDegrees": 38.5, "GRIB_Latin2InDegrees": 38.5,
    "GRIB_LoVInDegrees": 262.5, "GRIB_Nx": 1799, "GRIB_Ny": 1059,
}
# RRFS North America 13 km: rrfs.20261120/12 prslev f006 UGRD:700 mb.
RRFS_NA_ATTRS = {
    "GRIB_gridType": "rotated_ll", "GRIB_uvRelativeToGrid": 1,
    "GRIB_angleOfRotationInDegrees": 0.0,
    "GRIB_latitudeOfSouthernPoleInDegrees": -35.0,
    "GRIB_longitudeOfSouthernPoleInDegrees": 247.0,
}
# RRFS Alaska 3 km: cfgrib 0.9.15 exposes only the grid type for polar stereographic.
RRFS_AK_ATTRS = {"GRIB_gridType": "polar_stereographic"}
GEFS_ATTRS = {"GRIB_gridType": "regular_ll", "GRIB_Nx": 1440, "GRIB_Ny": 721}


def _to_grid(grid):
    crs = pyproj.CRS.from_proj4(
        f"+proj=lcc +lat_1={grid.latin1_deg} +lat_2={grid.latin2_deg} "
        f"+lat_0={grid.latin1_deg} +lon_0={grid.lov_deg} +R=6371229 +units=m"
    )
    return pyproj.Transformer.from_crs("EPSG:4326", crs, always_xy=True)

PLACES = {  # lat, lon
    "KVEL": (40.4409, -109.5099),
    "Daniels Summit": (40.30, -111.26),
    "Dinosaur": (40.244, -108.972),
    "on LoV": (38.5, -97.5),
    "east of LoV": (42.0, -80.0),
}


def _true_north_on_grid(grid, lat, lon, step_deg=1e-3):
    to_grid = _to_grid(grid)
    x0, y0 = to_grid.transform(lon, lat)
    x1, y1 = to_grid.transform(lon, lat + step_deg)
    n = np.array([x1 - x0, y1 - y0])
    return n / np.hypot(*n)


@pytest.mark.parametrize("grid_name", GRIDS)
@pytest.mark.parametrize("name", PLACES)
def test_rotation_matches_the_projection(name, grid_name):
    grid = GRIDS[grid_name]
    lat, lon = PLACES[name]
    north = _true_north_on_grid(grid, lat, lon)
    east = np.array([north[1], -north[0]])
    for u_g, v_g in ((1.0, 0.0), (0.0, 1.0), (3.0, -4.0), (-7.5, 2.0)):
        u_e, v_e = grid_to_earth_winds(np.float64(u_g), np.float64(v_g), lon, grid=grid)
        grid_wind = np.array([u_g, v_g])
        assert u_e == pytest.approx(grid_wind @ east, abs=1e-6)
        assert v_e == pytest.approx(grid_wind @ north, abs=1e-6)


def test_basin_rotation_size_and_sign():
    # The website measured "about 8 deg" placing the grid; west of LoV it is negative.
    assert HRRR_GRID.rotation_deg(-109.51) == pytest.approx(-7.48, abs=0.01)
    assert HRRR_GRID.rotation_deg(-111.26) == pytest.approx(-8.57, abs=0.01)
    assert HRRR_GRID.rotation_deg(-97.5) == 0.0
    # 0-360 longitudes (raw GRIB) give the same answer.
    assert HRRR_GRID.rotation_deg(360 - 109.51) == pytest.approx(HRRR_GRID.rotation_deg(-109.51))


def test_lambert_rotation_has_no_default_grid():
    with pytest.raises(TypeError):
        grid_rotation_deg(-109.51)
    with pytest.raises(TypeError):
        grid_to_earth_winds(np.float64(1.0), np.float64(0.0), -109.51)


def test_speed_kept_direction_turned():
    u_g, v_g = np.array([0.0]), np.array([-5.0])  # from grid-north at 5 m/s
    u_e, v_e = grid_to_earth_winds(u_g, v_g, -109.51, grid=HRRR_GRID)
    assert wind_speed(u_e, v_e)[0] == pytest.approx(5.0)
    # At KVEL the grid's y axis points 7.48 deg west of true north, so a wind from
    # grid-north is from 352.5 deg true: an unrotated direction reads 7.5 deg too high.
    assert wind_direction(u_e, v_e)[0] == pytest.approx(360 - 7.48, abs=0.01)


def _grid_ds(grid=HRRR_GRID):
    """A 2 x 2 Basin patch with a 10 m/s grid-north wind, stamped as NWPSource would."""
    lon = np.array([[-110.4, -109.5], [-110.4, -109.5]])
    lat = np.array([[40.0, 40.0], [40.3, 40.3]])
    return xr.Dataset(
        {
            "wind_u_10m": (("time", "y", "x"), np.zeros((2, 2, 2))),
            "wind_v_10m": (("time", "y", "x"), np.full((2, 2, 2), 10.0)),
        },
        coords={"longitude": (("y", "x"), lon), "latitude": (("y", "x"), lat)},
        attrs={} if grid is None else grid.to_attrs(),
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


# --- the grid comes from the GRIB, not the model's name (GH #80) -----------------


def test_rrfs_conus_declares_hrrrs_grid():
    assert WindGrid.from_grib_attrs(RRFS_CONUS_ATTRS) == HRRR_GRID


def test_grid_survives_the_dataset_attrs_round_trip():
    for grid in (HRRR_GRID, SECANT_GRID, WindGrid.from_grib_attrs(GEFS_ATTRS)):
        assert WindGrid.from_attrs(grid.to_attrs()) == grid
    assert WindGrid.from_attrs({}) is None


def test_dataset_without_a_grid_is_refused():
    with pytest.raises(ValueError, match="no grid definition"):
        rotate_winds_to_earth(_grid_ds(grid=None), "wind_u_10m", "wind_v_10m")
    # ... unless the caller names the grid outright.
    out = rotate_winds_to_earth(_grid_ds(grid=None), "wind_u_10m", "wind_v_10m", grid=HRRR_GRID)
    assert out["wind_u_10m"].attrs["wind_frame"] == "earth"


def test_rotated_latlon_winds_are_refused_not_given_a_lambert_angle():
    na = WindGrid.from_grib_attrs(RRFS_NA_ATTRS)
    assert na.grid_type == "rotated_ll" and na.uv_relative_to_grid
    with pytest.raises(NotImplementedError, match="rotated_ll"):
        rotate_winds_to_earth(_grid_ds(grid=na), "wind_u_10m", "wind_v_10m")


def test_grid_that_does_not_say_is_not_a_grid():
    # Alaska polar stereographic: cfgrib gives the type but not uvRelativeToGrid.
    assert WindGrid.from_grib_attrs(RRFS_AK_ATTRS) is None
    assert WindGrid.from_grib_attrs({}) is None


def test_regular_latlon_winds_are_already_earth_relative():
    gefs = WindGrid.from_grib_attrs(GEFS_ATTRS)
    out = rotate_winds_to_earth(_grid_ds(grid=gefs), "wind_u_10m", "wind_v_10m")
    np.testing.assert_array_equal(out["wind_u_10m"].values, 0.0)
    np.testing.assert_array_equal(out["wind_v_10m"].values, 10.0)
    assert out["wind_u_10m"].attrs["wind_frame"] == "earth"


def _fake_message(name, attrs):
    """One decoded GRIB message as Herbie hands it to NWPSource."""
    lon = np.array([[-110.4, -109.5], [-110.4, -109.5]])
    lat = np.array([[40.0, 40.0], [40.3, 40.3]])
    return xr.Dataset(
        {name: (("y", "x"), np.full((2, 2), 10.0), dict(attrs))},
        coords={"longitude": (("y", "x"), lon), "latitude": (("y", "x"), lat)},
    )


@pytest.mark.parametrize(
    "attrs, expected",
    [(RRFS_CONUS_ATTRS, HRRR_GRID), (RRFS_NA_ATTRS, WindGrid("rotated_ll", True)),
     (RRFS_AK_ATTRS, None)],
)
def test_nwpsource_copies_the_gribs_grid_onto_the_dataset(monkeypatch, attrs, expected):
    src = NWPSource("rrfs")
    monkeypatch.setattr(
        src, "_herbie_fetch",
        lambda init, fxx, search, product, retries: _fake_message(search.split(":")[0], attrs),
    )
    ds = src.fetch("2026-11-20 12Z", [0, 1], ["wind_u_10m", "wind_v_10m"], max_workers=1)
    assert WindGrid.from_attrs(ds.attrs) == expected
    if expected == HRRR_GRID:
        out = rotate_winds_to_earth(ds, "wind_u_10m", "wind_v_10m")
        assert out["wind_u_10m"].attrs["wind_frame"] == "earth"
    else:  # a grid with no formula, or none stated: refused, never HRRR's angle
        with pytest.raises((NotImplementedError, ValueError)):
            rotate_winds_to_earth(ds, "wind_u_10m", "wind_v_10m")

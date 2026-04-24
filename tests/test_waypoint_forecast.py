"""Shape-level tests for the HRRR waypoint-forecast JSON payload."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pytest
import xarray as xr

from brc_tools.nwp.waypoint_forecast import FIELD_SPECS, build_waypoint_payload


@pytest.fixture
def basin_dataset() -> xr.Dataset:
    """Synthetic HRRR surface grid covering the Uinta Basin with 2 time steps."""
    lats = np.linspace(40.1, 40.5, 5)
    lons = np.linspace(-111.3, -109.3, 5)
    lon2d, lat2d = np.meshgrid(lons, lats)
    times = np.array(
        [np.datetime64("2026-04-24T12:00:00"),
         np.datetime64("2026-04-24T13:00:00")]
    )
    shape = (2, lat2d.shape[0], lat2d.shape[1])
    ds = xr.Dataset(
        data_vars={
            "temp_2m": (("time", "y", "x"), np.full(shape, 283.15)),
            "dewpoint_2m": (("time", "y", "x"), np.full(shape, 273.15)),
            "wind_u_10m": (("time", "y", "x"), np.full(shape, 3.0)),
            "wind_v_10m": (("time", "y", "x"), np.full(shape, 4.0)),
            "wind_speed_10m": (("time", "y", "x"), np.full(shape, 5.0)),
            "wind_dir_10m": (("time", "y", "x"), np.full(shape, 216.87)),
            "rh_2m": (("time", "y", "x"), np.full(shape, 55.0)),
            "mslp": (("time", "y", "x"), np.full(shape, 101300.0)),
            "precip_1hr": (("time", "y", "x"), np.full(shape, 0.4)),
        },
        coords={
            "time": times,
            "latitude": (("y", "x"), lat2d),
            "longitude": (("y", "x"), lon2d),
        },
    )
    return ds


def test_payload_topshape(basin_dataset):
    init = dt.datetime(2026, 4, 24, 12, 0)
    payload = build_waypoint_payload(
        basin_dataset,
        group="basin_full",
        init_time=init,
        forecast_hours=[0, 1],
    )
    assert payload["model"] == "hrrr"
    assert payload["product"] == "waypoint_forecast"
    assert payload["group"] == "basin_full"
    assert payload["init_time"] == "2026-04-24T12:00:00Z"
    assert payload["forecast_hours"] == [0, 1]
    assert len(payload["valid_times"]) == 2
    assert set(FIELD_SPECS.keys()).issubset(payload["variables"].keys())
    assert len(payload["stations"]) == 6  # basin_full


def test_payload_stations_have_forecasts(basin_dataset):
    init = dt.datetime(2026, 4, 24, 12, 0)
    payload = build_waypoint_payload(
        basin_dataset,
        group="basin_full",
        init_time=init,
        forecast_hours=[0, 1],
    )
    for station in payload["stations"]:
        assert "id" in station and "lat" in station and "lon" in station
        for field in FIELD_SPECS:
            assert field in station["forecasts"]
            assert len(station["forecasts"][field]) == 2


def test_unit_transforms(basin_dataset):
    init = dt.datetime(2026, 4, 24, 12, 0)
    payload = build_waypoint_payload(
        basin_dataset,
        group="basin_full",
        init_time=init,
        forecast_hours=[0, 1],
    )
    station = payload["stations"][0]
    # 283.15 K -> 10.0 C
    assert station["forecasts"]["temp_2m_c"][0] == pytest.approx(10.0, abs=0.05)
    # 101300 Pa -> 1013.0 hPa
    assert station["forecasts"]["mslp_hpa"][0] == pytest.approx(1013.0, abs=0.05)
    # 5 m/s wind_speed carries through unchanged
    assert station["forecasts"]["wind_speed_10m_ms"][0] == pytest.approx(5.0, abs=0.05)


def test_unknown_group_raises(basin_dataset):
    with pytest.raises(ValueError, match="Unknown waypoint group"):
        build_waypoint_payload(
            basin_dataset,
            group="definitely_not_a_group",
            init_time=dt.datetime(2026, 4, 24, 12, 0),
            forecast_hours=[0],
        )

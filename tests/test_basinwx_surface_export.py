"""Unit tests for the BasinWX HRRR surface export."""

import datetime as dt

import numpy as np
import xarray as xr

from brc_tools.nwp.basinwx import (
    INDEX_FILENAME,
    build_surface_index,
    build_surface_payload,
    downsample_surface_dataset,
    prepare_surface_dataset,
)


def _sample_raw_dataset() -> xr.Dataset:
    times = np.array(["2026-04-16T00:00:00", "2026-04-16T01:00:00"], dtype="datetime64[s]")
    latitude = xr.DataArray(
        np.array([[40.0, 40.0, 40.0], [40.2, 40.2, 40.2]]),
        dims=("y", "x"),
    )
    longitude = xr.DataArray(
        np.array([[-110.4, -110.2, -110.0], [-110.4, -110.2, -110.0]]),
        dims=("y", "x"),
    )
    coords = {"time": times, "y": [0, 1], "x": [0, 1, 2], "latitude": latitude, "longitude": longitude}

    return xr.Dataset(
        coords=coords,
        data_vars={
            "temp_2m": (("time", "y", "x"), np.array([
                [[273.15, 274.15, 275.15], [276.15, 277.15, 278.15]],
                [[274.15, 275.15, 276.15], [277.15, 278.15, 279.15]],
            ])),
            "wind_u_10m": (("time", "y", "x"), np.full((2, 2, 3), 3.4)),
            "wind_v_10m": (("time", "y", "x"), np.full((2, 2, 3), -1.2)),
            "precip_1hr": (("time", "y", "x"), np.array([
                [[0.0, 1.2, 2.4], [1.5, 0.3, 0.0]],
                [[0.5, 2.0, 0.0], [0.0, 0.1, 0.6]],
            ])),
            "snowfall_1hr": (("time", "y", "x"), np.array([
                [[0.0, 0.001, 0.002], [0.0005, 0.0, 0.0]],
                [[0.0015, 0.0, 0.0], [0.0, 0.0, 0.0007]],
            ])),
            "categorical_rain": (("time", "y", "x"), np.array([
                [[0, 1, 1], [0, 1, 0]],
                [[1, 1, 0], [0, 0, 1]],
            ])),
            "categorical_snow": (("time", "y", "x"), np.array([
                [[0, 1, 1], [1, 0, 0]],
                [[1, 0, 0], [0, 0, 1]],
            ])),
        },
    )


def test_prepare_surface_dataset_converts_units_and_partitions_precip():
    prepared = prepare_surface_dataset(_sample_raw_dataset())

    assert prepared["temperature_2m_c"].isel(time=0, y=0, x=0).item() == 0.0
    assert prepared["wind_u_10m_ms"].isel(time=0, y=0, x=0).item() == 3.4
    assert prepared["wind_v_10m_ms"].isel(time=0, y=0, x=0).item() == -1.2
    assert prepared["rainfall_1h_mm"].isel(time=0, y=1, x=0).item() == 0.0
    assert prepared["rainfall_1h_mm"].isel(time=0, y=0, x=1).item() == 1.2
    assert prepared["snowfall_1h_mm"].isel(time=0, y=0, x=1).item() == 1.0
    assert prepared["snowfall_1h_mm"].isel(time=1, y=0, x=1).item() == 0.0


def test_downsample_surface_dataset_reduces_grid_shape():
    prepared = prepare_surface_dataset(_sample_raw_dataset())
    reduced = downsample_surface_dataset(prepared, stride=2)

    assert reduced.sizes["y"] == 1
    assert reduced.sizes["x"] == 2


def test_build_surface_payload_serializes_shapes_and_values():
    prepared = prepare_surface_dataset(_sample_raw_dataset())
    payload = build_surface_payload(
        downsample_surface_dataset(prepared, stride=1),
        init_time=dt.datetime(2026, 4, 16, 0, tzinfo=dt.timezone.utc),
        stride=1,
    )

    assert payload["model"] == "hrrr"
    assert payload["product"] == "surface_layers"
    assert payload["forecast_hours"] == [0, 1]
    assert payload["grid"]["shape"] == [2, 3]
    assert payload["field_shape"] == [2, 2, 3]
    assert len(payload["grid"]["lats"]) == 6
    assert len(payload["fields"]["temperature_2m_c"]) == 12
    assert payload["fields"]["temperature_2m_c"][0] == 0.0
    assert payload["fields"]["snowfall_1h_mm"][1] == 1.0
    assert payload["variables"]["rainfall_1h_mm"]["units"] == "Millimeters"


def test_build_surface_index_preserves_run_metadata():
    entries = [
        {
            "filename": "forecast_hrrr_surface_layers_20260416_0100Z.json",
            "init_time": "2026-04-16T01:00:00Z",
            "forecast_hours": [0, 1],
            "valid_times": ["2026-04-16T01:00:00Z", "2026-04-16T02:00:00Z"],
        }
    ]

    index_payload = build_surface_index(entries)

    assert index_payload["product"] == "surface_layers_index"
    assert index_payload["runs"][0]["filename"].endswith(".json")
    assert INDEX_FILENAME.endswith(".json")

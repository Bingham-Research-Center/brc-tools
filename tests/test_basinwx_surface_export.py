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
            # ASNOW, as HRRR sends it: snowfall depth (m) since the run began, never falling.
            "snowfall_1hr": (("time", "y", "x"), np.array([
                [[0.0, 0.001, 0.002], [0.0005, 0.0, 0.0]],
                [[0.0015, 0.001, 0.002], [0.0005, 0.0, 0.0007]],
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
    # A run total is not masked by the hour's snow flag (it is 0 at this point at t=1):
    # masking made the total drop to zero and come back the next hour.
    assert prepared["snowfall_1h_mm"].isel(time=1, y=0, x=1).item() == 1.0
    assert prepared["snowfall_1h_mm"].isel(time=1, y=1, x=0).item() == 0.5
    totals = prepared["snowfall_1h_mm"].values
    assert (np.diff(totals, axis=0) >= 0).all(), "a run total never falls"
    assert "since run start" in prepared["snowfall_1h_mm"].attrs["long_name"]


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


# --- one exporter, more than one model ----------------------------------------


def test_hrrr_names_are_unchanged_by_default():
    from brc_tools.nwp import basinwx

    init = dt.datetime(2026, 11, 20, 12, tzinfo=dt.timezone.utc)
    assert basinwx._surface_filename(init) == "forecast_hrrr_surface_layers_20261120_1200Z.json"
    assert basinwx._index_filename() == INDEX_FILENAME
    assert build_surface_index([])["model"] == "hrrr"


def test_rrfs_gets_its_own_files_and_model_label():
    from brc_tools.nwp import basinwx

    init = dt.datetime(2026, 11, 20, 12, tzinfo=dt.timezone.utc)
    assert basinwx._surface_filename(init, "rrfs") == (
        "forecast_rrfs_surface_layers_20261120_1200Z.json"
    )
    assert basinwx._index_filename("rrfs") == "forecast_rrfs_surface_layers_index.json"
    assert build_surface_index([], model="rrfs")["model"] == "rrfs"
    prepared = prepare_surface_dataset(_sample_raw_dataset())
    payload = build_surface_payload(
        prepared, init_time=dt.datetime(2026, 4, 16, 0, tzinfo=dt.timezone.utc),
        stride=1, model="rrfs",
    )
    assert payload["model"] == "rrfs"


def test_latest_init_times_step_by_the_models_cycle_spacing():
    from brc_tools.nwp import NWPSource
    from brc_tools.nwp.basinwx import latest_init_times

    now = dt.datetime(2026, 11, 20, 16, 30, tzinfo=dt.timezone.utc)
    hrrr = latest_init_times(3, now=now, source=NWPSource("hrrr"))
    assert [t.hour for t in hrrr] == [14, 13, 12]
    # RRFS: hourly files only at 00/03/.../21Z, and a 3 h availability lag.
    rrfs = latest_init_times(3, now=now, source=NWPSource("rrfs"))
    assert [t.hour for t in rrfs] == [12, 9, 6]


def test_unknown_model_is_refused_before_any_fetch(tmp_path):
    import pytest

    from brc_tools.nwp.basinwx import export_latest_surface_layers

    with pytest.raises(ValueError, match="model must be one of"):
        export_latest_surface_layers(output_dir=tmp_path, model="gefs")


def test_snowfall_total_missing_at_the_analysis_hour_is_zero_not_null():
    # RRFS has no ASNOW message at f000; later leads that are missing stay missing.
    raw = _sample_raw_dataset()
    raw["snowfall_1hr"] = raw["snowfall_1hr"].where(raw.time != raw.time[0])
    init = dt.datetime(2026, 4, 16, 0, tzinfo=dt.timezone.utc)
    assert np.isnan(prepare_surface_dataset(raw)["snowfall_1h_mm"].isel(time=0)).all()
    fixed = prepare_surface_dataset(raw, init_time=init)["snowfall_1h_mm"]
    assert (fixed.isel(time=0) == 0.0).all()
    np.testing.assert_array_equal(
        fixed.isel(time=1), prepare_surface_dataset(_sample_raw_dataset())["snowfall_1h_mm"].isel(time=1)
    )
    later = _sample_raw_dataset()
    later["snowfall_1hr"] = later["snowfall_1hr"].where(later.time != later.time[1])
    assert np.isnan(prepare_surface_dataset(later, init_time=init)["snowfall_1h_mm"].isel(time=1)).all()

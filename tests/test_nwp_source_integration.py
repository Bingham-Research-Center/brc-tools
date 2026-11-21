"""NWPSource end to end against a fake Herbie (no network): alias resolution, product
grouping, level expansion, the valid-time axis, cropping, waypoint extraction, and what
a failed download does to the result.

The fake (``tests/_nwp_fakes.py``) answers a search the way Herbie does and returns what
cfgrib returns, so ``_herbie_fetch``'s locking, cache check and retry run for real. Every
field is an analytic plane in (lat, lon, hour), so each value can be checked against the
grid point and hour it should have come from.
"""

from __future__ import annotations

import datetime as dt
import logging
import time

import numpy as np
import polars as pl
import pytest
import xarray as xr
from _nwp_fakes import (
    PRS_MESSAGES,
    SFC_MESSAGES,
    fail_when,
    field_value,
    lambert_grid,
    make_fake_herbie,
    regular_grid,
)

from brc_tools.nwp import source
from brc_tools.nwp._crop import nearest_point_value
from brc_tools.nwp.derived import WindGrid
from brc_tools.nwp.source import NWPSource, load_lookups

LU = load_lookups()
INIT = "2026-11-21 05Z"
INIT_DT = dt.datetime(2026, 11, 21, 5)
BASIN = LU["regions"]["uinta_basin"]


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    """Locks in tmp, no real cache dir, and backoff sleeps recorded instead of slept."""
    monkeypatch.setenv("BRC_TOOLS_LOCK_DIR", str(tmp_path))
    monkeypatch.delenv("BRC_TOOLS_HERBIE_CACHE", raising=False)
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", sleeps.append)
    return sleeps


def _install(monkeypatch, grid=None, **kw):
    fake = make_fake_herbie(grid if grid is not None else lambert_grid(), **kw)
    monkeypatch.setattr(source, "Herbie", fake)
    return fake


def _expected(ds, base, fxx):
    lon180 = ((ds.longitude + 180.0) % 360.0) - 180.0
    return field_value(base, fxx, ds.latitude, lon180)


# ── shape of the result ──────────────────────────────────────────────────


def test_fetch_stacks_hours_on_a_valid_time_axis(monkeypatch):
    _install(monkeypatch)
    ds = NWPSource("hrrr").fetch(INIT, [0, 1, 2], ["temp_2m", "mslp"])

    assert set(ds.data_vars) == {"temp_2m", "mslp"}
    assert ds["temp_2m"].dims == ("time", "y", "x")
    want = [np.datetime64(INIT_DT + dt.timedelta(hours=h)) for h in (0, 1, 2)]
    assert list(ds.time.values) == want
    # cfgrib's scalar coords (step, level, valid_time, Herbie's projection) are gone
    assert set(ds.coords) == {"time", "latitude", "longitude"}
    for i, fxx in enumerate((0, 1, 2)):
        hour = ds.isel(time=i)
        np.testing.assert_allclose(hour["temp_2m"], _expected(hour, SFC_MESSAGES["TMP:2 m above ground"][1], fxx))
        np.testing.assert_allclose(hour["mslp"], _expected(hour, SFC_MESSAGES["MSLMA:mean sea level"][1], fxx))


def test_alias_resolves_to_the_models_search_and_product(monkeypatch):
    fake = _install(monkeypatch)
    NWPSource("hrrr").fetch(INIT, [1], ["temp_2m", "mslp"], max_workers=1)

    assert sorted(s for _, _, s in fake.searches) == ["MSLMA:mean sea level", "TMP:2 m above ground"]
    assert {c["model"] for c in fake.calls} == {"hrrr"}
    assert {c["product"] for c in fake.calls} == {"sfc"}
    assert all(c["date"] == INIT_DT and c["member"] is None for c in fake.calls)


def test_unknown_alias_raises_before_any_download(monkeypatch):
    fake = _install(monkeypatch)
    with pytest.raises(ValueError, match="Unknown alias"):
        NWPSource("hrrr").fetch(INIT, [0], ["temp_2m", "no_such_alias"])
    assert fake.calls == []


def test_alias_the_model_cannot_serve_is_skipped(monkeypatch):
    fake = _install(monkeypatch, regular_grid())
    ds = NWPSource("gefs").fetch(INIT, [6], ["temp_2m", "precip_1hr"])  # GEFS has no 1-h bucket
    assert set(ds.data_vars) == {"temp_2m"}
    assert not [s for _, _, s in fake.searches if "APCP" in s]


def test_derived_alias_is_not_downloaded(monkeypatch):
    fake = _install(monkeypatch)
    ds = NWPSource("hrrr").fetch(INIT, [1], ["temp_2m", "wind_speed_10m"])
    assert set(ds.data_vars) == {"temp_2m"}
    assert [s for _, _, s in fake.searches] == ["TMP:2 m above ground"]


# ── products and levels ──────────────────────────────────────────────────


def test_pressure_level_alias_goes_to_its_own_product_per_level(monkeypatch):
    fake = _install(monkeypatch)
    ds = NWPSource("hrrr").fetch(INIT, [3], ["temp_2m", "temp_pl"], levels=[700, 500])

    assert set(ds.data_vars) == {"temp_2m", "temp_700", "temp_500"}
    by_search = {s: p for _, p, s in fake.searches}
    assert by_search == {"TMP:2 m above ground": "sfc", "TMP:700 mb": "prs", "TMP:500 mb": "prs"}
    hour = ds.isel(time=0)
    np.testing.assert_allclose(hour["temp_700"], _expected(hour, PRS_MESSAGES["TMP:700 mb"][1], 3))


def test_pressure_level_alias_falls_back_to_default_levels(monkeypatch):
    _install(monkeypatch)
    ds = NWPSource("hrrr").fetch(INIT, [0], ["temp_pl"])
    want = {f"temp_{lv}" for lv in LU["aliases"]["temp_pl"]["default_levels"]}
    assert set(ds.data_vars) == want


def test_product_override_routes_every_alias(monkeypatch):
    fake = _install(monkeypatch, products={"nat": SFC_MESSAGES})
    NWPSource("hrrr").fetch(INIT, [0, 1], ["temp_2m", "mslp"], product="nat")
    assert {c["product"] for c in fake.calls} == {"nat"}


def test_gefs_switches_product_above_its_breakpoint(monkeypatch):
    fake = _install(monkeypatch, regular_grid())
    NWPSource("gefs").fetch(INIT, [240, 246], ["temp_2m"], max_workers=1)
    assert {(c["fxx"], c["product"]) for c in fake.calls} == {(240, "atmos.25"), (246, "atmos.5")}


def test_member_and_cache_dir_reach_herbie(monkeypatch, tmp_path):
    fake = _install(monkeypatch, regular_grid())
    monkeypatch.setenv("BRC_TOOLS_HERBIE_CACHE", str(tmp_path / "herbie"))
    NWPSource("gefs", member="p05").fetch(INIT, [6], ["temp_2m"])
    (call,) = fake.calls
    assert call["model"] == "gefs" and call["member"] == "p05"
    assert call["save_dir"] == str(tmp_path / "herbie")


@pytest.mark.parametrize("init", [INIT, "2026112105", "2026-11-21 05:00", INIT_DT,
                                  INIT_DT.replace(tzinfo=dt.timezone.utc)])
def test_every_init_format_reaches_herbie_as_naive_utc(monkeypatch, init):
    fake = _install(monkeypatch)
    NWPSource("hrrr").fetch(init, [0], ["temp_2m"])
    assert fake.calls[0]["date"] == INIT_DT and fake.calls[0]["date"].tzinfo is None


# ── space: cropping and waypoints ────────────────────────────────────────


def _in_bbox(lat, lon180, sw, ne):
    return (lat >= sw[0]) & (lat <= ne[0]) & (lon180 >= sw[1]) & (lon180 <= ne[1])


def test_region_crop_keeps_every_inside_point_and_no_spare_rows(monkeypatch):
    grid = lambert_grid()
    _install(monkeypatch, grid)
    ds = NWPSource("hrrr").fetch(INIT, [0], ["temp_2m"], region="uinta_basin")

    full_lat, full_lon = grid.lonlat_2d()
    lat = ds.latitude.values
    lon = ((ds.longitude.values + 180.0) % 360.0) - 180.0
    inside = _in_bbox(lat, lon, BASIN["sw"], BASIN["ne"])
    assert ds.sizes["y"] < grid.lat.shape[0] and ds.sizes["x"] < grid.lat.shape[1]
    assert inside.sum() == _in_bbox(full_lat, full_lon, BASIN["sw"], BASIN["ne"]).sum()
    # the crop is the smallest index box: each edge row/column holds an inside point
    assert inside[0].any() and inside[-1].any() and inside[:, 0].any() and inside[:, -1].any()


def _nearest_value(ds_t, var, lat, lon):
    """Brute-force nearest grid point in (lat, lon) degrees, NWPSource's metric."""
    lon_q = lon % 360.0 if float(ds_t.longitude.max()) > 180.0 else lon
    d2 = (ds_t.latitude.values - lat) ** 2 + (ds_t.longitude.values - lon_q) ** 2
    yi, xi = np.unravel_index(np.argmin(d2), d2.shape)
    return float(ds_t[var].values[yi, xi]), float(np.sqrt(d2.min()))


def test_extract_at_waypoints_reads_each_waypoints_nearest_point(monkeypatch):
    _install(monkeypatch)
    src = NWPSource("hrrr")
    ds = src.fetch(INIT, [0, 3], ["temp_2m", "mslp"], region="uinta_basin")
    df = src.extract_at_waypoints(ds, group="basin_full")

    group = LU["waypoint_groups"]["basin_full"]
    assert df.height == len(group) * 2
    assert df.schema["valid_time"] == pl.Datetime("us")
    assert set(df["waypoint"]) == set(group)
    for row in df.iter_rows(named=True):
        wp = LU["waypoints"][row["waypoint"]]
        ds_t = ds.sel(time=np.datetime64(row["valid_time"]))
        for var in ("temp_2m", "mslp"):
            want, dist = _nearest_value(ds_t, var, wp["lat"], wp["lon"])
            assert row[var] == pytest.approx(want), (row["waypoint"], var)
            assert dist < 0.06  # within one fake-grid spacing


def test_nearest_point_tree_is_not_reused_across_grids():
    """Regression: the KD-tree cache was keyed by id() of a temporary, so a second grid
    in the same process silently read the first grid's tree (and the wrong point)."""

    def plane(lat0, n):
        lat = np.linspace(lat0, lat0 + 1.0, n)
        lon = np.linspace(-110.0, -109.0, n)
        lon2d, lat2d = np.meshgrid(lon, lat)
        return xr.Dataset({"v": (("y", "x"), lat2d * 100 + lon2d)},
                          coords={"latitude": (("y", "x"), lat2d), "longitude": (("y", "x"), lon2d)})

    a, b = plane(40.0, 11), plane(39.0, 21)
    pa = nearest_point_value(a, 40.5, -109.5)
    pb = nearest_point_value(b, 39.25, -109.25)
    pa2 = nearest_point_value(a, 40.5, -109.5)
    assert (float(pa.latitude), float(pa.longitude)) == pytest.approx((40.5, -109.5))
    assert (float(pb.latitude), float(pb.longitude)) == pytest.approx((39.25, -109.25))
    assert float(pa2.v) == float(pa.v)


def test_two_regions_in_one_process_each_extract_correctly(monkeypatch):
    _install(monkeypatch)
    src = NWPSource("hrrr")
    for region in ("uinta_basin", "uinta_basin_wide", "uinta_basin"):
        ds = src.fetch(INIT, [0], ["temp_2m"], region=region)
        df = src.extract_at_waypoints(ds, waypoints=["vernal", "duchesne"])
        for row in df.iter_rows(named=True):
            wp = LU["waypoints"][row["waypoint"]]
            want, _ = _nearest_value(ds.isel(time=0), "temp_2m", wp["lat"], wp["lon"])
            assert row["temp_2m"] == pytest.approx(want), (region, row["waypoint"])


def test_extract_keeps_datetimes_from_a_nanosecond_time_axis(monkeypatch):
    _install(monkeypatch)
    src = NWPSource("hrrr")
    ds = src.fetch(INIT, [0, 1], ["temp_2m"], region="uinta_basin")
    ds = ds.assign_coords(time=ds.time.values.astype("datetime64[ns]"))
    df = src.extract_at_waypoints(ds, waypoints=["vernal"])
    assert df.schema["valid_time"] == pl.Datetime("us")
    assert df["valid_time"].to_list() == [INIT_DT, INIT_DT + dt.timedelta(hours=1)]


def test_gefs_regular_grid_crops_to_minus180_and_extracts(monkeypatch):
    _install(monkeypatch, regular_grid())
    src = NWPSource("gefs")
    ds = src.fetch(INIT, [6], ["temp_2m"], region="uinta_basin")

    lon = ds.longitude.values
    assert lon.min() >= BASIN["sw"][1] and lon.max() <= BASIN["ne"][1]
    assert ds.latitude.min() >= BASIN["sw"][0] and ds.latitude.max() <= BASIN["ne"][0]
    df = src.extract_at_waypoints(ds, group="basin_full")
    for row in df.iter_rows(named=True):
        wp = LU["waypoints"][row["waypoint"]]
        lat = float(ds.latitude.sel(latitude=wp["lat"], method="nearest"))
        lon_n = float(ds.longitude.sel(longitude=wp["lon"], method="nearest"))
        want = field_value(SFC_MESSAGES["TMP:2 m above ground"][1], 6, lat, lon_n)
        assert row["temp_2m"] == pytest.approx(float(want))


def test_grid_definition_from_the_grib_lands_on_attrs(monkeypatch):
    _install(monkeypatch)
    grid = WindGrid.from_attrs(NWPSource("hrrr").fetch(INIT, [0], ["wind_u_10m", "wind_v_10m"]).attrs)
    assert grid == WindGrid("lambert", True, 262.5, 38.5, 38.5)

    _install(monkeypatch, regular_grid())
    grid = WindGrid.from_attrs(NWPSource("gefs").fetch(INIT, [6], ["wind_u_10m"]).attrs)
    assert grid.grid_type == "regular_ll" and grid.uv_relative_to_grid is False


# ── failures ─────────────────────────────────────────────────────────────


def test_transient_failure_is_retried_with_backoff(monkeypatch, _isolated):
    fake = _install(monkeypatch)
    fake.fail = [fail_when(contains="MSLMA", times=1)]
    ds = NWPSource("hrrr").fetch(INIT, [1], ["temp_2m", "mslp"], max_workers=1)

    assert set(ds.data_vars) == {"temp_2m", "mslp"}
    assert [s for _, _, s in fake.searches].count("MSLMA:mean sea level") == 2
    assert _isolated == [LU["defaults"]["download_backoff_secs"]]


@pytest.mark.parametrize("workers", [1, 6])
def test_variable_that_never_arrives_is_left_out_not_fatal(monkeypatch, caplog, workers):
    """Serial and parallel fetches treat a dead message the same way."""
    fake = _install(monkeypatch)
    fake.fail = [fail_when(contains="MSLMA")]
    with caplog.at_level(logging.WARNING, logger="brc_tools.nwp.source"):
        ds = NWPSource("hrrr").fetch(INIT, [0, 1], ["temp_2m", "mslp"], max_workers=workers)

    assert set(ds.data_vars) == {"temp_2m"} and ds.sizes["time"] == 2
    retries = LU["defaults"]["download_retries"]
    assert [s for _, _, s in fake.searches].count("MSLMA:mean sea level") == 2 * retries
    assert sum("Fetch failed" in r.getMessage() for r in caplog.records) == 2


def test_variable_missing_at_one_hour_is_nan_there_only(monkeypatch):
    fake = _install(monkeypatch)
    fake.fail = [fail_when(fxx=1, contains="MSLMA")]
    ds = NWPSource("hrrr").fetch(INIT, [0, 1, 2], ["temp_2m", "mslp"])
    assert np.isnan(ds["mslp"].isel(time=1)).all()
    assert np.isfinite(ds["mslp"].isel(time=[0, 2])).all()
    assert np.isfinite(ds["temp_2m"]).all()


def test_hour_where_nothing_arrived_is_missing_from_time(monkeypatch):
    fake = _install(monkeypatch)
    fake.fail = [fail_when(fxx=2)]
    ds = NWPSource("hrrr").fetch(INIT, [0, 1, 2], ["temp_2m", "mslp"])
    assert list(ds.time.values) == [np.datetime64(INIT_DT + dt.timedelta(hours=h)) for h in (0, 1)]


@pytest.mark.parametrize("workers", [1, 6])
def test_nothing_at_all_raises(monkeypatch, workers):
    fake = _install(monkeypatch)
    fake.fail = [fail_when()]
    with pytest.raises(RuntimeError, match="No data returned"):
        NWPSource("hrrr").fetch(INIT, [0, 1], ["temp_2m"], max_workers=workers)


def test_corrupt_cached_grib_is_purged_before_it_is_read(monkeypatch, tmp_path):
    fake = _install(monkeypatch)
    bad = tmp_path / "hrrr.t05z.wrfsfcf00.grib2"
    bad.write_bytes(b"HTML" + b"\0" * 5000)  # an error page saved as GRIB
    fake.grib_path = bad
    ds = NWPSource("hrrr").fetch(INIT, [0], ["temp_2m"])
    assert not bad.exists()
    assert "temp_2m" in ds


def test_waypoint_payload_hours_follow_the_dataset(monkeypatch, caplog):
    """A dropped hour must not leave forecast_hours one step out of line with the data."""
    from brc_tools.nwp.waypoint_forecast import build_waypoint_payload

    fake = _install(monkeypatch)
    fake.fail = [fail_when(fxx=2)]
    ds = NWPSource("hrrr").fetch(INIT, [0, 1, 2, 3], ["temp_2m"], region="uinta_basin")
    with caplog.at_level(logging.WARNING, logger="brc_tools.nwp.waypoint_forecast"):
        payload = build_waypoint_payload(ds, group="basin_full", init_time=INIT_DT,
                                         forecast_hours=[0, 1, 2, 3])

    assert payload["forecast_hours"] == [0, 1, 3]
    assert payload["valid_times"] == ["2026-11-21T05:00:00Z", "2026-11-21T06:00:00Z",
                                      "2026-11-21T08:00:00Z"]
    for station in payload["stations"]:
        assert len(station["forecasts"]["temp_2m_c"]) == 3
    assert any("[2]" in r.getMessage() for r in caplog.records)

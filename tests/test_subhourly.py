"""Sub-hourly products through NWPSource (GH #82): a ``subh`` fetch keeps each message's
own valid time, so HRRR f00-f02 come back as 0, 15, ..., 120 min instead of one stamp
per hour, and the aviation crosswind payload is built on that path.

The fake Herbie writes ``subh`` the way the live feeds do (tests/_nwp_fakes.py): HRRR
labels steps in minutes and ships a 5-min-average twin of 10 m wind whose value carries
a decoy offset, so reading the average instead of the instant shows up as +1000.
"""

from __future__ import annotations

import datetime as dt
import logging
import time

import numpy as np
import pytest
from _nwp_fakes import (
    AVERAGE_DECOY,
    SFC_MESSAGES,
    field_value,
    lambert_grid,
    make_fake_herbie,
)

from brc_tools.nwp import source
from brc_tools.nwp._normalise import normalize_coords, steps_to_time
from brc_tools.nwp.aviation import build_airport_crosswind_payload, fetch_airport_winds
from brc_tools.nwp.source import NWPSource, load_lookups

LU = load_lookups()
INIT = dt.datetime(2026, 11, 20, 13)
HRRR_F00_F02 = [0, 15, 30, 45, 60, 75, 90, 105, 120]


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("BRC_TOOLS_LOCK_DIR", str(tmp_path))
    monkeypatch.delenv("BRC_TOOLS_HERBIE_CACHE", raising=False)
    monkeypatch.setattr(time, "sleep", lambda s: None)


def _install(monkeypatch, style="hrrr"):
    fake = make_fake_herbie(lambert_grid(), subh_style=style)
    monkeypatch.setattr(source, "Herbie", fake)
    return fake


def _minutes(ds):
    return [int(m) for m in (ds.time.values - np.datetime64(INIT)) / np.timedelta64(1, "m")]


def _expected(ds_t, key, minutes):
    lon180 = ((ds_t.longitude + 180.0) % 360.0) - 180.0
    return field_value(SFC_MESSAGES[key][1], minutes / 60.0, ds_t.latitude, lon180)


def test_hrrr_subh_keeps_the_15_minute_axis(monkeypatch):
    _install(monkeypatch)
    ds = NWPSource("hrrr").fetch(INIT, [0, 1, 2], ["temp_2m", "wind_gust_10m"], product="subh")

    assert _minutes(ds) == HRRR_F00_F02
    assert ds.time.dtype == np.dtype("datetime64[us]")  # as the hourly path stamps it
    assert set(ds.coords) == {"time", "latitude", "longitude"}
    for i, m in enumerate(HRRR_F00_F02):
        t = ds.isel(time=i)
        np.testing.assert_allclose(t["temp_2m"], _expected(t, "TMP:2 m above ground", m))
        np.testing.assert_allclose(t["wind_gust_10m"], _expected(t, "GUST:surface", m))


def test_hrrr_subh_reads_the_instantaneous_wind_not_its_5_min_average(monkeypatch):
    fake = _install(monkeypatch)
    ds = NWPSource("hrrr").fetch(INIT, [0, 1, 2], ["wind_u_10m", "wind_v_10m"], product="subh")

    assert _minutes(ds) == HRRR_F00_F02
    for i, m in enumerate(HRRR_F00_F02):
        t = ds.isel(time=i)
        np.testing.assert_allclose(t["wind_u_10m"], _expected(t, "UGRD:10 m above ground", m))
    pinned = LU["aliases"]["wind_u_10m"]["search_by_product"]["hrrr"]["subh"]
    assert {s for _, p, s in fake.searches if "UGRD" in s} == {pinned}
    assert float(ds["wind_v_10m"].max()) < AVERAGE_DECOY / 2


def test_the_hourly_product_keeps_the_plain_search(monkeypatch):
    fake = _install(monkeypatch)
    ds = NWPSource("hrrr").fetch(INIT, [0, 1], ["wind_u_10m"])
    assert {s for _, _, s in fake.searches} == {"UGRD:10 m above ground"}
    assert _minutes(ds) == [0, 60]


def test_rrfs_subh_reads_whole_hours_and_has_no_f000(monkeypatch, caplog):
    _install(monkeypatch, style="rrfs")
    with caplog.at_level(logging.WARNING, logger="brc_tools.nwp.source"):
        ds = NWPSource("rrfs").fetch(INIT, [0, 1, 2], ["temp_2m", "wind_u_10m"], product="subh")
    assert _minutes(ds) == HRRR_F00_F02[1:]
    t = ds.sel(time=np.datetime64(INIT + dt.timedelta(hours=1)))
    np.testing.assert_allclose(t["wind_u_10m"], _expected(t, "UGRD:10 m above ground", 60))
    assert any("f000" in r.getMessage() for r in caplog.records)


def test_a_subh_search_that_matches_two_kinds_of_message_says_so(monkeypatch, caplog):
    """Without the instantaneous pin, cfgrib hands back two hypercubes (instant and
    5-min average); that must read as a registry problem, not an AttributeError."""
    _install(monkeypatch)
    monkeypatch.delitem(LU["aliases"]["wind_u_10m"], "search_by_product")
    with caplog.at_level(logging.WARNING, logger="brc_tools.nwp.source"):
        ds = NWPSource("hrrr").fetch(INIT, [1], ["temp_2m", "wind_u_10m"], product="subh")
    assert set(ds.data_vars) == {"temp_2m"}
    assert any("cannot be stacked" in r.getMessage() for r in caplog.records)


def test_steps_to_time_handles_a_lone_message_and_a_step_stack(monkeypatch):
    fake = _install(monkeypatch)
    lone = fake(INIT, model="hrrr", product="subh", fxx=0).xarray("TMP:2 m above ground")
    stack = fake(INIT, model="hrrr", product="subh", fxx=1).xarray("TMP:2 m above ground")
    a, b = steps_to_time(lone), steps_to_time(stack)
    assert a.sizes["time"] == 1 and b.sizes["time"] == 4
    assert "step" not in b.coords and "valid_time" not in b.coords
    kept = normalize_coords(b, INIT, 1)  # must not restamp init + fxx over the axis
    assert _minutes(kept) == [15, 30, 45, 60]


# ── aviation on the shared path ──────────────────────────────────────────


def test_airport_winds_come_back_on_15_minutes_and_earth_relative(monkeypatch):
    _install(monkeypatch)
    ds = fetch_airport_winds(init_time=INIT, forecast_hours=[0, 1, 2])
    assert _minutes(ds) == HRRR_F00_F02
    assert ds["wind_u_10m"].attrs["wind_frame"] == ds["wind_v_10m"].attrs["wind_frame"] == "earth"

    payload = build_airport_crosswind_payload(ds, airport="KVEL", init_time=INIT)
    assert payload["forecast_minutes"] == HRRR_F00_F02
    assert payload["valid_times"][0] == "2026-11-20T13:00:00Z"
    assert payload["valid_times"][-1] == "2026-11-20T15:00:00Z"
    for name, values in payload["series"].items():
        assert len(values) == len(HRRR_F00_F02), name
        assert all(v is not None for v in values), name
    assert max(payload["series"]["wind_speed_kt"]) < AVERAGE_DECOY / 2  # the instant wind

"""NRCS AWDB REST client, offline against recorded responses (12 Nov 2026)."""

import json
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from brc_tools.hydro import awdb

FIX = Path(__file__).parent / "fixtures" / "hydro"


def _fetcher(files):
    calls = []

    def fetch(url, params=None):
        calls.append((url, params))
        return json.loads(Path(files[len(calls) - 1]).read_text()), {"url": url}

    fetch.calls = calls
    return fetch


def test_stations_and_element_depths(tmp_path):
    fetch = _fetcher([FIX / "awdb_stations_ut_sntl.json"])
    st = awdb.stations(states=("UT",), networks=("SNTL",), cache_dir=tmp_path, fetch=fetch)
    p = fetch.calls[0][1]
    assert p["stationTriplets"] == "*:UT:SNTL" and p["returnStationElements"] == "true"
    assert p["elements"].startswith("WTEQ:*:*,SNWD:*:*") and p["durations"] == "DAILY"
    k = st.filter(pl.col("shef_id") == "KGCU1")
    assert k["triplet"][0] == "559:UT:SNTL" and k["data_time_zone"][0] == -8.0
    assert k["elevation_m"][0] == pytest.approx(8740 * 0.3048)
    el = awdb.station_elements(st)
    sto = el.filter(pl.col("element") == "STO").sort("depth_cm")
    assert sto["height_depth_in"].to_list() == [-2.0, -8.0, -20.0]
    assert sto["depth_cm"].to_list() == [5.08, 20.32, 50.8]
    assert el.filter(pl.col("element") == "WTEQ")["depth_cm"][0] is None
    # bbox filter is local; this station is at 40.716 N 109.544 W
    assert awdb.stations(states=("UT",), networks=("SNTL",), bbox=(-109.6, 40.7, -109.5, 40.8), cache_dir=tmp_path, fetch=_fetcher([])).height == 1
    assert awdb.stations(states=("UT",), networks=("SNTL",), bbox=(-111.0, 39.0, -110.0, 40.0), cache_dir=tmp_path, fetch=_fetcher([])).height == 0


def test_daily_values_units_flags_and_cache(tmp_path):
    fetch = _fetcher([FIX / "awdb_data_559.json"])
    df = awdb.daily("559:UT:SNTL", begin=date(2015, 4, 1), end="2015-04-03", cache_dir=tmp_path, fetch=fetch)
    p = fetch.calls[0][1]
    assert p["duration"] == "DAILY" and p["returnFlags"] == "true" and p["elements"].count(":*:*") == 6
    assert df["date"].dtype == pl.Date
    sms2 = df.filter((pl.col("element") == "SMS") & (pl.col("height_depth_in") == -2)).sort("date")
    assert sms2["value"].to_list() == [25.1, 24.8, 25.0] and sms2["unit_si"][0] == "%" and sms2["depth_cm"][0] == 5.08
    sto2 = df.filter((pl.col("element") == "STO") & (pl.col("height_depth_in") == -2)).sort("date")
    assert sto2["value"][0] == 38.0 and sto2["value_si"][0] == pytest.approx((38 - 32) * 5 / 9) and sto2["unit_si"][0] == "degC"
    prec = df.filter(pl.col("element") == "PREC").sort("date")
    assert prec["value_si"][0] == pytest.approx(5.3 * 25.4) and prec["unit_si"][0] == "mm" and prec["qc_flag"][0] == "E"
    snwd = df.filter(pl.col("element") == "SNWD").sort("date")
    assert snwd["value_si"][1] == pytest.approx(3 * 2.54) and snwd["unit_si"][1] == "cm"
    fetch2 = _fetcher([])
    df2 = awdb.daily("559:UT:SNTL", begin="2015-04-01", end="2015-04-03", cache_dir=tmp_path, fetch=fetch2)
    assert fetch2.calls == [] and df2.equals(df)

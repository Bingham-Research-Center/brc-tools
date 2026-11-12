"""USGS Water Data OGC API client, offline against recorded pages (12 Nov 2026)."""

import json
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from brc_tools.hydro import nwis

FIX = Path(__file__).parent / "fixtures" / "hydro"


def _fetcher(pages):
    calls = []

    def fetch(url, params=None):
        calls.append((url, params))
        return json.loads(Path(pages[len(calls) - 1]).read_text()), {"url": url}

    fetch.calls = calls
    return fetch


def test_daily_pages_cache_and_units(tmp_path):
    fetch = _fetcher([FIX / "nwis_daily_page1.json", FIX / "nwis_daily_page2.json"])
    df = nwis.daily("09266500", start=date(2014, 10, 1), end="2014-10-10", cache_dir=tmp_path, fetch=fetch)
    assert len(fetch.calls) == 2                       # followed one `next` link, stopped without one
    assert fetch.calls[0][1]["monitoring_location_id"] == "USGS-09266500"
    assert fetch.calls[1][1] is None and "cursor=" in fetch.calls[1][0]
    assert df.height == 5 and df["site_id"][0] == "USGS-09266500"
    assert df["time"].dtype == pl.Date and df["time"][0] == date(2014, 10, 1)
    assert df["value"][0] == 178.0 and df["value_m3s"][0] == pytest.approx(178 * 0.028316846592)
    assert df["unit"][0] == "ft^3/s" and df["approval_status"][0] == "Approved"
    raw = sorted(p for p in (tmp_path / "nwis" / "daily").glob("*.page*.json") if not p.name.endswith(".meta.json"))
    assert len(raw) == 2 and all(p.with_suffix(".json.meta.json").exists() for p in raw)
    # second call: no network, parquet reused
    fetch2 = _fetcher([])
    df2 = nwis.daily("USGS-09266500", start="2014-10-01", end="2014-10-10", cache_dir=tmp_path, fetch=fetch2)
    assert fetch2.calls == [] and df2.equals(df)


def test_monitoring_locations_parse(tmp_path):
    fetch = _fetcher([FIX / "nwis_monitoring_locations.json"])
    df = nwis.monitoring_locations((-110.0, 40.3, -109.4, 40.6), cache_dir=tmp_path, fetch=fetch)
    assert len(fetch.calls) == 1 and fetch.calls[0][1]["site_type_code"] == "ST"
    bb = df.filter(pl.col("site_no") == "09261700")
    assert bb["name"][0].startswith("BIG BRUSH")
    assert bb["altitude_m"][0] == pytest.approx(5627.26 * 0.3048)
    assert bb["drainage_km2"][0] == pytest.approx(77.2 * 2.589988110336)
    assert bb["huc"][0] == "140600100205" and bb["lat"][0] == pytest.approx(40.5, abs=0.5)


def test_water_year_summary_triangle():
    days = pl.date_range(date(2015, 4, 1), date(2015, 7, 31), eager=True)
    n = len(days)
    # symmetric triangle peaking mid-window: centroid at the peak
    q = [min(i, n - 1 - i) + 1.0 for i in range(n)]
    df = pl.DataFrame({"site_id": ["USGS-1"] * n, "time": days, "value_m3s": q})
    s = nwis.water_year_summary(df)
    assert s.height == 1 and s["water_year"][0] == 2015 and s["complete"][0]
    assert s["vol_m3"][0] == pytest.approx(sum(q) * 86400)
    assert abs((s["centroid_date"][0] - s["peak_date"][0]).days) <= 1
    short = nwis.water_year_summary(df.head(10))
    assert not short["complete"][0]

"""Coverage index and request planning over a canonical archive, offline."""

from datetime import datetime, timezone

import polars as pl

from brc_tools.obs.archive import atomic, digest, encode, preserve
from brc_tools.obs.coverage import (build_index, coverage_report, covered, plan_requests,
                                    station_daily_counts, water_year_blocks)


def _payload(stid, times, sensors, flags=None):
    obs = {"date_time": times}
    obs.update(sensors)
    return {
        "SUMMARY": {"RESPONSE_CODE": 1},
        "UNITS": {"soil_temp": "Celsius", "snow_water_equiv": "Millimeters"},
        "STATION": [{"STID": stid, "MNET_ID": "25", "ELEVATION": "8000", "TIMEZONE": "America/Denver",
                     "SENSOR_VARIABLES": {"soil_temp": {"soil_temp_set_1": {}}, "snow_water_equiv": {"snow_water_equiv_set_1": {}}},
                     "OBSERVATIONS": obs, "QC": flags or {}}],
    }


def _archive_request(root, payload, params):
    path = preserve(root, payload, "timeseries", params, {"SynopticPy": "test"})
    key = digest(encode(dict(service="timeseries", params=params, version=1)))
    atomic(root / "requests" / f"{key}.json", encode({"receipt": str(path.relative_to(root))}))
    return key


def _params(stid, start, end, vars_):
    return dict(stid=[stid], vars=sorted(vars_), start=start, end=end, qc="on", qc_flags="on",
                qc_remove_data="off", showemptystations=1)


def test_daily_counts_and_flags():
    times = ["2015-03-31T23:00:00Z", "2015-04-01T00:00:00Z", "2015-04-01T01:00:00Z", "2015-04-01T02:00:00Z"]
    p = _payload("KGCU1", times, {"soil_temp_set_1": [0.1, None, 0.3, 0.4], "snow_water_equiv_set_1": [100, 99, 98, 97]},
                 flags={"soil_temp_set_1": [None, None, ["sl_range_check"], None]})
    c = station_daily_counts(p["STATION"][0]).sort("sensor", "day")
    st = c.filter(pl.col("variable") == "soil_temp")
    assert st["day"].to_list() == [datetime(2015, 3, 31).date(), datetime(2015, 4, 1).date()]
    assert st["n_obs"].to_list() == [1, 2] and st["n_flagged"].to_list() == [0, 1]
    assert c.filter(pl.col("variable") == "snow_water_equiv")["n_obs"].sum() == 4


def test_build_index_is_incremental_and_plan_skips_covered(tmp_path):
    root = tmp_path / "arch"
    times = [f"2015-04-0{d}T12:00:00Z" for d in (1, 2, 3)]
    vars_ = ["snow_water_equiv", "soil_temp"]
    # a five-water-year block request for KGCU1 (WY2011-2015)
    k1 = _archive_request(root, _payload("KGCU1", times, {"soil_temp_set_1": [1, 2, 3], "snow_water_equiv_set_1": [5, 4, 3]}),
                          _params("KGCU1", "2010-10-01T00:00:00+00:00", "2015-10-01T00:00:00+00:00", vars_))
    # a pseudoprofile-style one-day request for two stations
    _archive_request(root, _payload("MMTU1", times[:1], {"soil_temp_set_1": [7]}),
                     dict(stid=["MMTU1", "KGCU1"], vars=vars_, start="2026-10-24T00:00:00+00:00", end="2026-10-25T00:00:00+00:00"))
    index, windows = build_index(root)
    assert windows.height == 3 and index.height == 7  # 2 sensors x 3 days + 1
    assert set(windows["stid"]) == {"KGCU1", "MMTU1"}
    # second pass: nothing new, same tables
    index2, windows2 = build_index(root)
    assert index2.height == index.height and windows2.height == windows.height
    assert (root / "coverage" / "seen.json").exists()
    now = datetime(2026, 11, 12, tzinfo=timezone.utc)
    a, b = datetime(2010, 10, 1, tzinfo=timezone.utc), datetime(2015, 10, 1, tzinfo=timezone.utc)
    assert covered(windows, "KGCU1", a, b, vars_)
    assert not covered(windows, "KGCU1", a, b, vars_ + ["air_temp"])  # more variables than asked
    assert not covered(windows, "KGCU1", datetime(2015, 10, 1, tzinfo=timezone.utc), datetime(2020, 10, 1, tzinfo=timezone.utc), vars_)
    # a one-day window never covers a five-year block
    assert not covered(windows, "MMTU1", datetime(2025, 10, 1, tzinfo=timezone.utc), now, vars_)
    stations = [dict(stid="KGCU1", por_start="2000-01-20", por_end=None),
                dict(stid="MMTU1", por_start="2013-05-01", por_end="2026-09-15")]
    plan = plan_requests(stations, 2001, 2026, vars_for={"KGCU1": vars_, "MMTU1": vars_}, windows=windows, now=now)
    blocks = {(r["stid"], r["block"]) for r in plan}
    assert ("KGCU1", "WY2011-2015") not in blocks          # covered
    assert ("KGCU1", "WY2001-2005") in blocks and ("KGCU1", "WY2026-2026") in blocks
    assert ("MMTU1", "WY2001-2005") not in blocks           # before its record
    mm = [r for r in plan if r["stid"] == "MMTU1" and r["block"] == "WY2011-2015"][0]
    assert mm["params"]["start"].startswith("2013-05-01")  # clipped to POR
    assert mm["params"]["qc_remove_data"] == "off" and mm["params"]["stid"] == ["MMTU1"]
    assert all(r["station_hours"] <= 5 * 366 * 24 for r in plan)
    rep = coverage_report(index, ["KGCU1", "MMTU1"], vars_, start_wy=2015, end_wy=2016)
    assert rep.height == 2 * 2 * 2
    row = rep.filter((pl.col("stid") == "KGCU1") & (pl.col("variable") == "soil_temp") & (pl.col("water_year") == 2015))
    assert row["days_with_obs"][0] == 3 and row["days_in_year"][0] == 365


def test_water_year_blocks():
    now = datetime(2026, 11, 12, tzinfo=timezone.utc)
    blocks = water_year_blocks(2001, 2026, 5, now=now)
    assert [b[2] for b in blocks] == ["WY2001-2005", "WY2006-2010", "WY2011-2015", "WY2016-2020", "WY2021-2025", "WY2026-2026"]
    assert blocks[0][0] == datetime(2000, 10, 1, tzinfo=timezone.utc) and blocks[0][1] == datetime(2005, 10, 1, tzinfo=timezone.utc)
    assert blocks[-1][1] == datetime(2026, 10, 1, tzinfo=timezone.utc)   # WY2026 is complete
    # the water year in progress ends at `now`
    assert water_year_blocks(2001, 2027, 5, now=now)[-1] == (datetime(2025, 10, 1, tzinfo=timezone.utc), now, "WY2026-2027")

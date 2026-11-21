"""Daily aggregation from archived payloads: statistics, QC policy, day basis, SI units,
and de-duplication of overlapping request windows."""

from datetime import date

import polars as pl
import pytest

from brc_tools.obs.archive import atomic, digest, encode, preserve
from brc_tools.obs.daily import QC_POLICY, build_daily, depth_of, station_daily


def _payload(stid, times, sensors, flags=None, sensor_vars=None):
    obs = {"date_time": times}
    obs.update(sensors)
    return {
        "SUMMARY": {"RESPONSE_CODE": 1},
        "UNITS": {"soil_temp": "Celsius", "soil_moisture": "%", "snow_water_equiv": "Millimeters", "odd_var": "furlongs"},
        "STATION": [{"STID": stid, "MNET_ID": "25", "ELEVATION": "8000", "TIMEZONE": "America/Denver",
                     "SENSOR_VARIABLES": sensor_vars or {}, "OBSERVATIONS": obs, "QC": flags or {}}],
    }


def test_station_daily_statistics_policy_and_units():
    times = ["2015-04-01T00:00:00Z", "2015-04-01T06:00:00Z", "2015-04-01T12:00:00Z", "2015-04-02T00:00:00Z"]
    p = _payload("KGCU1", times,
                 {"soil_temp_set_1": [1.0, 3.0, 50.0, 2.0], "soil_moisture_set_1": [20.0, 22.0, None, 24.0], "odd_var_set_1": [1, 1, 1, 1]},
                 flags={"soil_temp_set_1": [None, None, ["sl_range_check"], None]})
    d = station_daily(p["STATION"][0], p["UNITS"], day_basis="utc").sort("sensor", "day")
    st = d.filter(pl.col("variable") == "soil_temp")
    d1 = st.filter(pl.col("day") == date(2015, 4, 1))
    assert d1["n_obs"][0] == 3 and d1["n_flagged"][0] == 1 and d1["n_used"][0] == 2
    assert d1["mean"][0] == 2.0 and d1["min"][0] == 1.0 and d1["max"][0] == 3.0   # 50.0 was flagged and dropped
    assert d1["unit"][0] == "Celsius" and d1["unit_si"][0] == "degC" and d1["mean_si"][0] == 2.0
    assert d1["qc_policy"][0] == QC_POLICY
    sm = d.filter(pl.col("variable") == "soil_moisture").filter(pl.col("day") == date(2015, 4, 1))
    assert sm["n_obs"][0] == 2 and sm["mean"][0] == 21.0 and sm["unit_si"][0] == "%"
    odd = d.filter(pl.col("variable") == "odd_var")
    assert odd["unit"][0] == "furlongs" and odd["unit_si"][0] is None and odd["mean_si"][0] is None
    assert d["first_time"].dtype == pl.Datetime("us", "UTC")


def test_mst_day_basis_moves_evening_utc_values_back_a_day():
    times = ["2015-04-01T03:00:00Z", "2015-04-01T18:00:00Z"]   # 20:00 MST on 31 Mar; 11:00 MST on 1 Apr
    p = _payload("KGCU1", times, {"soil_temp_set_1": [1.0, 3.0]})
    utc = station_daily(p["STATION"][0], p["UNITS"], day_basis="utc")
    mst = station_daily(p["STATION"][0], p["UNITS"], day_basis="mst")
    assert utc["day"].to_list() == [date(2015, 4, 1)] and utc["mean"][0] == 2.0
    assert sorted(mst["day"].to_list()) == [date(2015, 3, 31), date(2015, 4, 1)]
    assert set(mst["day_basis"]) == {"mst"}
    with pytest.raises(ValueError):
        station_daily(p["STATION"][0], p["UNITS"], day_basis="mdt")


def test_depth_from_metadata_or_none():
    assert depth_of("soil_temp", "soil_temp_set_1", {"position": "-0.2"}) == 20.0
    assert depth_of("soil_temp", "soil_temp_set_1", {}) is None
    assert depth_of("air_temp", "air_temp_set_1", {"position": "2"}) is None


def _archive_request(root, payload, params):
    path = preserve(root, payload, "timeseries", params, {"SynopticPy": "test"})
    key = digest(encode(dict(service="timeseries", params=params, version=1)))
    atomic(root / "requests" / f"{key}.json", encode({"receipt": str(path.relative_to(root))}))


def test_build_daily_dedupes_overlap_and_is_resumable(tmp_path):
    root, out = tmp_path / "arch", tmp_path / "daily"
    vars_ = ["soil_temp"]
    # earlier request: two days
    _archive_request(root, _payload("KGCU1", ["2015-04-01T12:00:00Z", "2015-04-02T12:00:00Z"], {"soil_temp_set_1": [1.0, 2.0]}),
                     dict(stid=["KGCU1"], vars=vars_, start="2015-04-01T00:00:00+00:00", end="2015-04-03T00:00:00+00:00"))
    # later request overlapping day 2 with a revised value, plus day 3
    _archive_request(root, _payload("KGCU1", ["2015-04-02T12:00:00Z", "2015-04-03T12:00:00Z"], {"soil_temp_set_1": [9.0, 3.0]}),
                     dict(stid=["KGCU1"], vars=vars_, start="2015-04-02T00:00:00+00:00", end="2015-04-04T00:00:00+00:00"))
    manifest = build_daily(root, out, day_basis="utc", log=lambda *_: None)
    frame = pl.read_parquet(out / "utc" / "KGCU1.parquet").sort("day")
    assert frame["day"].to_list() == [date(2015, 4, 1), date(2015, 4, 2), date(2015, 4, 3)]
    assert frame["mean"].to_list() == [1.0, 9.0, 3.0]   # the later request wins on the overlap
    assert manifest["bases"]["utc"]["KGCU1"]["rows"] == 3
    parts = sorted((out / "utc" / "parts").glob("*.parquet"))
    assert len(parts) == 2
    mtimes = [p.stat().st_mtime_ns for p in parts]
    build_daily(root, out, day_basis="utc", log=lambda *_: None)   # resumable: parts untouched
    assert [p.stat().st_mtime_ns for p in parts] == mtimes

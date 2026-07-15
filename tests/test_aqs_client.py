"""Offline tests for brc_tools.api.aqs (no network).

Loading/filtering runs against synthetic AirData CSVs built in tmp_path, so
what is under test is the local layer -- site-id normalisation (zero-padding),
hourly/daily time handling, bbox and date filters, zip extraction, and the
basin site registry -- not EPA's servers.
"""

from __future__ import annotations

import zipfile
from datetime import date, datetime
from pathlib import Path

import polars as pl
import pytest

from brc_tools.api import aqs
from brc_tools.api.aqs import client as ac

BASIN_BBOX = (-110.9, 39.4, -108.7, 41.1)  # lookups.toml uinta_basin, east edge widened to Rangely CO


def test_basin_registry_wellformed():
    ids = [s.aqs_id for s in aqs.UINTA_BASIN_SITES.values()]
    assert len(ids) == len(set(ids))
    for site in aqs.UINTA_BASIN_SITES.values():
        state, county, num = site.aqs_id.split("-")
        assert state.isdigit() and county.isdigit() and num.isdigit()
        assert BASIN_BBOX[0] <= site.lon <= BASIN_BBOX[2]
        assert BASIN_BBOX[1] <= site.lat <= BASIN_BBOX[3]
    # The incomplete-flagged industry monitor stays out unless asked for.
    default = aqs.basin_site_ids()
    assert aqs.UINTA_BASIN_SITES["enefit"].aqs_id not in default
    assert aqs.UINTA_BASIN_SITES["ouray"].aqs_id in default
    assert len(aqs.basin_site_ids(include_flagged=True)) == len(default) + 1


def test_airdata_url_forms():
    assert (aqs.airdata_url("daily", "ozone", 2013)
            == "https://aqs.epa.gov/aqsweb/airdata/daily_44201_2013.zip")
    # Raw segments pass through (met files use words, gases use codes).
    assert aqs.airdata_url("hourly", "WIND", 2020).endswith("hourly_WIND_2020.zip")
    assert aqs.airdata_url("hourly", "88502", 2013).endswith("hourly_88502_2013.zip")
    with pytest.raises(ValueError):
        aqs.airdata_url("weekly", "ozone", 2013)


HOURLY_HEADER = ('"State Code","County Code","Site Num","Latitude","Longitude",'
                 '"Date GMT","Time GMT","Sample Measurement","MDL","Units of Measure"')

HOURLY_ROWS = [
    '"49","047","2003",40.057,-109.688,"2013-02-02","12:00",0.060,1,"Parts per million"',
    '"49","047","2003",40.057,-109.688,"2013-02-02","13:00",0.056,0.1,"Parts per million"',
    '"8","103","6",40.087,-108.761,"2013-02-02","12:00",0.028,0.1,"Parts per million"',
    '"49","013","0002",40.294,-110.010,"2013-03-15","12:00",0.055,0.1,"Parts per million"',
]


def _write_hourly_csv(path: Path) -> Path:
    path.write_text("\n".join([HOURLY_HEADER, *HOURLY_ROWS]) + "\n")
    return path


def test_load_hourly_site_and_date_filters(tmp_path):
    csv_path = _write_hourly_csv(tmp_path / "hourly_44201_2013.csv")
    df = aqs.load_airdata(
        csv_path,
        sites=["49-047-2003", (8, 103, 6)],   # padded string + bare tuple
        start="2013-02-01", end=date(2013, 2, 28),
    )
    # The March Roosevelt row is outside the window; both id styles match.
    assert df.height == 3
    assert df["valid_time"].dtype == pl.Datetime
    assert df["valid_time"].min() == datetime(2013, 2, 2, 12)
    # MDL mixes int-looking and float rows; the override keeps it float.
    assert df["MDL"].dtype == pl.Float64


def test_load_hourly_from_zip_and_bbox(tmp_path):
    csv_path = _write_hourly_csv(tmp_path / "hourly_44201_2013.csv")
    zp = tmp_path / "hourly_44201_2013.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        zf.write(csv_path, csv_path.name)
    csv_path.unlink()  # force the zip-extraction path

    df = aqs.load_airdata(zp, bbox=(-110.9, 39.4, -109.0, 41.1))
    # The Rangely row (-108.761) falls outside this bbox.
    assert df.height == 3
    assert (zp.parent / "hourly_44201_2013.csv").exists()


def test_load_daily_dates_and_standard_rows(tmp_path):
    header = ('"State Code","County Code","Site Num","Latitude","Longitude",'
              '"Date Local","Pollutant Standard","1st Max Value"')
    rows = [
        '"49","047","2003",40.057,-109.688,"2013-02-02","Ozone 8-hour 2015",0.095',
        '"49","047","2003",40.057,-109.688,"2013-02-06","Ozone 8-hour 2015",0.137',
        '"49","047","2003",40.057,-109.688,"2013-02-02","Ozone 1-hour 1979",0.102',
    ]
    p = tmp_path / "daily_44201_2013.csv"
    p.write_text("\n".join([header, *rows]) + "\n")

    df = aqs.load_airdata(p, sites=["49-47-2003"])   # unpadded county accepted
    assert df.height == 3
    assert df["date_local"].dtype == pl.Date
    mda8 = df.filter(pl.col("Pollutant Standard") == "Ozone 8-hour 2015")
    assert mda8["1st Max Value"].max() == pytest.approx(0.137)


def test_norm_code_and_site_tuple():
    assert ac._norm_code("047") == "47"
    assert ac._norm_code("0002") == "2"
    assert ac._norm_code("0") == "0"
    assert ac._site_tuple("49-013-0002") == ("49", "13", "2")
    assert ac._site_tuple((8, 103, 6)) == ("8", "103", "6")
    with pytest.raises(ValueError):
        ac._site_tuple("49/013/0002")

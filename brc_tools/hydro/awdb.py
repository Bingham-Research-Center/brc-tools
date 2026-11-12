"""NRCS Air and Water Database (AWDB) REST API: SNOTEL / SCAN stations and daily data.

Shape (checked 12 Nov 2026 against ``/v3/api-docs`` and live calls):

* ``/stations`` takes ``stationTriplets=*:UT:SNTL`` wildcards and, with
  ``returnStationElements=true``, must be narrowed by ``elements=`` and ``durations=``
  or it answers 400 ("number of station elements exceeds the amount allowed").
  ``shefId`` is the Synoptic station id (KGCU1), ``dataTimeZone`` the station's data
  offset (-8 for SNOTEL), ``elevation`` is feet, ``heightDepth`` is inches (negative
  below ground).
* ``/data`` takes ``elements=CODE:heightDepth:ordinal`` with ``*`` wildcards and returns
  ``[{stationTriplet, data: [{stationElement, values: [{date, value, qcFlag}]}]}]``.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import polars as pl

from . import cache_dir as _cache_dir
from . import fresh_parquet, get_json, save_raw

BASE = "https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1"
ELEMENTS = ("WTEQ", "SNWD", "SMS", "STO", "PREC", "TOBS")
FT_TO_M = 0.3048
IN_TO_CM = 2.54

STATION_SCHEMA = {
    "triplet": pl.String, "station_id": pl.String, "state": pl.String, "network": pl.String,
    "name": pl.String, "shef_id": pl.String, "lat": pl.Float64, "lon": pl.Float64,
    "elevation_m": pl.Float64, "data_time_zone": pl.Float64, "huc": pl.String,
    "begin_date": pl.String, "end_date": pl.String, "county": pl.String, "elements": pl.String,
}

ELEMENT_SCHEMA = {
    "triplet": pl.String, "shef_id": pl.String, "element": pl.String, "ordinal": pl.Int32,
    "height_depth_in": pl.Float64, "depth_cm": pl.Float64, "duration": pl.String,
    "unit": pl.String, "begin_date": pl.String, "end_date": pl.String, "derived": pl.Boolean,
}

DAILY_SCHEMA = {
    "triplet": pl.String, "element": pl.String, "ordinal": pl.Int32, "height_depth_in": pl.Float64,
    "depth_cm": pl.Float64, "date": pl.Date, "value": pl.Float64, "unit": pl.String,
    "value_si": pl.Float64, "unit_si": pl.String, "qc_flag": pl.String, "qa_flag": pl.String,
}

# storedUnitCode -> (scale, offset, SI unit); SNWD is special-cased to cm below.
_UNITS = {
    "in": (25.4, 0.0, "mm"),
    "degF": (5.0 / 9.0, -32.0 * 5.0 / 9.0, "degC"),
    "degC": (1.0, 0.0, "degC"),
    "pct": (1.0, 0.0, "%"),
    "mm": (1.0, 0.0, "mm"),
    "cm": (10.0, 0.0, "mm"),
}


def _element_filter(elements) -> str:
    return ",".join(f"{e}:*:*" if ":" not in e else e for e in elements)


def _num(value):
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _depth_cm(height_depth_in):
    """AWDB heightDepth is inches, negative below ground; depth_cm is positive below
    ground (an above-ground sensor height comes out negative)."""
    if height_depth_in is None:
        return None
    return round(-height_depth_in * IN_TO_CM, 2)


def stations(*, states=("UT", "CO", "WY"), networks=("SNTL", "SCAN"), bbox=None, elements=ELEMENTS,
             durations=("DAILY",), active_only: bool = False, cache_dir: Path | str | None = None,
             force: bool = False, fetch=get_json) -> pl.DataFrame:
    """Stations of the given networks and states, one cached request per (state,
    network), with their element lists narrowed to ``elements`` x ``durations``.
    ``bbox = (lon_w, lat_s, lon_e, lat_n)`` filters locally (the API has no bbox)."""
    out = _cache_dir("awdb/stations", cache_dir)
    rows = []
    for state in states:
        for net in networks:
            stem = f"{state}_{net}_{'-'.join(elements)}_{'-'.join(durations)}_{'active' if active_only else 'all'}"
            path = out / f"{stem}.json"
            if not path.exists() or force:
                params = {"stationTriplets": f"*:{state}:{net}", "returnStationElements": "true",
                          "activeOnly": "true" if active_only else "false",
                          "elements": _element_filter(elements), "durations": ",".join(durations)}
                data, meta = fetch(f"{BASE}/stations", params)
                meta["params"] = params
                save_raw(path, data, meta)
            for s in json.loads(path.read_text()):
                elev = _num(s.get("elevation"))
                rows.append(dict(
                    triplet=s.get("stationTriplet"), station_id=s.get("stationId"), state=s.get("stateCode"),
                    network=s.get("networkCode"), name=s.get("name"), shef_id=s.get("shefId"),
                    lat=_num(s.get("latitude")), lon=_num(s.get("longitude")),
                    elevation_m=elev * FT_TO_M if elev is not None else None,
                    data_time_zone=_num(s.get("dataTimeZone")), huc=s.get("huc"),
                    begin_date=s.get("beginDate"), end_date=s.get("endDate"), county=s.get("countyName"),
                    elements=json.dumps(s.get("stationElements") or []),
                ))
    frame = pl.DataFrame(rows, schema=STATION_SCHEMA)
    if bbox is not None:
        w, s_, e, n = bbox
        frame = frame.filter((pl.col("lon") >= w) & (pl.col("lon") <= e) & (pl.col("lat") >= s_) & (pl.col("lat") <= n))
    return frame.sort("state", "network", "name")


def station_elements(stations_frame: pl.DataFrame) -> pl.DataFrame:
    """One row per (station, element, depth, ordinal): the authoritative sensor-depth table."""
    rows = []
    for triplet, shef, blob in zip(stations_frame["triplet"], stations_frame["shef_id"], stations_frame["elements"]):
        for el in json.loads(blob or "[]"):
            hd = _num(el.get("heightDepth"))
            rows.append(dict(
                triplet=triplet, shef_id=shef, element=el.get("elementCode"), ordinal=int(el.get("ordinal") or 1),
                height_depth_in=hd, depth_cm=_depth_cm(hd), duration=el.get("durationName"),
                unit=el.get("storedUnitCode"), begin_date=el.get("beginDate"), end_date=el.get("endDate"),
                derived=bool(el.get("derivedData")),
            ))
    return pl.DataFrame(rows, schema=ELEMENT_SCHEMA).sort("triplet", "element", "height_depth_in", "ordinal")


def _si(element, unit, value):
    if value is None:
        return None, None
    if element == "SNWD" and unit == "in":
        return value * IN_TO_CM, "cm"
    spec = _UNITS.get(unit)
    if spec is None:
        return None, None
    scale, offset, target = spec
    return value * scale + offset, target


def daily(triplet: str, *, elements=ELEMENTS, begin: date | str, end: date | str,
          cache_dir: Path | str | None = None, force: bool = False, fetch=get_json) -> pl.DataFrame:
    """Daily values of ``elements`` for one station triplet, cached as the raw response
    plus a derived parquet. SI columns: WTEQ/PREC mm, SNWD cm, STO/TOBS degC, SMS %."""
    begin, end = str(begin)[:10], str(end)[:10]
    out = _cache_dir("awdb/daily", cache_dir)
    stem = f"{triplet.replace(':', '_')}_{'-'.join(elements)}_{begin}_{end}"
    raw = out / f"{stem}.json"
    if not raw.exists() or force:
        params = {"stationTriplets": triplet, "elements": _element_filter(elements), "duration": "DAILY",
                  "beginDate": begin, "endDate": end, "returnFlags": "true", "periodRef": "END"}
        data, meta = fetch(f"{BASE}/data", params)
        meta["params"] = params
        save_raw(raw, data, meta)
    parquet = out / f"{stem}.parquet"
    if fresh_parquet(parquet, [raw]) and not force:
        return pl.read_parquet(parquet)
    rows = []
    for station in json.loads(raw.read_text()):
        for block in station.get("data", []):
            el = block.get("stationElement", {})
            code, unit = el.get("elementCode"), el.get("storedUnitCode")
            hd = _num(el.get("heightDepth"))
            for v in block.get("values", []):
                val = _num(v.get("value"))
                si, unit_si = _si(code, unit, val)
                rows.append(dict(
                    triplet=station.get("stationTriplet"), element=code, ordinal=int(el.get("ordinal") or 1),
                    height_depth_in=hd, depth_cm=_depth_cm(hd), date=date.fromisoformat(str(v.get("date"))[:10]),
                    value=val, unit=unit, value_si=si, unit_si=unit_si, qc_flag=v.get("qcFlag"), qa_flag=v.get("qaFlag"),
                ))
    frame = pl.DataFrame(rows, schema=DAILY_SCHEMA).sort("element", "height_depth_in", "date")
    frame.write_parquet(parquet, compression="zstd")
    parquet.with_suffix(".meta.json").write_text(json.dumps({"pages": [raw.name]}))
    return frame

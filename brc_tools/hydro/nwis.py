"""USGS Water Data OGC API: monitoring locations and daily values.

The legacy ``waterservices.usgs.gov/nwis`` endpoints degrade from November 2026 and
close in February 2027; this module speaks only to ``api.waterdata.usgs.gov``.
Shape (checked 12 Nov 2026): GeoJSON feature collections, ``value`` as a string,
cursor paging through ``links[rel=next]``, no ``numberMatched``.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import polars as pl

from . import cache_dir as _cache_dir
from . import fresh_parquet, get_json, save_raw

BASE = "https://api.waterdata.usgs.gov/ogcapi/v1"
DISCHARGE = "00060"          # parameter code: discharge, ft3/s
DAILY_MEAN = "00003"         # statistic code: daily mean
FT3_TO_M3 = 0.028316846592
FT_TO_M = 0.3048
MI2_TO_KM2 = 2.589988110336
PAGE_LIMIT = 5000

DAILY_SCHEMA = {
    "site_id": pl.String, "time": pl.Date, "value": pl.Float64, "unit": pl.String,
    "value_m3s": pl.Float64, "approval_status": pl.String, "qualifier": pl.String,
    "statistic_id": pl.String, "parameter_code": pl.String, "last_modified": pl.String,
}

LOCATION_SCHEMA = {
    "site_id": pl.String, "site_no": pl.String, "name": pl.String, "lat": pl.Float64,
    "lon": pl.Float64, "altitude_m": pl.Float64, "huc": pl.String, "drainage_km2": pl.Float64,
    "contributing_km2": pl.Float64, "site_type_code": pl.String, "state_code": pl.String,
    "county_name": pl.String, "time_zone": pl.String,
}


def _pages(first_url: str, params: dict, out_dir: Path, stem: str, *, force: bool, fetch=get_json) -> list[Path]:
    """Fetch (or reuse) every page of a cursor-paged collection; return the page files."""
    done = out_dir / f"{stem}.done"
    existing = sorted((p for p in out_dir.glob(f"{stem}.page*.json") if re.search(r"\.page\d+\.json$", p.name)),
                      key=lambda p: int(re.search(r"page(\d+)", p.name).group(1)))
    if existing and done.exists() and not force:
        return existing
    for p in existing:
        p.unlink(missing_ok=True)
        p.with_suffix(".json.meta.json").unlink(missing_ok=True)
    done.unlink(missing_ok=True)
    pages, url, prm, n = [], first_url, params, 0
    while url:
        data, meta = fetch(url, prm)
        meta["params"] = prm
        pages.append(save_raw(out_dir / f"{stem}.page{n}.json", data, meta))
        nxt = [l.get("href") for l in data.get("links", []) if l.get("rel") == "next"]
        url, prm, n = (nxt[0] if nxt else None), None, n + 1
    done.write_text(json.dumps({"pages": [p.name for p in pages]}))
    return pages


def _features(pages: list[Path]):
    for p in pages:
        for f in json.loads(p.read_text()).get("features", []):
            yield f


def _num(value):
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def monitoring_locations(bbox: tuple[float, float, float, float], *, site_type_code: str = "ST",
                         cache_dir: Path | str | None = None, force: bool = False, fetch=get_json) -> pl.DataFrame:
    """Sites of one type inside ``bbox = (lon_w, lat_s, lon_e, lat_n)``. Altitude and
    drainage area are converted from the API's feet and square miles."""
    out = _cache_dir("nwis/monitoring_locations", cache_dir)
    stem = f"{site_type_code}_{bbox[0]:.3f}_{bbox[1]:.3f}_{bbox[2]:.3f}_{bbox[3]:.3f}".replace("-", "m")
    params = {"bbox": ",".join(f"{v:.4f}" for v in bbox), "site_type_code": site_type_code, "f": "json", "limit": 1000}
    pages = _pages(f"{BASE}/collections/monitoring-locations/items", params, out, stem, force=force, fetch=fetch)
    rows = []
    for f in _features(pages):
        p = f.get("properties", {})
        coords = (f.get("geometry") or {}).get("coordinates") or [None, None]
        alt = _num(p.get("altitude"))
        da, cda = _num(p.get("drainage_area")), _num(p.get("contributing_drainage_area"))
        rows.append(dict(
            site_id=p.get("id"), site_no=p.get("monitoring_location_number"), name=p.get("monitoring_location_name"),
            lat=_num(coords[1]), lon=_num(coords[0]), altitude_m=alt * FT_TO_M if alt is not None else None,
            huc=p.get("hydrologic_unit_code"), drainage_km2=da * MI2_TO_KM2 if da is not None else None,
            contributing_km2=cda * MI2_TO_KM2 if cda is not None else None, site_type_code=p.get("site_type_code"),
            state_code=p.get("state_code"), county_name=p.get("county_name"), time_zone=p.get("time_zone_abbreviation"),
        ))
    return pl.DataFrame(rows, schema=LOCATION_SCHEMA).sort("site_no")


def daily(site_id: str, *, parameter_code: str = DISCHARGE, statistic_id: str = DAILY_MEAN,
          start: date | str, end: date | str, cache_dir: Path | str | None = None,
          api_key: str | None = None, force: bool = False, fetch=get_json) -> pl.DataFrame:
    """Daily values for one site (``"USGS-09266500"`` or ``"09266500"``), cached as raw
    pages plus a derived parquet. Discharge is also returned in m3 s-1."""
    site_id = site_id if site_id.startswith("USGS-") else f"USGS-{site_id}"
    start, end = str(start)[:10], str(end)[:10]
    out = _cache_dir("nwis/daily", cache_dir)
    stem = f"{site_id}_{parameter_code}_{statistic_id}_{start}_{end}"
    params = {"monitoring_location_id": site_id, "parameter_code": parameter_code, "statistic_id": statistic_id,
              "datetime": f"{start}/{end}", "f": "json", "limit": PAGE_LIMIT}
    if api_key:
        params["api_key"] = api_key
    pages = _pages(f"{BASE}/collections/daily/items", params, out, stem, force=force, fetch=fetch)
    parquet = out / f"{stem}.parquet"
    if fresh_parquet(parquet, pages) and not force:
        return pl.read_parquet(parquet)
    rows = []
    for f in _features(pages):
        p = f.get("properties", {})
        v = _num(p.get("value"))
        unit = p.get("unit_of_measure")
        rows.append(dict(
            site_id=p.get("monitoring_location_id"), time=date.fromisoformat(str(p.get("time"))[:10]), value=v, unit=unit,
            value_m3s=(v * FT3_TO_M3 if v is not None and unit and unit.replace("^", "").replace("**", "").lower() in ("ft3/s", "cfs") else None),
            approval_status=p.get("approval_status"), qualifier=(",".join(p["qualifier"]) if isinstance(p.get("qualifier"), list) else p.get("qualifier")),
            statistic_id=p.get("statistic_id"), parameter_code=p.get("parameter_code"), last_modified=p.get("last_modified"),
        ))
    frame = pl.DataFrame(rows, schema=DAILY_SCHEMA).sort("time")
    frame.write_parquet(parquet, compression="zstd")
    parquet.with_suffix(".meta.json").write_text(json.dumps({"pages": [p.name for p in pages]}))
    return frame


def water_year(col: pl.Expr) -> pl.Expr:
    return pl.when(col.dt.month() >= 10).then(col.dt.year() + 1).otherwise(col.dt.year())


def water_year_summary(df: pl.DataFrame, *, months=(4, 5, 6, 7), min_days: int = 100) -> pl.DataFrame:
    """Per site and water year over ``months``: volume (m3), centroid date (half the
    volume passed), peak and its date, days present. Years with fewer than
    ``min_days`` daily values in the window are kept but flagged ``complete = false``."""
    sub = (
        df.filter(pl.col("value_m3s").is_not_null() & pl.col("time").dt.month().is_in(list(months)))
        .with_columns(water_year(pl.col("time")).alias("water_year"), (pl.col("value_m3s") * 86400.0).alias("vol_day_m3"))
        .sort("site_id", "time")
    )
    rows = []
    for (site, wy), g in sub.group_by(["site_id", "water_year"], maintain_order=True):
        vol = g["vol_day_m3"].sum()
        cum = g["vol_day_m3"].cum_sum()
        half_idx = int((cum >= 0.5 * vol).arg_max()) if vol > 0 else None
        peak_idx = int(g["value_m3s"].arg_max())
        rows.append(dict(site_id=site, water_year=int(wy), vol_m3=float(vol), n_days=g.height,
                         complete=g.height >= min_days,
                         centroid_date=g["time"][half_idx] if half_idx is not None else None,
                         peak_m3s=float(g["value_m3s"][peak_idx]), peak_date=g["time"][peak_idx]))
    schema = {"site_id": pl.String, "water_year": pl.Int32, "vol_m3": pl.Float64, "n_days": pl.Int32, "complete": pl.Boolean,
              "centroid_date": pl.Date, "peak_m3s": pl.Float64, "peak_date": pl.Date}
    return pl.DataFrame(rows, schema=schema).sort("site_id", "water_year")

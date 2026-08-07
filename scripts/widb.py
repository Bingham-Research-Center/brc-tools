#!/usr/bin/env python3
"""Python client for the Waterisotopes Database (wiDB) public API.

A Python port of SPATIAL-Lab/wiDButil (R). The wiDB API is three public GET
endpoints, no auth (see that repo's Protocol.md). Returns tidy polars frames.

    widb_sites(...)   -> sites.php    site metadata (JSON)
    widb_data(...)    -> download.php  the d2H/d18O records (zip of CSV/XLSX)
    widb_values(...)  -> values.php    valid values for categorical fields (JSON)

Filters (all optional, passed as kwargs): min_lat / max_lat / min_long / max_long,
min_elev / max_elev, min_date / max_date ("yyyy-mm-dd"), and list-valued
countries / states / types / projects.

CLI example (Uinta transect precipitation):
    python widb.py data --min-lat 40.0 --max-lat 41.0 --min-long -111.0 --max-long -109.0 \
        --types Precipitation --out uinta_precip.csv

Standalone: depends only on requests + polars (no brc_tools imports).
"""
from __future__ import annotations

import argparse
import io
import zipfile

import polars as pl
import requests

BASE = "https://wateriso.utah.edu/api/v1"
_MISSING = [9999.0, -9999.0]  # Protocol.md: 9999 = embargoed, -9999 = no value

# python kwarg -> wiDB API query parameter
_PARAM = {
    "min_lat": "minLat", "max_lat": "maxLat", "min_long": "minLong", "max_long": "maxLong",
    "min_elev": "minElev", "max_elev": "maxElev", "min_date": "minDate", "max_date": "maxDate",
    "countries": "countries", "states": "states", "types": "types", "projects": "projects",
}


def _query(filters: dict) -> dict:
    """Map kwargs to API params, dropping None and comma-joining lists."""
    out = {}
    for k, v in filters.items():
        if v is None:
            continue
        api = _PARAM.get(k, k)
        out[api] = ",".join(map(str, v)) if isinstance(v, (list, tuple)) else str(v)
    return out


def _get(endpoint: str, params: dict, *, base: str = BASE, timeout: float = 90.0) -> requests.Response:
    r = requests.get(f"{base}/{endpoint}", params=params, timeout=timeout)
    r.raise_for_status()
    return r


def _json_to_frame(data) -> pl.DataFrame:
    """wiDB JSON -> polars, handling list-of-records or dict-of-equal-length-lists."""
    if isinstance(data, list):
        return pl.DataFrame(data)
    if isinstance(data, dict) and data:
        cols = {k: v for k, v in data.items() if isinstance(v, list)}
        if cols and len({len(v) for v in cols.values()}) == 1:
            return pl.DataFrame(cols)
        return pl.DataFrame([data])
    return pl.DataFrame()


def widb_values(fields, *, base: str = BASE) -> dict:
    """Valid values for categorical fields (values.php). fields: e.g. ['types','states']."""
    return _get("values.php", {"fields": ",".join(fields)}, base=base).json()


def widb_sites(*, return_fields=None, base: str = BASE, **filters) -> pl.DataFrame:
    """Sites matching the spatial/temporal filters (sites.php) — one row per site
    (Latitude, Longitude, Site_ID)."""
    params = _query(filters)
    if return_fields:
        params["return"] = ",".join(return_fields)
    data = _get("sites.php", params, base=base).json()
    if isinstance(data, dict) and isinstance(data.get("sites"), list):
        return pl.DataFrame(data["sites"])
    return _json_to_frame(data)


def widb_data(*, base: str = BASE, **filters) -> pl.DataFrame:
    """The d2H/d18O records matching the filters (download.php -> zip of CSVs).

    The zip holds ``*-data.csv`` (records) + ``*-project.csv`` + a header-description
    xlsx; we read the data CSV. Returns an empty frame if nothing matched.
    """
    resp = _get("download.php", _query(filters), base=base)
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    names = zf.namelist()
    name = (next((n for n in names if n.lower().endswith("data.csv")), None)
            or next((n for n in names if n.lower().endswith(".csv")), None))
    if not name:
        return pl.DataFrame()
    raw = zf.read(name)
    if not raw.strip():
        return pl.DataFrame()  # query matched no records
    df = pl.read_csv(io.BytesIO(raw), infer_schema_length=5000)
    iso = [c for c in ("d2H", "d18O", "d2H_Analytical_SD", "d18O_Analytical_SD") if c in df.columns]
    if iso:
        df = df.with_columns(
            pl.when(pl.col(c).is_in(_MISSING)).then(None).otherwise(pl.col(c)).alias(c) for c in iso
        )
    return df


def main() -> None:
    ap = argparse.ArgumentParser(description="Query the Waterisotopes Database (wiDB).")
    ap.add_argument("mode", choices=["sites", "data", "values"])
    for f in ("min-lat", "max-lat", "min-long", "max-long", "min-elev", "max-elev"):
        ap.add_argument(f"--{f}", type=float)
    for f in ("min-date", "max-date", "types", "projects", "states", "countries", "fields", "out"):
        ap.add_argument(f"--{f}")
    a = ap.parse_args()

    if a.mode == "values":
        print(widb_values((a.fields or "types,states,projects").split(",")))
        return

    def lst(x):
        return x.split(",") if x else None

    filt = dict(
        min_lat=a.min_lat, max_lat=a.max_lat, min_long=a.min_long, max_long=a.max_long,
        min_elev=a.min_elev, max_elev=a.max_elev, min_date=a.min_date, max_date=a.max_date,
        types=lst(a.types), projects=lst(a.projects), states=lst(a.states), countries=lst(a.countries),
    )
    df = widb_sites(**filt) if a.mode == "sites" else widb_data(**filt)
    with pl.Config(tbl_rows=20, tbl_cols=-1):
        print(df)
    print("shape:", df.shape)
    if a.out:
        df.write_csv(a.out)
        print("wrote", a.out)


if __name__ == "__main__":
    main()

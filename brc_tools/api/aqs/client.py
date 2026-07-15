"""EPA AQS "AirData" bulk-file client: quality-assured AQ + met observations.

Mechanical API layer.  Downloads EPA's pre-generated annual AirData files
(``https://aqs.epa.gov/aqsweb/airdata/``) and loads them filtered to sites,
counties, a bbox, and/or a date window as a Polars frame.  The files are
**anonymous** (no key, no registration) and are the citable, quality-assured
record for regulatory and tribal monitors -- unlike Synoptic, which returns no
ozone/PM for the Uinta Basin before ~2014.  Like ``api/soundings``, this source
is open, so there is no ``_auth`` wiring.

Scope notes
-----------
* One file = one parameter x one year x one cadence (``hourly``/``daily``),
  covering the whole US (hourly ozone is ~66 MB zipped / ~2 GB CSV; the daily
  file is ~5 MB).  Download once into the cache, filter locally.
* **Do not recompute regulatory MDA8 from the hourly file** -- the ``daily``
  file already carries EPA's own daily max 8-hour value per ``Pollutant
  Standard`` row (``"1st Max Value"``), with the 75%-completeness and
  day-assignment rules applied.  Use hourly for diurnal structure, daily for
  MDA8 series.
* EPA regenerates these files as QA flows in (the ``Last-Modified`` header
  moves).  ``download_airdata`` stores a ``*.meta.json`` sidecar (URL,
  retrieval time, Last-Modified, size) next to the zip so a study can record
  exactly which vintage it used.
* Tribal monitors (e.g. Ute Indian Tribe) appear under normal state/county
  FIPS codes in these files, not under AQS "TT" tribal codes.

Cache: ``BRC_TOOLS_AQS_CACHE`` env var, else ``~/.cache/brc-tools/aqs``.
Times: hourly rows gain a tz-naive UTC ``valid_time`` (house convention);
daily rows gain a ``date_local`` Date column.
"""

from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

AIRDATA_BASE = "https://aqs.epa.gov/aqsweb/airdata"

# AirData filename "parameter" segments.  Criteria gases use the AQS parameter
# code; the met/derived files use literal words.
PARAMS: dict[str, str] = {
    "ozone": "44201",
    "pm25_frm": "88101",       # FRM/FEM PM2.5
    "pm25_nonfrm": "88502",    # non-FRM "Acceptable PM2.5" (tribal sites live here)
    "pm10": "81102",
    "no2": "42602",
    "so2": "42401",
    "co": "42101",
    "wind": "WIND",
    "temp": "TEMP",
    "rh_dp": "RH_DP",
    "pressure": "PRESS",
}

# Columns that trip Polars' integer inference partway through a file.
_FLOAT_OVERRIDES = (
    "MDL", "Uncertainty", "Sample Measurement", "1st Max Value",
    "Arithmetic Mean", "Observation Percent", "AQI",
)


@dataclass(frozen=True)
class AQSSite:
    """One AQS monitor: zero-padded ``SS-CCC-NNNN`` id + identity notes."""

    aqs_id: str        # e.g. "49-047-2003"
    name: str
    operator: str
    lat: float
    lon: float
    note: str = ""


# Uinta Basin area monitors verified to report ozone through winter 2012-13
# (AQS site registry + annual_conc_by_monitor_2013; identities cross-checked
# against coordinates, 2026-07-15).  Extend freely; ``load_airdata`` also
# accepts raw ids for any site.
UINTA_BASIN_SITES: dict[str, AQSSite] = {
    "ouray": AQSSite("49-047-2003", "Ouray", "Ute Indian Tribe", 40.057, -109.688,
                     "basin floor; also PM2.5 (88502); est. 2008-12"),
    "redwash": AQSSite("49-047-2002", "Redwash", "Ute Indian Tribe", 40.206, -109.354,
                       "Deadman's Bench; also PM2.5 (88502); est. 2008-12"),
    "whiterocks": AQSSite("49-047-7022", "Whiterocks", "Ute Indian Tribe", 40.484, -109.907,
                          "est. 1985"),
    "myton": AQSSite("49-013-7011", "Myton", "Ute Indian Tribe", 40.217, -110.183,
                     "est. 1985"),
    "roosevelt": AQSSite("49-013-0002", "Roosevelt", "Utah DEQ", 40.294, -110.010,
                         "also PM2.5 (88502, POC 3); est. 2011-10"),
    "vernal": AQSSite("49-047-1003", "Vernal", "Utah DEQ", 40.452, -109.510,
                      "est. 2012-01"),
    "dinosaur_nm": AQSSite("49-047-1002", "Dinosaur NM - West Entrance", "NPS",
                           40.437, -109.305, "Jensen, UT side; est. 2005-05"),
    "little_mountain": AQSSite("49-047-0014", "Little Mountain", "USFS",
                               40.538, -109.700, "north-rim control site; est. 2010-05"),
    "fruitland": AQSSite("49-013-1001", "Fruitland", "Utah DEQ", 40.209, -110.841,
                         "west-margin control; 2011-04 to 2014-03"),
    "rangely": AQSSite("08-103-0006", "Rangely, Golf Course", "NPS", 40.087, -108.761,
                       "CO side of basin; also PM2.5 (88101); est. 2010-08"),
    "enefit": AQSSite("49-047-5632", "Enefit (Dragon Rd)", "Enefit (industry)",
                      39.869, -109.097,
                      "2012 to 2013-12; 2013 data flagged incomplete -- exclude by default"),
}


def basin_site_ids(*, include_flagged: bool = False) -> list[str]:
    """AQS ids of the registry sites, dropping incomplete-flagged ones by default."""
    return [s.aqs_id for k, s in UINTA_BASIN_SITES.items()
            if include_flagged or k != "enefit"]


def airdata_url(kind: str, param: str, year: int) -> str:
    """URL of one pre-generated AirData file.

    ``kind`` is ``"hourly"`` or ``"daily"``; ``param`` is a ``PARAMS`` key or a
    raw AirData segment (e.g. ``"44201"``, ``"WIND"``).
    """
    if kind not in ("hourly", "daily"):
        raise ValueError(f"kind must be 'hourly' or 'daily', got {kind!r}")
    seg = PARAMS.get(param, param)
    return f"{AIRDATA_BASE}/{kind}_{seg}_{year}.zip"


def _cache_dir(cache_dir: Path | str | None = None) -> Path:
    if cache_dir is not None:
        p = Path(cache_dir)
    else:
        p = Path(os.getenv("BRC_TOOLS_AQS_CACHE",
                           Path.home() / ".cache" / "brc-tools" / "aqs"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def download_airdata(kind: str, param: str, year: int, *,
                     cache_dir: Path | str | None = None,
                     force: bool = False) -> Path:
    """Download (or reuse) one AirData zip; return its path.

    Writes a ``<name>.zip.meta.json`` provenance sidecar (URL, retrieval time,
    server ``Last-Modified``, size).  Raises ``requests.HTTPError`` on failure.
    """
    import requests

    url = airdata_url(kind, param, year)
    out = _cache_dir(cache_dir) / url.rsplit("/", 1)[1]
    if out.exists() and not force:
        return out

    resp = requests.get(url, stream=True, timeout=120)
    resp.raise_for_status()
    part = out.with_suffix(out.suffix + ".part")
    with open(part, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1 << 20):
            f.write(chunk)
    part.rename(out)

    meta = {
        "url": url,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "last_modified": resp.headers.get("Last-Modified"),
        "content_length": out.stat().st_size,
    }
    with open(out.parent / (out.name + ".meta.json"), "w") as f:
        json.dump(meta, f, indent=1)
    return out


def _extract_csv(zip_path: Path) -> Path:
    """Extract the single CSV member next to the zip (idempotent)."""
    import zipfile

    with zipfile.ZipFile(zip_path) as zf:
        members = [m for m in zf.namelist() if m.lower().endswith(".csv")]
        if len(members) != 1:
            raise ValueError(f"{zip_path.name}: expected one CSV member, got {members}")
        target = zip_path.parent / members[0]
        if not target.exists():
            zf.extract(members[0], zip_path.parent)
    return target


def _read_header(csv_path: Path) -> list[str]:
    with open(csv_path, newline="") as f:
        return next(csv.reader(f))


def _norm_code(value: str) -> str:
    """Normalise an AQS code for comparison: '047' == '47', '0002' == '2'."""
    s = str(value).strip()
    stripped = s.lstrip("0")
    return stripped if stripped else "0"


def _site_tuple(site) -> tuple[str, str, str]:
    """Accept '49-047-2003' or (49, 47, 2003); return normalised strings."""
    if isinstance(site, str):
        parts = site.split("-")
        if len(parts) != 3:
            raise ValueError(f"site id must be 'SS-CCC-NNNN', got {site!r}")
    else:
        parts = list(site)
    return tuple(_norm_code(p) for p in parts)  # type: ignore[return-value]


def _to_date(d) -> date:
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    return date.fromisoformat(str(d))


def load_airdata(source: Path | str, *,
                 sites=None, bbox=None, start=None, end=None):
    """Load one AirData zip/CSV filtered to sites/bbox/dates; return a Polars frame.

    Parameters
    ----------
    source : Path or str
        An AirData ``.zip`` (extracted on demand, cached) or ``.csv``.
    sites : iterable, optional
        AQS ids as ``"SS-CCC-NNNN"`` strings or ``(state, county, site)``
        tuples.  Zero-padding-insensitive.
    bbox : tuple, optional
        ``(lon_min, lat_min, lon_max, lat_max)`` on the Latitude/Longitude
        columns (same order as ``regions`` in ``lookups.toml``).
    start, end : date/datetime/ISO str, optional
        Inclusive window on ``Date GMT`` (hourly files) or ``Date Local``
        (daily files).
    """
    import polars as pl

    src = Path(source)
    csv_path = _extract_csv(src) if src.suffix.lower() == ".zip" else src
    header = _read_header(csv_path)
    overrides = {c: pl.Float64 for c in _FLOAT_OVERRIDES if c in header}

    lf = pl.scan_csv(csv_path, infer_schema_length=10000, schema_overrides=overrides)

    hourly = "Date GMT" in header
    date_col = "Date GMT" if hourly else "Date Local"
    lf = lf.with_columns(pl.col(date_col).cast(pl.Utf8).str.to_date().alias("_date"))

    if start is not None:
        lf = lf.filter(pl.col("_date") >= _to_date(start))
    if end is not None:
        lf = lf.filter(pl.col("_date") <= _to_date(end))

    if sites is not None:
        norm = [_site_tuple(s) for s in sites]
        code = {c: pl.col(c).cast(pl.Utf8).str.strip_chars_start("0").replace("", "0")
                for c in ("State Code", "County Code", "Site Num")}
        preds = [(code["State Code"] == st) & (code["County Code"] == co)
                 & (code["Site Num"] == si) for st, co, si in norm]
        combined = preds[0]
        for p in preds[1:]:
            combined = combined | p
        lf = lf.filter(combined)

    if bbox is not None:
        lon_min, lat_min, lon_max, lat_max = bbox
        lf = lf.filter(pl.col("Longitude").is_between(lon_min, lon_max)
                       & pl.col("Latitude").is_between(lat_min, lat_max))

    df = lf.collect()

    if hourly:
        df = df.with_columns(
            (pl.col("Date GMT").cast(pl.Utf8) + " " + pl.col("Time GMT").cast(pl.Utf8))
            .str.to_datetime("%Y-%m-%d %H:%M").alias("valid_time"))
    else:
        df = df.rename({"_date": "date_local"})
    return df.drop("_date") if "_date" in df.columns else df

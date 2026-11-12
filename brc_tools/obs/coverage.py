"""What a canonical Synoptic archive already holds, and what is still missing.

Two tables, both derived from the archive and cached beside it under
``<archive>/coverage/``:

* ``windows.parquet`` -- one row per (request, station): the time window a request
  asked for and the variables it asked for. Coverage is judged on windows, because an
  empty answer for a station-year is a legitimate answer that must not be re-asked.
* ``index.parquet`` -- one row per (station, sensor, UTC day): how many values came
  back and how many carried a QC flag. This is for completeness figures.

Everything streams one archived object at a time and never builds the one-dict-per-cell
``research.long_frame``; a five-water-year hourly station object is a few hundred
thousand cells and this must run on a small host.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import polars as pl

from .archive import replay

INDEX_SCHEMA = {
    "stid": pl.String,
    "variable": pl.String,
    "sensor": pl.String,
    "day": pl.Date,
    "n_obs": pl.UInt32,
    "n_flagged": pl.UInt32,
    "request_key": pl.String,
    "receipt": pl.String,
}

WINDOWS_SCHEMA = {
    "request_key": pl.String,
    "receipt": pl.String,
    "service": pl.String,
    "stid": pl.String,
    "vars": pl.List(pl.String),
    "window_start": pl.Datetime("us", "UTC"),
    "window_end": pl.Datetime("us", "UTC"),
    "outcome": pl.String,
    "requested_utc": pl.String,
}

_SENSOR_SUFFIX = re.compile(r"_(?:set|value)_\d+d?$")


def variable_of(sensor: str) -> str:
    """``soil_temp_set_2`` -> ``soil_temp`` (the same rule research.long_frame uses)."""
    return _SENSOR_SUFFIX.sub("", sensor)


def utc_times(strings: list[str]) -> pl.Series:
    """Synoptic ``date_time`` strings (``...Z`` or an explicit offset) as tz-aware UTC."""
    s = pl.Series("time", strings, dtype=pl.String).str.replace(r"Z$", "+0000")
    return s.str.to_datetime("%Y-%m-%dT%H:%M:%S%z", time_unit="us").dt.convert_time_zone("UTC")


def _coverage_dir(archive: Path) -> Path:
    d = Path(archive) / "coverage"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _replace(path: Path, frame: pl.DataFrame) -> None:
    """Rewrite a derived table in place (these are caches, not archive objects)."""
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".pending-", suffix=".parquet")
    os.close(fd)
    frame.write_parquet(name, compression="zstd")
    os.replace(name, path)


def _read_or_empty(path: Path, schema: dict) -> pl.DataFrame:
    if path.exists():
        return pl.read_parquet(path)
    return pl.DataFrame(schema=schema)


def station_daily_counts(station: dict) -> pl.DataFrame:
    """Per (sensor, UTC day) counts for one station of a replayed payload."""
    obs = station.get("OBSERVATIONS", {})
    times = obs.get("date_time", [])
    if not times:
        return pl.DataFrame(schema={k: v for k, v in INDEX_SCHEMA.items()
                                    if k in ("stid", "variable", "sensor", "day", "n_obs", "n_flagged")})
    day = utc_times(times).dt.date().alias("day")
    qc = station.get("QC", {}) or {}
    parts = []
    for sensor, values in obs.items():
        if sensor == "date_time" or not isinstance(values, list) or len(values) != len(times):
            continue
        value = pl.Series("value", values, dtype=pl.Float64, strict=False)
        flags = qc.get(sensor) or []
        flagged = (
            pl.Series("flagged", [bool(f) for f in flags], dtype=pl.Boolean)
            if len(flags) == len(times)
            else pl.Series("flagged", [False] * len(times), dtype=pl.Boolean)
        )
        part = (
            pl.DataFrame([day, value, flagged])
            .group_by("day")
            .agg(
                pl.col("value").is_not_null().sum().cast(pl.UInt32).alias("n_obs"),
                pl.col("flagged").sum().cast(pl.UInt32).alias("n_flagged"),
            )
            .with_columns(
                pl.lit(station["STID"]).alias("stid"),
                pl.lit(variable_of(sensor)).alias("variable"),
                pl.lit(sensor).alias("sensor"),
            )
            .select("stid", "variable", "sensor", "day", "n_obs", "n_flagged")
        )
        parts.append(part)
    if not parts:
        return pl.DataFrame(schema={k: v for k, v in INDEX_SCHEMA.items()
                                    if k in ("stid", "variable", "sensor", "day", "n_obs", "n_flagged")})
    return pl.concat(parts)


def _windows_rows(key: str, stem: str, receipt: dict) -> list[dict]:
    params = receipt.get("params", {})
    service = receipt.get("service")
    if service != "timeseries":
        return [dict(request_key=key, receipt=stem, service=service, stid=None, vars=None,
                     window_start=None, window_end=None, outcome=receipt.get("outcome"),
                     requested_utc=receipt.get("requested_utc"))]
    start = datetime.fromisoformat(str(params["start"]).replace("Z", "+00:00")).astimezone(timezone.utc)
    end = datetime.fromisoformat(str(params["end"]).replace("Z", "+00:00")).astimezone(timezone.utc)
    stids = params.get("stid") or []
    if isinstance(stids, str):
        stids = [s.strip() for s in stids.split(",") if s.strip()]
    vars_ = params.get("vars") or []
    if isinstance(vars_, str):
        vars_ = [v.strip() for v in vars_.split(",") if v.strip()]
    return [
        dict(request_key=key, receipt=stem, service=service, stid=stid, vars=sorted(vars_),
             window_start=start, window_end=end, outcome=receipt.get("outcome"),
             requested_utc=receipt.get("requested_utc"))
        for stid in stids
    ]


def build_index(archive, *, rebuild: bool = False) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Index every request the archive holds that is not yet indexed; return
    ``(index, windows)``. Incremental through ``coverage/seen.json``."""
    archive = Path(archive)
    cov = _coverage_dir(archive)
    seen_path, index_path, windows_path = cov / "seen.json", cov / "index.parquet", cov / "windows.parquet"
    seen = set() if rebuild else set(json.loads(seen_path.read_text())) if seen_path.exists() else set()
    index = pl.DataFrame(schema=INDEX_SCHEMA) if rebuild else _read_or_empty(index_path, INDEX_SCHEMA)
    windows = pl.DataFrame(schema=WINDOWS_SCHEMA) if rebuild else _read_or_empty(windows_path, WINDOWS_SCHEMA)
    new_index, new_windows = [], []
    for req in sorted((archive / "requests").glob("*.json")):
        key = req.stem
        receipt_rel = json.loads(req.read_text())["receipt"]
        receipt_path = archive / receipt_rel
        stem = receipt_path.stem
        if stem in seen:
            continue
        receipt = json.loads(receipt_path.read_bytes())
        new_windows.extend(_windows_rows(key, stem, receipt))
        if receipt.get("service") == "timeseries" and receipt.get("outcome") == "success":
            payload, _ = replay(receipt_path)
            for station in payload.get("STATION", []):
                counts = station_daily_counts(station)
                if counts.height:
                    new_index.append(counts.with_columns(pl.lit(key).alias("request_key"),
                                                         pl.lit(stem).alias("receipt")))
            del payload
        seen.add(stem)
    if new_windows:
        windows = pl.concat([windows, pl.DataFrame(new_windows, schema=WINDOWS_SCHEMA)])
        _replace(windows_path, windows)
    if new_index:
        index = pl.concat([index, pl.concat(new_index).select(list(INDEX_SCHEMA))])
        _replace(index_path, index)
    if new_windows or new_index or rebuild or not seen_path.exists():
        tmp = seen_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(sorted(seen)))
        os.replace(tmp, seen_path)
    return index, windows


def water_year_blocks(start_wy: int, end_wy: int, years_per_request: int = 5, *, now=None):
    """Half-open UTC blocks ``[1 Oct, 1 Oct + n years)`` covering water years
    ``start_wy..end_wy`` (WY 2001 starts 2000-10-01); the last block ends at ``now``."""
    now = now or datetime.now(timezone.utc)
    blocks = []
    wy = start_wy
    while wy <= end_wy:
        last = min(wy + years_per_request - 1, end_wy)
        a = datetime(wy - 1, 10, 1, tzinfo=timezone.utc)
        b = min(datetime(last, 10, 1, tzinfo=timezone.utc), now)
        if b > a:
            blocks.append((a, b, f"WY{wy}-{last}"))
        wy = last + 1
    return blocks


def _as_utc(value, default):
    if value in (None, ""):
        return default
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        dt = datetime.fromisoformat(text[:10])
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def covered(windows: pl.DataFrame, stid: str, start: datetime, end: datetime, vars_: list[str]) -> bool:
    """True when one archived request window for ``stid`` spans ``[start, end]`` and
    asked for every variable in ``vars_``."""
    if windows.height == 0:
        return False
    rows = windows.filter(
        (pl.col("stid") == stid)
        & (pl.col("service") == "timeseries")
        & (pl.col("window_start") <= start)
        & (pl.col("window_end") >= end)
    )
    want = set(vars_)
    return any(want <= set(v or []) for v in rows["vars"].to_list())


def plan_requests(
    stations: list[dict],
    start_wy: int,
    end_wy: int,
    *,
    vars_for: dict[str, list[str]],
    windows: pl.DataFrame | None = None,
    archive=None,
    years_per_request: int = 5,
    now=None,
    qc=("on", "on", "off"),
) -> list[dict]:
    """The time-series requests still missing from the archive.

    ``stations`` rows carry ``stid`` and optional ``por_start``/``por_end`` (ISO);
    ``vars_for[stid]`` is the variable list to ask for. Blocks are water-year groups
    clipped to the station's period of record; a block already spanned by an archived
    window that asked for those variables is skipped (``skipped_covered`` is not
    emitted -- callers compare against ``water_year_blocks`` if they want the gaps).
    """
    if windows is None:
        if archive is None:
            raise ValueError("pass windows or archive")
        _, windows = build_index(archive)
    now = now or datetime.now(timezone.utc)
    qc_on, qc_flags, qc_remove = qc
    plan = []
    for st in stations:
        stid = st["stid"]
        vars_ = sorted(vars_for.get(stid) or [])
        if not vars_:
            continue
        por_a = _as_utc(st.get("por_start"), datetime(1900, 1, 1, tzinfo=timezone.utc))
        por_b = _as_utc(st.get("por_end"), now)
        for a, b, label in water_year_blocks(start_wy, end_wy, years_per_request, now=now):
            a2, b2 = max(a, por_a), min(b, por_b, now)
            if b2 <= a2:
                continue
            if covered(windows, stid, a2, b2, vars_):
                continue
            hours = (b2 - a2).total_seconds() / 3600
            plan.append(
                dict(
                    service="timeseries",
                    stid=stid,
                    block=label,
                    params=dict(
                        stid=[stid],
                        vars=vars_,
                        start=a2.isoformat(),
                        end=b2.isoformat(),
                        qc=qc_on,
                        qc_flags=qc_flags,
                        qc_remove_data=qc_remove,
                        showemptystations=1,
                    ),
                    station_hours=round(hours, 1),
                )
            )
    return plan


def water_year_of(day: pl.Expr) -> pl.Expr:
    return pl.when(day.dt.month() >= 10).then(day.dt.year() + 1).otherwise(day.dt.year())


def coverage_report(index: pl.DataFrame, stids: list[str], variables: list[str], *, start_wy: int, end_wy: int) -> pl.DataFrame:
    """stid x water_year x variable -> days_with_obs, days_in_year, fraction, n_flagged,
    with every cell present (zero where nothing came back)."""
    grid = (
        pl.DataFrame({"stid": stids})
        .join(pl.DataFrame({"water_year": list(range(start_wy, end_wy + 1))}), how="cross")
        .join(pl.DataFrame({"variable": variables}), how="cross")
    )
    if index.height:
        have = (
            index.with_columns(water_year_of(pl.col("day")).alias("water_year"))
            .filter(pl.col("n_obs") > 0)
            .group_by("stid", "water_year", "variable")
            .agg(pl.col("day").n_unique().alias("days_with_obs"), pl.col("n_flagged").sum())
        )
        out = grid.join(have, on=["stid", "water_year", "variable"], how="left")
    else:
        out = grid.with_columns(pl.lit(None, pl.UInt32).alias("days_with_obs"), pl.lit(None, pl.UInt32).alias("n_flagged"))
    days_in_year = pl.when(((pl.col("water_year") % 4 == 0) & (pl.col("water_year") % 100 != 0)) | (pl.col("water_year") % 400 == 0)).then(366).otherwise(365)
    return out.with_columns(
        pl.col("days_with_obs").fill_null(0).cast(pl.UInt32),
        pl.col("n_flagged").fill_null(0).cast(pl.UInt32),
        days_in_year.alias("days_in_year"),
    ).with_columns((pl.col("days_with_obs") / pl.col("days_in_year")).alias("fraction")).sort("stid", "variable", "water_year")

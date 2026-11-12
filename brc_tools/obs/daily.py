"""Daily tables from a canonical Synoptic archive, one archived object at a time.

This is the time-zone boundary: archived observation times are tz-aware UTC, the
daily table carries a plain ``day`` date and says which day basis made it (``utc``,
or ``mst`` = fixed UTC-7, never daylight time). Downstream analysis is UTC-naive.

Values with a non-empty QC flag list are dropped from the statistics under the policy
named in the row (``drop_any_flag_v1``) and counted in ``n_flagged`` so the choice is
visible. Units are the payload's own ``UNITS`` string plus an SI conversion through
``brc_tools.obs.units.convert``; a unit that module does not know yields null SI
columns and the verbatim unit, never a guess.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

import polars as pl

from .archive import replay
from .coverage import build_index, utc_times, variable_of
from .units import convert

QC_POLICY = "drop_any_flag_v1"
BASES = {"utc": "UTC", "mst": "Etc/GMT+7"}

DAILY_SCHEMA = {
    "stid": pl.String,
    "variable": pl.String,
    "sensor": pl.String,
    "depth_cm": pl.Float32,
    "day": pl.Date,
    "day_basis": pl.String,
    "n_obs": pl.UInt32,
    "n_flagged": pl.UInt32,
    "n_used": pl.UInt32,
    "mean": pl.Float64,
    "min": pl.Float64,
    "max": pl.Float64,
    "first_time": pl.Datetime("us", "UTC"),
    "last_time": pl.Datetime("us", "UTC"),
    "unit": pl.String,
    "unit_si": pl.String,
    "mean_si": pl.Float64,
    "min_si": pl.Float64,
    "max_si": pl.Float64,
    "qc_policy": pl.String,
    "request_key": pl.String,
    "receipt": pl.String,
    "requested_utc": pl.String,
}


def depth_of(variable: str, sensor: str, sensor_meta: dict | None) -> float | None:
    """Sensor depth in cm from Synoptic ``SENSOR_VARIABLES`` metadata when it carries
    one (``position`` in metres, negative below ground). SNOTEL soil sensors carry none;
    the experiment maps those from NRCS metadata instead, so None here is honest."""
    if not variable.startswith("soil") or not sensor_meta:
        return None
    for key in ("position", "depth", "height"):
        value = sensor_meta.get(key)
        if value in (None, ""):
            continue
        try:
            metres = float(value)
        except (TypeError, ValueError):
            continue
        return round(abs(metres) * 100.0, 1)
    return None


def _si(frame: pl.DataFrame) -> pl.DataFrame:
    """Add unit_si / *_si columns row by row (the frame is daily, so this is small)."""
    units_si, means, mins, maxs = [], [], [], []
    for unit, mean, lo, hi in zip(frame["unit"], frame["mean"], frame["min"], frame["max"]):
        m, u, status = convert(mean, unit) if mean is not None else (None, None, "missing")
        if status != "converted":
            units_si.append(None); means.append(None); mins.append(None); maxs.append(None)
            continue
        units_si.append(u); means.append(m)
        mins.append(convert(lo, unit)[0] if lo is not None else None)
        maxs.append(convert(hi, unit)[0] if hi is not None else None)
    return frame.with_columns(
        pl.Series("unit_si", units_si, dtype=pl.String),
        pl.Series("mean_si", means, dtype=pl.Float64),
        pl.Series("min_si", mins, dtype=pl.Float64),
        pl.Series("max_si", maxs, dtype=pl.Float64),
    )


def station_daily(station: dict, units: dict, *, day_basis: str = "utc") -> pl.DataFrame:
    """Daily statistics for every sensor of one station of a replayed payload."""
    if day_basis not in BASES:
        raise ValueError(f"day_basis must be one of {sorted(BASES)}")
    obs = station.get("OBSERVATIONS", {})
    times = obs.get("date_time", [])
    cols = [c for c in DAILY_SCHEMA if c not in ("request_key", "receipt", "requested_utc")]
    empty = pl.DataFrame(schema={c: DAILY_SCHEMA[c] for c in cols})
    if not times:
        return empty
    t_utc = utc_times(times)
    day = t_utc.dt.convert_time_zone(BASES[day_basis]).dt.date().alias("day")
    qc = station.get("QC", {}) or {}
    sensor_vars = station.get("SENSOR_VARIABLES", {}) or {}
    parts = []
    for sensor, values in obs.items():
        if sensor == "date_time" or not isinstance(values, list) or len(values) != len(times):
            continue
        variable = variable_of(sensor)
        value = pl.Series("value", values, dtype=pl.Float64, strict=False)
        flags = qc.get(sensor) or []
        flagged = (
            pl.Series("flagged", [bool(f) for f in flags], dtype=pl.Boolean)
            if len(flags) == len(times)
            else pl.Series("flagged", [False] * len(times), dtype=pl.Boolean)
        )
        frame = pl.DataFrame([t_utc.alias("time"), day, value, flagged])
        used = pl.col("value").is_not_null() & ~pl.col("flagged")
        agg = (
            frame.group_by("day")
            .agg(
                pl.col("value").is_not_null().sum().cast(pl.UInt32).alias("n_obs"),
                pl.col("flagged").sum().cast(pl.UInt32).alias("n_flagged"),
                used.sum().cast(pl.UInt32).alias("n_used"),
                pl.col("value").filter(used).mean().alias("mean"),
                pl.col("value").filter(used).min().alias("min"),
                pl.col("value").filter(used).max().alias("max"),
                pl.col("time").filter(used).min().alias("first_time"),
                pl.col("time").filter(used).max().alias("last_time"),
            )
            .with_columns(
                pl.lit(station["STID"]).alias("stid"),
                pl.lit(variable).alias("variable"),
                pl.lit(sensor).alias("sensor"),
                pl.lit(depth_of(variable, sensor, (sensor_vars.get(variable) or {}).get(sensor)), pl.Float32).alias("depth_cm"),
                pl.lit(day_basis).alias("day_basis"),
                pl.lit(units.get(variable), pl.String).alias("unit"),
                pl.lit(QC_POLICY).alias("qc_policy"),
            )
        )
        parts.append(_si(agg).select(cols))
    return pl.concat(parts) if parts else empty


def aggregate_object(receipt_path, *, day_basis: str = "utc") -> pl.DataFrame:
    """Daily rows for every station in one archived request (receipt path)."""
    receipt_path = Path(receipt_path)
    payload, receipt = replay(receipt_path)
    units = payload.get("UNITS", {}) or {}
    frames = [station_daily(s, units, day_basis=day_basis) for s in payload.get("STATION", [])]
    frames = [f for f in frames if f.height]
    if not frames:
        return pl.DataFrame(schema=DAILY_SCHEMA)
    return pl.concat(frames).with_columns(
        pl.lit(None, pl.String).alias("request_key"),
        pl.lit(receipt_path.stem).alias("receipt"),
        pl.lit(receipt.get("requested_utc"), pl.String).alias("requested_utc"),
    ).select(list(DAILY_SCHEMA))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _write(path: Path, frame: pl.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".pending-", suffix=".parquet")
    os.close(fd)
    frame.write_parquet(name, compression="zstd")
    os.replace(name, path)


def build_daily(archive, out_dir, *, stids: list[str] | None = None, day_basis=("utc", "mst"), windows: pl.DataFrame | None = None, log=print) -> dict:
    """Write ``out_dir/<basis>/<stid>.parquet`` for every station the archive's
    time-series requests touch (or ``stids``), one archived object at a time.

    Part files land in ``out_dir/<basis>/parts/<receipt>.parquet`` first (resumable:
    an existing part is not recomputed), then each station's parts are concatenated and
    overlapping windows de-duplicated (the later ``requested_utc`` wins per
    (sensor, day)). A ``manifest.json`` records parts and sha256 per station file."""
    archive, out_dir = Path(archive), Path(out_dir)
    if isinstance(day_basis, str):
        day_basis = (day_basis,)
    if windows is None:
        _, windows = build_index(archive)
    ts = windows.filter((pl.col("service") == "timeseries") & (pl.col("outcome") == "success"))
    if stids is not None:
        ts = ts.filter(pl.col("stid").is_in(list(stids)))
    receipts = sorted(set(ts["receipt"].to_list()))
    receipt_paths = {s: archive / "receipts" / f"{s}.json" for s in receipts}
    manifest = {"archive": str(archive), "qc_policy": QC_POLICY, "bases": {}}
    for basis in day_basis:
        parts_dir = out_dir / basis / "parts"
        parts_dir.mkdir(parents=True, exist_ok=True)
        for stem in receipts:
            part = parts_dir / f"{stem}.parquet"
            if part.exists():
                continue
            frame = aggregate_object(receipt_paths[stem], day_basis=basis)
            if stids is not None:
                frame = frame.filter(pl.col("stid").is_in(list(stids)))
            _write(part, frame)
            log(f"[daily/{basis}] {stem[:12]} -> {frame.height} rows")
        # one station at a time: scan only the parts that mention it
        per_station = {}
        for stem in receipts:
            for stid in ts.filter(pl.col("receipt") == stem)["stid"].to_list():
                per_station.setdefault(stid, []).append(stem)
        files = {}
        for stid, stems in sorted(per_station.items()):
            lazy = [pl.scan_parquet(parts_dir / f"{s}.parquet").filter(pl.col("stid") == stid) for s in stems]
            frame = (
                pl.concat(lazy).collect()
                .sort("requested_utc", descending=True)
                .unique(subset=["stid", "sensor", "day", "day_basis"], keep="first")
                .sort("sensor", "day")
            )
            out = out_dir / basis / f"{stid}.parquet"
            _write(out, frame)
            files[stid] = dict(rows=frame.height, parts=stems, sha256=_sha256(out))
        manifest["bases"][basis] = files
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True))
    return manifest

"""Synoptic research path: archive before parsing; explicit long observations."""

from __future__ import annotations

import contextlib
import importlib.metadata
import io
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from .archive import atomic, digest, encode, preserve, replay
from .budget import AcquisitionStopped

#: Synoptic's documented hard cap for one Time Series request (station count x hours).
MAX_STATION_HOURS = 100_000
#: The pilot default; a historical pull passes a larger ``max_station_hours``.
DEFAULT_STATION_HOURS = 5000

SCHEMA = {
    "stid": pl.String,
    "time": pl.Datetime("us", "UTC"),
    "variable": pl.String,
    "sensor": pl.String,
    "value": pl.Float64,
    "raw_value": pl.String,
    "unit": pl.String,
    "qc": pl.String,
    "sensor_metadata": pl.String,
    "status": pl.String,
}


def utc(value):
    t = (
        datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if not isinstance(value, datetime)
        else value
    )
    if t.tzinfo is None:
        raise ValueError("time must carry an explicit UTC offset")
    return t.astimezone(timezone.utc)


def long_frame(payload):
    rows = []
    for s in payload.get("STATION", []):
        obs = s.get("OBSERVATIONS", {})
        times = obs.get("date_time", [])
        sensor_vars = s.get("SENSOR_VARIABLES", {})
        for sensor, values in obs.items():
            if sensor == "date_time":
                continue
            var = re.sub(r"_(?:set|value)_\d+d?$", "", sensor)
            if not isinstance(values, list) or len(values) != len(times):
                raise ValueError("observation/time array mismatch; payload retained")
            flags = s.get("QC", {}).get(sensor, [])
            if flags and len(flags) != len(times):
                raise ValueError("QC/time array mismatch; payload retained")
            for i, (t, v) in enumerate(zip(times, values)):
                try:
                    dt = utc(t)
                    value = (
                        float(v)
                        if v is not None and not isinstance(v, (dict, list))
                        else None
                    )
                    status = (
                        "missing"
                        if v is None
                        else ("nonnumeric" if value is None else "reported")
                    )
                except (ValueError, TypeError):
                    dt, value, status = None, None, "invalid_input"
                rows.append(
                    dict(
                        stid=s["STID"],
                        time=dt,
                        variable=var,
                        sensor=sensor,
                        value=value,
                        raw_value=json.dumps(v),
                        unit=payload.get("UNITS", {}).get(var),
                        qc=json.dumps(flags[i]) if flags else None,
                        sensor_metadata=json.dumps(
                            sensor_vars.get(var, {}).get(sensor)
                        ),
                        status=status,
                    )
                )
    return pl.DataFrame(rows, schema=SCHEMA)


@dataclass
class SynopticResult:
    payload: dict
    frame: pl.DataFrame
    receipt: dict
    path: Path


def metadata_frame(payload):
    """Generic metadata only; radius, eligibility, bands and splits belong to callers."""
    rows = []
    for station in payload.get("STATION", []):

        def number(name, scale=1):
            try:
                return float(station[name]) * scale
            except (ValueError, TypeError, KeyError):
                return None

        rows.append(
            dict(
                stid=station.get("STID"),
                network_id=str(station.get("MNET_ID")),
                elevation_m=number("ELEVATION", 0.3048),
                elevation_dem_m=number("ELEV_DEM", 0.3048),
                latitude=number("LATITUDE"),
                longitude=number("LONGITUDE"),
                metadata=json.dumps(station),
            )
        )
    return pl.DataFrame(
        rows,
        schema={
            "stid": pl.String,
            "network_id": pl.String,
            "elevation_m": pl.Float64,
            "elevation_dem_m": pl.Float64,
            "latitude": pl.Float64,
            "longitude": pl.Float64,
            "metadata": pl.String,
        },
    )


def result(path):
    payload, receipt = replay(path)
    frame = (
        long_frame(payload)
        if receipt["service"] == "timeseries"
        else metadata_frame(payload)
        if receipt["service"] == "metadata"
        else pl.DataFrame(payload.get("MNET", []), infer_schema_length=None)
    )
    return SynopticResult(payload, frame, receipt, Path(path))


def normalize_params(service, params):
    """The request parameters as the archive keys them: credentials refused, explicit
    station and variable lists required for a time series, times as UTC ISO strings."""
    if service not in {"metadata", "networks", "timeseries"}:
        raise ValueError("unsupported service")
    params = dict(params)
    if any(re.search(r"token|key|password", k, re.I) for k in params):
        raise ValueError(
            "use SynopticPy credential configuration, not request parameters"
        )
    if service == "timeseries":
        if not params.get("stid") or not params.get("vars"):
            raise ValueError("explicit station and variable lists required")
        start, end = utc(params["start"]), utc(params["end"])
        params.update(start=start.isoformat(), end=end.isoformat())
    return params


def request_key(service, params):
    """The archive's request index key (``requests/<key>.json``) for a request."""
    params = normalize_params(service, params)
    return digest(encode({"service": service, "params": params, "version": 1}))


def receipt_of(archive, service, params):
    """The receipt path an identical earlier request left in the archive, or None."""
    index = Path(archive) / "requests" / f"{request_key(service, params)}.json"
    if not index.exists():
        return None
    return Path(archive) / json.loads(index.read_text())["receipt"]


def fetch(
    service,
    params,
    *,
    archive,
    budget,
    max_station_hours=DEFAULT_STATION_HOURS,
    parse=True,
):
    """Replay an identical archived request, else fetch once under ``budget``.

    ``max_station_hours`` bounds one time-series request (stations x hours); the
    default is the pilot's 5000 and the ceiling is Synoptic's 100,000. ``parse=False``
    skips the long-frame parse (one Python dict per observation), which a 5-year hourly
    station request would not survive on a small host; the receipt and path still come
    back and ``result(path)`` parses later if wanted.
    """
    params = normalize_params(service, params)
    if service == "timeseries":
        if not 1 <= max_station_hours <= MAX_STATION_HOURS:
            raise ValueError(
                f"max_station_hours must lie in 1..{MAX_STATION_HOURS} (Synoptic's cap)"
            )
        start, end = utc(params["start"]), utc(params["end"])
        hours = (end - start).total_seconds() / 3600
        if hours <= 0 or hours * len(params["stid"]) > max_station_hours:
            raise ValueError(
                f"request exceeds {max_station_hours} station-hours or has an invalid window"
            )
    key = digest(encode({"service": service, "params": params, "version": 1}))
    index = Path(archive) / "requests" / f"{key}.json"
    if index.exists():
        path = Path(archive) / json.loads(index.read_text())["receipt"]
        return result(path) if parse else unparsed(path)
    with (
        budget.transport(),
        contextlib.redirect_stdout(io.StringIO()),
        contextlib.redirect_stderr(io.StringIO()),
    ):
        # SynopticPy's import-time validation request is counted by the transport.
        import synoptic

        cls = {
            "metadata": synoptic.Metadata,
            "networks": synoptic.Networks,
            "timeseries": synoptic.TimeSeries,
        }[service]
        wire_params = dict(params)
        if service == "timeseries":
            wire_params.update(start=utc(params["start"]), end=utc(params["end"]))
        try:
            req = cls(**wire_params, verbose=False)
        except Exception as exc:
            raise AcquisitionStopped(
                f"{type(exc).__name__}; no automatic retry"
            ) from None
        versions = {
            name: importlib.metadata.version(name) for name in ("SynopticPy", "polars")
        }
        path = preserve(archive, req.json, service, params, versions)
        atomic(index, encode({"receipt": str(path.relative_to(archive))}))
    return result(path) if parse else unparsed(path)


def unparsed(path):
    """A SynopticResult carrying only the receipt and its path (no payload decode)."""
    path = Path(path)
    receipt = json.loads(path.read_bytes())
    return SynopticResult(None, None, receipt, path)

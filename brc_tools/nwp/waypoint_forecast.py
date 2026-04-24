"""Build HRRR waypoint-forecast JSON payloads for the BasinWX website."""

from __future__ import annotations

import datetime as dt
from typing import Iterable

import numpy as np
import xarray as xr

from brc_tools.nwp.derived import add_wind_fields, pa_to_hpa, temp_K_to_C
from brc_tools.nwp.point_extract import extract_point_series, valid_times_iso
from brc_tools.nwp.source import NWPSource, load_lookups

DEFAULT_REGION = "uinta_basin"
DEFAULT_FORECAST_HOURS = tuple(range(0, 19))

SOURCE_VARIABLES = [
    "temp_2m",
    "dewpoint_2m",
    "wind_u_10m",
    "wind_v_10m",
    "rh_2m",
    "mslp",
    "precip_1hr",
]

FIELD_SPECS: dict[str, dict[str, object]] = {
    "temp_2m_c": {
        "source": "temp_2m",
        "label": "Temperature",
        "units": "Celsius",
        "precision": 1,
        "transform": "K_to_C",
    },
    "dewpoint_2m_c": {
        "source": "dewpoint_2m",
        "label": "Dewpoint",
        "units": "Celsius",
        "precision": 1,
        "transform": "K_to_C",
    },
    "wind_speed_10m_ms": {
        "source": "wind_speed_10m",
        "label": "Wind Speed",
        "units": "m/s",
        "precision": 1,
        "transform": None,
    },
    "wind_dir_10m_deg": {
        "source": "wind_dir_10m",
        "label": "Wind Direction",
        "units": "deg_true",
        "precision": 0,
        "transform": None,
    },
    "rh_2m_pct": {
        "source": "rh_2m",
        "label": "Relative Humidity",
        "units": "percent",
        "precision": 0,
        "transform": None,
    },
    "mslp_hpa": {
        "source": "mslp",
        "label": "Mean Sea-Level Pressure",
        "units": "hPa",
        "precision": 1,
        "transform": "pa_to_hpa",
    },
    "rainfall_1h_mm": {
        "source": "precip_1hr",
        "label": "Rainfall",
        "units": "mm",
        "precision": 1,
        "transform": None,
    },
}


def fetch_waypoint_dataset(
    *,
    init_time: dt.datetime,
    forecast_hours: Iterable[int],
    region: str = DEFAULT_REGION,
    source: NWPSource | None = None,
) -> xr.Dataset:
    """Fetch the HRRR surface variables needed for the waypoint payload."""
    src = source or NWPSource("hrrr")
    ds = src.fetch(
        init_time=init_time,
        forecast_hours=list(forecast_hours),
        variables=SOURCE_VARIABLES,
        region=region,
    )
    return add_wind_fields(ds)


def build_waypoint_payload(
    ds: xr.Dataset,
    *,
    group: str,
    init_time: dt.datetime,
    forecast_hours: Iterable[int],
    region: str = DEFAULT_REGION,
    field_specs: dict[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    """Serialise a HRRR dataset into the BasinWX waypoint-forecast JSON shape."""
    lookups = load_lookups()
    group_cfg = lookups.get("waypoint_groups", {}).get(group)
    if group_cfg is None:
        raise ValueError(f"Unknown waypoint group {group!r}")
    all_waypoints = lookups.get("waypoints", {})

    specs = field_specs or FIELD_SPECS
    init_utc = _ensure_utc(init_time)
    hours = [int(h) for h in forecast_hours]

    stations_out: list[dict[str, object]] = []
    for wp_name in group_cfg:
        wp = all_waypoints[wp_name]
        raw_series = extract_point_series(
            ds,
            wp["lat"],
            wp["lon"],
            variables=SOURCE_VARIABLES + ["wind_speed_10m", "wind_dir_10m"],
        )
        forecasts = _convert_series(raw_series, specs)
        stations_out.append(
            {
                "id": wp_name,
                "name": wp_name.replace("_", " ").title(),
                "lat": float(wp["lat"]),
                "lon": float(wp["lon"]),
                "elevation_m": float(wp.get("elevation_m", float("nan")))
                if wp.get("elevation_m") is not None
                else None,
                "reference_stid": wp.get("reference_stid"),
                "forecasts": forecasts,
            }
        )

    variable_meta = {
        name: {
            "label": spec["label"],
            "units": spec["units"],
            "precision": spec["precision"],
        }
        for name, spec in specs.items()
    }

    payload: dict[str, object] = {
        "model": "hrrr",
        "product": "waypoint_forecast",
        "group": group,
        "region": region,
        "init_time": _isoformat_utc(init_utc),
        "generated_at": _isoformat_utc(dt.datetime.now(dt.timezone.utc)),
        "forecast_hours": hours,
        "valid_times": valid_times_iso(ds),
        "variables": variable_meta,
        "stations": stations_out,
    }
    return payload


def _convert_series(
    raw: dict[str, list[float | None]],
    specs: dict[str, dict[str, object]],
) -> dict[str, list[float | None]]:
    out: dict[str, list[float | None]] = {}
    for output_name, spec in specs.items():
        source = spec["source"]
        series = raw.get(source)
        if series is None:
            continue
        transform = spec.get("transform")
        precision = int(spec.get("precision", 1))
        converted: list[float | None] = []
        for value in series:
            if value is None:
                converted.append(None)
                continue
            if transform == "K_to_C":
                converted.append(round(float(temp_K_to_C(value)), precision))
            elif transform == "pa_to_hpa":
                converted.append(round(float(pa_to_hpa(value)), precision))
            else:
                converted.append(round(float(value), precision))
        out[output_name] = converted
    return out


def _ensure_utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def _isoformat_utc(value: dt.datetime) -> str:
    return _ensure_utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")

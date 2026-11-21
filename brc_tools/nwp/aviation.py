"""Airport-relative HRRR wind payloads for the BasinWX aviation page.

Fetches HRRR 10 m wind and gust through ``NWPSource``, which keeps the native 15-min
time axis of the ``subh`` product (GH #82) and pins the instantaneous 10 m wind there
(``subh`` also ships 5-min averages of it).
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Iterable

import numpy as np
import xarray as xr

from brc_tools.nwp._crop import nearest_point_value
from brc_tools.nwp.derived import (
    KT_PER_MS,
    crosswind_kt,
    headwind_kt,
    rotate_winds_to_earth,
    wind_direction,
    wind_speed,
)
from brc_tools.nwp.source import NWPSource, load_lookups

LOG = logging.getLogger(__name__)

DEFAULT_PRODUCT = "subh"
DEFAULT_MAX_FXX = 6
AIRPORT_VARIABLES = ("wind_u_10m", "wind_v_10m", "wind_gust_10m")


def fetch_airport_winds(
    *,
    init_time: dt.datetime,
    forecast_hours: Iterable[int],
    product: str = DEFAULT_PRODUCT,
) -> xr.Dataset:
    """Fetch HRRR 10 m U/V plus surface gust across a list of forecast hours.

    ``subh`` comes back on its native axis (f00 analysis, then 4 x 15 min per hour);
    ``sfc`` one step per hour. Winds are rotated to earth-relative by the grid the
    GRIB declares (runway math and "deg_true" need east/north).
    """
    ds = NWPSource("hrrr").fetch(
        init_time=init_time,
        forecast_hours=list(forecast_hours),
        variables=list(AIRPORT_VARIABLES),
        product=product,
    )
    return rotate_winds_to_earth(ds, "wind_u_10m", "wind_v_10m").sortby("time")


def build_airport_crosswind_payload(
    ds: xr.Dataset,
    *,
    airport: str,
    init_time: dt.datetime,
    product: str = DEFAULT_PRODUCT,
) -> dict[str, object]:
    """Serialise airport-relative wind data into the BasinWX aviation JSON shape."""
    airport_cfg = _airport_config(airport)
    lat = float(airport_cfg["lat"])
    lon = float(airport_cfg["lon"])
    runway_headings = [int(h) for h in airport_cfg["runway_headings_deg"]]

    pt = nearest_point_value(ds, lat, lon, method="kdtree_2d")

    u = np.asarray(_first_var(pt, ("wind_u_10m", "u10", "UGRD")).values)
    v = np.asarray(_first_var(pt, ("wind_v_10m", "v10", "VGRD")).values)
    gust_ms = _get_gust_ms(pt)

    speed_kt = wind_speed(u, v) * KT_PER_MS
    dir_deg = wind_direction(u, v)

    variables = {
        "wind_speed_kt": {"label": "Wind Speed", "units": "kt", "precision": 1},
        "wind_dir_deg": {"label": "Wind Direction", "units": "deg_true", "precision": 0},
        "gust_kt": {"label": "Gust", "units": "kt", "precision": 1},
    }
    series: dict[str, list[float | None]] = {
        "wind_speed_kt": _round_series(speed_kt, 1),
        "wind_dir_deg": _round_series(dir_deg, 0),
        "gust_kt": _round_series(
            gust_ms * KT_PER_MS if gust_ms is not None else _nan_like(u),
            1,
        ),
    }

    for heading in runway_headings:
        cw_key = f"crosswind_kt_{heading:03d}"
        hw_key = f"headwind_kt_{heading:03d}"
        variables[cw_key] = {
            "label": f"Crosswind (Rwy {heading // 10:02d})",
            "units": "kt",
            "precision": 1,
        }
        variables[hw_key] = {
            "label": f"Headwind (Rwy {heading // 10:02d})",
            "units": "kt",
            "precision": 1,
        }
        series[cw_key] = _round_series(crosswind_kt(u, v, heading), 1)
        series[hw_key] = _round_series(headwind_kt(u, v, heading), 1)

    valid_times, forecast_minutes = _time_axes(pt, init_time)

    return {
        "model": "hrrr_subh" if product == "subh" else "hrrr",
        "product": "aviation_crosswind",
        "airport": airport,
        "name": airport_cfg.get("name"),
        "lat": lat,
        "lon": lon,
        "elevation_m": float(airport_cfg.get("elevation_m", 0.0)),
        "runway_headings_deg": runway_headings,
        "init_time": _isoformat_utc(_ensure_utc(init_time)),
        "generated_at": _isoformat_utc(dt.datetime.now(dt.timezone.utc)),
        "valid_times": valid_times,
        "forecast_minutes": forecast_minutes,
        "variables": variables,
        "series": series,
    }


def _airport_config(airport: str) -> dict[str, object]:
    lookups = load_lookups()
    airports = lookups.get("airports", {})
    if airport not in airports:
        raise ValueError(f"Unknown airport {airport!r} in lookups.toml")
    return airports[airport]


def _first_var(pt: xr.Dataset, names: tuple[str, ...]) -> xr.DataArray:
    """The first of ``names`` present: canonical (NWPSource) first, cfgrib names after."""
    for name in names:
        if name in pt.data_vars:
            return pt[name]
    raise KeyError(f"none of {names} in dataset (have {list(pt.data_vars)})")


def _get_gust_ms(pt: xr.Dataset) -> np.ndarray | None:
    for name in ("wind_gust_10m", "gust", "GUST", "i10fg", "fg10"):
        if name in pt.data_vars:
            return np.asarray(pt[name].values)
    return None


def _nan_like(arr: np.ndarray) -> np.ndarray:
    out = np.empty_like(arr, dtype=float)
    out.fill(np.nan)
    return out


def _round_series(values: np.ndarray, precision: int) -> list[float | None]:
    arr = np.atleast_1d(np.asarray(values, dtype=float))
    rounded = np.round(arr, decimals=precision)
    return [
        None if not np.isfinite(v) else float(v)
        for v in rounded
    ]


def _time_axes(
    pt: xr.Dataset, init_time: dt.datetime
) -> tuple[list[str], list[int]]:
    init_utc = _ensure_utc(init_time)
    init_np = np.datetime64(init_utc.replace(tzinfo=None))
    valid_times: list[str] = []
    forecast_minutes: list[int] = []
    if "time" not in pt.coords:
        return valid_times, forecast_minutes
    for value in np.atleast_1d(pt["time"].values):
        valid_times.append(_np_isoz(value))
        delta_min = int((value - init_np) / np.timedelta64(1, "m"))
        forecast_minutes.append(delta_min)
    return valid_times, forecast_minutes


def _np_isoz(value: np.datetime64) -> str:
    seconds = value.astype("datetime64[s]").astype(int)
    return (
        dt.datetime.fromtimestamp(int(seconds), tz=dt.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )


def _ensure_utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def _isoformat_utc(value: dt.datetime) -> str:
    return _ensure_utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")

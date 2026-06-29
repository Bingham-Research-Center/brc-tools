"""Airport-relative HRRR wind payloads for the BasinWX aviation page.

Fetches HRRR surface winds via Herbie directly so the native sub-hourly
(15-min) time axis of the ``subh`` product is preserved.  NWPSource's
normalize_coords replaces the GRIB time coord with a single init+fxx
stamp, which collapses subh output to hourly — this module bypasses that.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Iterable

import numpy as np
import xarray as xr
from herbie import Herbie

from brc_tools.nwp._crop import nearest_point_value
from brc_tools.nwp.derived import crosswind_kt, headwind_kt, wind_direction, wind_speed, KT_PER_MS
from brc_tools.nwp.source import load_lookups

LOG = logging.getLogger(__name__)

DEFAULT_PRODUCT = "subh"
DEFAULT_MAX_FXX = 6
SEARCH_U10 = "UGRD:10 m above ground"
SEARCH_V10 = "VGRD:10 m above ground"
SEARCH_GUST = "GUST:surface"


def fetch_airport_winds(
    *,
    init_time: dt.datetime,
    forecast_hours: Iterable[int],
    product: str = DEFAULT_PRODUCT,
) -> xr.Dataset:
    """Fetch HRRR 10 m U/V plus surface gust across a list of forecast hours.

    Uses Herbie directly so the native time axis (4 × 15-min per hour for
    ``subh``; one hourly step for ``sfc``) is preserved across the concat.
    """
    slices: list[xr.Dataset] = []
    for fxx in forecast_hours:
        H = Herbie(init_time, model="hrrr", product=product, fxx=int(fxx))
        pieces: list[xr.Dataset] = []
        for search in (SEARCH_U10, SEARCH_V10, SEARCH_GUST):
            try:
                piece = H.xarray(search, remove_grib=False)
            except Exception as exc:
                LOG.warning("Herbie fetch failed f%03d %r: %s", int(fxx), search, exc)
                continue
            if isinstance(piece, list):
                piece = xr.merge(piece, compat="override", combine_attrs="drop")
            pieces.append(_clean_dataset(piece))
        if not pieces:
            continue
        slices.append(xr.merge(pieces, compat="override", combine_attrs="drop"))

    if not slices:
        raise RuntimeError(
            f"No HRRR {product} data fetched for init={init_time} "
            f"fxx={list(forecast_hours)}"
        )

    merged = xr.concat(slices, dim="time", combine_attrs="drop")
    return merged.sortby("time")


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

    u = np.asarray(pt["u10"].values if "u10" in pt.data_vars else pt["UGRD"].values)
    v = np.asarray(pt["v10"].values if "v10" in pt.data_vars else pt["VGRD"].values)
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


def _clean_dataset(ds: xr.Dataset) -> xr.Dataset:
    keep = {"time", "valid_time", "step", "latitude", "longitude", "y", "x"}
    drop = [n for n in ds.coords if n not in keep and n not in ds.dims]
    if drop:
        ds = ds.drop_vars(drop, errors="ignore")
    if "step" in ds.coords and "valid_time" in ds.coords:
        ds = ds.drop_vars("step", errors="ignore")
    if "valid_time" in ds.coords and "time" in ds.coords:
        ds = ds.drop_vars("time", errors="ignore").rename({"valid_time": "time"})
    elif "valid_time" in ds.coords:
        ds = ds.rename({"valid_time": "time"})
    if "time" in ds.coords and "time" not in ds.dims:
        ds = ds.expand_dims("time")
    return ds


def _get_gust_ms(pt: xr.Dataset) -> np.ndarray | None:
    for name in ("gust", "GUST", "i10fg", "fg10"):
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

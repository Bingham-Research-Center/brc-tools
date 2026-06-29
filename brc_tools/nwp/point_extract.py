"""Point extraction helpers shared by waypoint and aviation payload builders."""

from __future__ import annotations

import datetime as dt
from typing import Iterable

import numpy as np
import xarray as xr

from brc_tools.nwp._crop import nearest_point_value


def _isfinite(value) -> bool:
    return value is not None and bool(np.isfinite(value))


def _coerce_float(value) -> float | None:
    arr = np.asarray(value)
    if arr.size == 0:
        return None
    if arr.size != 1:
        raise ValueError(f"Expected scalar, got array of shape {arr.shape}")
    scalar = arr.item()
    return float(scalar) if np.isfinite(scalar) else None


def extract_point_series(
    ds: xr.Dataset,
    lat: float,
    lon: float,
    variables: Iterable[str],
    *,
    method: str = "kdtree_2d",
) -> dict[str, list[float | None]]:
    """Extract per-variable time series at the grid point nearest ``(lat, lon)``.

    Returns a dict keyed by variable name; each value is a list aligned with
    the dataset's ``time`` coordinate. Missing variables are returned as
    all-``None`` lists of the same length. Non-finite values become ``None``
    so the payload is JSON-safe.
    """
    pt = nearest_point_value(ds, lat, lon, method=method)
    n_time = int(pt.sizes.get("time", 1))
    out: dict[str, list[float | None]] = {}
    for var in variables:
        if var not in pt.data_vars:
            out[var] = [None] * n_time
            continue
        series: list[float | None] = []
        if "time" in pt[var].dims:
            for t_idx in range(n_time):
                series.append(_coerce_float(pt[var].isel(time=t_idx).values))
        else:
            series.append(_coerce_float(pt[var].values))
        out[var] = series
    return out


def valid_times_iso(ds: xr.Dataset) -> list[str]:
    """Return the dataset's ``time`` coordinate as ISO-Z strings."""
    if "time" not in ds.coords:
        return []
    values = np.atleast_1d(ds["time"].values)
    return [_np_datetime_to_isoz(v) for v in values]


def valid_times_datetime(ds: xr.Dataset) -> list[dt.datetime]:
    """Return the dataset's ``time`` coordinate as tz-naive UTC datetimes."""
    if "time" not in ds.coords:
        return []
    values = np.atleast_1d(ds["time"].values)
    return [_np_datetime_to_utc_naive(v) for v in values]


def _np_datetime_to_utc_naive(value: np.datetime64) -> dt.datetime:
    seconds = value.astype("datetime64[s]").astype(int)
    return dt.datetime.fromtimestamp(int(seconds), tz=dt.timezone.utc).replace(
        tzinfo=None
    )


def _np_datetime_to_isoz(value: np.datetime64) -> str:
    return _np_datetime_to_utc_naive(value).strftime("%Y-%m-%dT%H:%M:%SZ")

"""Shared HRRR access helpers for the minimal proof-of-concept."""

from __future__ import annotations

import datetime as dt
import logging
import os
from pathlib import Path
from typing import Mapping

import numpy as np
import xarray as xr
from herbie import Herbie

LOG = logging.getLogger(__name__)

_GRIB_MAGIC = b"GRIB"
_MIN_GRIB_SIZE = 1000
_DEFAULT_CACHE_DIR = (
    Path(os.environ.get("BRC_TOOLS_HRRR_CACHE", ""))
    if os.environ.get("BRC_TOOLS_HRRR_CACHE")
    else Path(__file__).resolve().parents[2] / "data" / "herbie_cache" / "hrrr"
)


def ensure_cache_dir(cache_dir: str | os.PathLike[str] | None = None) -> Path:
    """Create and return the Herbie cache directory."""
    target = Path(cache_dir).expanduser() if cache_dir else _DEFAULT_CACHE_DIR
    target.mkdir(parents=True, exist_ok=True)
    return target


def setup_herbie(
    init_time: dt.datetime,
    fxx: int,
    *,
    product: str = "sfc",
    cache_dir: str | os.PathLike[str] | None = None,
) -> Herbie:
    """Create a Herbie instance for one HRRR cycle and lead time."""
    return Herbie(
        init_time,
        model="hrrr",
        product=product,
        fxx=int(fxx),
        save_dir=str(ensure_cache_dir(cache_dir)),
        verbose=False,
    )


def get_latest_hrrr_init(
    *,
    now: dt.datetime | None = None,
    product: str = "sfc",
    availability_fxx: int = 1,
    start_lag_hours: int = 2,
    lookback_hours: int = 6,
    cache_dir: str | os.PathLike[str] | None = None,
) -> dt.datetime:
    """Return the most recent HRRR init we can confidently reference."""
    anchor = now or dt.datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    start_hour = anchor - dt.timedelta(hours=start_lag_hours)

    for hours_back in range(lookback_hours):
        candidate = start_hour - dt.timedelta(hours=hours_back)
        try:
            herbie_obj = setup_herbie(
                candidate,
                availability_fxx,
                product=product,
                cache_dir=cache_dir,
            )
        except Exception as exc:  # pragma: no cover - Herbie setup depends on env
            LOG.debug("HRRR candidate setup failed for %s: %s", candidate, exc)
            continue

        if _herbie_candidate_available(herbie_obj):
            LOG.info("Selected HRRR init %s", candidate.strftime("%Y-%m-%d %HZ"))
            return candidate

    raise RuntimeError(
        f"No HRRR {product!r} run found in the last {lookback_hours} hours"
    )


def _herbie_candidate_available(herbie_obj: Herbie) -> bool:
    """Best-effort availability check without downloading a full dataset."""
    for attr_name in ("grib", "idx", "remote_grib", "remote_idx"):
        if getattr(herbie_obj, attr_name, None):
            return True
    return False


def _validate_cached_grib(grib_path: str | os.PathLike[str] | None) -> bool:
    """Return True when a cached GRIB looks usable or does not exist."""
    if grib_path is None:
        return True

    path = Path(grib_path)
    if not path.exists():
        return True

    try:
        stat = path.stat()
        if stat.st_size < _MIN_GRIB_SIZE:
            LOG.warning(
                "HRRR cache invalid: %s too small (%d bytes)",
                path.name,
                stat.st_size,
            )
            return False
        with path.open("rb") as handle:
            if handle.read(4) != _GRIB_MAGIC:
                LOG.warning("HRRR cache invalid: %s missing GRIB header", path.name)
                return False
    except OSError as exc:
        LOG.warning("HRRR cache validation failed for %s: %s", path, exc)
        return False
    return True


def _purge_cached_files(herbie_obj: Herbie) -> None:
    """Delete any cached index/GRIB files for a Herbie object."""
    for attr_name in ("idx", "grib"):
        path = getattr(herbie_obj, attr_name, None)
        if not isinstance(path, (str, os.PathLike)):
            continue
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            continue


def fetch_hour_dataset(
    init_time: dt.datetime,
    fxx: int,
    query_map: Mapping[str, str],
    *,
    product: str = "sfc",
    cache_dir: str | os.PathLike[str] | None = None,
    remove_grib: bool = True,
    retries: int = 2,
) -> xr.Dataset:
    """Fetch one HRRR forecast hour and rename data vars to internal aliases."""
    herbie_obj = setup_herbie(
        init_time,
        fxx,
        product=product,
        cache_dir=cache_dir,
    )

    if not _validate_cached_grib(getattr(herbie_obj, "grib", None)):
        _purge_cached_files(herbie_obj)

    datasets: list[xr.Dataset] = []
    for alias, search_string in query_map.items():
        last_exc: Exception | None = None
        for attempt in range(1, retries + 1):
            try:
                raw_ds = herbie_obj.xarray(search_string, remove_grib=remove_grib)
                renamed = _rename_data_var(raw_ds, alias)
                normalized = _normalize_hour_dataset(renamed, init_time, fxx)
                datasets.append(normalized[[alias]])
                break
            except Exception as exc:  # pragma: no cover - depends on Herbie/network state
                last_exc = exc
                LOG.warning(
                    "HRRR load failed alias=%s f%03d attempt=%d/%d: %s",
                    alias,
                    fxx,
                    attempt,
                    retries,
                    exc,
                )
                if attempt < retries:
                    _purge_cached_files(herbie_obj)
        else:
            LOG.warning("Skipping alias=%s f%03d after %d attempts", alias, fxx, retries)
            if last_exc is not None:
                LOG.debug("Last HRRR exception for %s f%03d: %r", alias, fxx, last_exc)

    if not datasets:
        raise RuntimeError(f"No HRRR variables loaded for f{int(fxx):03d}")

    merged = xr.merge(datasets, compat="override", combine_attrs="drop")
    return _normalize_longitudes(merged)


def fetch_hourly_datasets(
    init_time: dt.datetime,
    query_map: Mapping[str, str],
    *,
    max_fxx: int,
    product: str = "sfc",
    cache_dir: str | os.PathLike[str] | None = None,
    remove_grib: bool = True,
) -> dict[int, xr.Dataset]:
    """Fetch multiple HRRR forecast hours, skipping hours that fail."""
    datasets: dict[int, xr.Dataset] = {}
    for fxx in range(1, max_fxx + 1):
        try:
            datasets[fxx] = fetch_hour_dataset(
                init_time,
                fxx,
                query_map,
                product=product,
                cache_dir=cache_dir,
                remove_grib=remove_grib,
            )
            LOG.info("Fetched HRRR hour f%03d with %d fields", fxx, len(datasets[fxx].data_vars))
        except Exception as exc:  # pragma: no cover - depends on Herbie/network state
            LOG.warning("Skipping HRRR hour f%03d: %s", fxx, exc)
    return datasets


def nearest_grid_index(ds: xr.Dataset, lat: float, lon: float) -> tuple[int, int]:
    """Return nearest `(y_idx, x_idx)` on the HRRR grid."""
    lats = np.asarray(ds.latitude.values)
    lons = np.asarray(ds.longitude.values)
    if np.nanmax(lons) > 180.0:
        lons = ((lons + 180.0) % 360.0) - 180.0

    dist = (lats - lat) ** 2 + (lons - lon) ** 2
    y_idx, x_idx = np.unravel_index(np.nanargmin(dist), dist.shape)
    return int(y_idx), int(x_idx)


def extract_point_values(
    ds: xr.Dataset,
    *,
    y_idx: int,
    x_idx: int,
    aliases: list[str] | None = None,
) -> dict[str, float]:
    """Extract scalar values at one grid point for the requested aliases."""
    values: dict[str, float] = {}
    wanted = aliases or list(ds.data_vars)

    for alias in wanted:
        if alias not in ds.data_vars:
            continue
        arr = ds[alias]
        indexers = {}
        if "time" in arr.dims:
            indexers["time"] = 0
        if "y" in arr.dims:
            indexers["y"] = y_idx
        if "x" in arr.dims:
            indexers["x"] = x_idx

        point = arr.isel(**indexers).squeeze(drop=True)
        if point.size != 1:
            continue

        value = float(np.asarray(point.values).item())
        if np.isfinite(value):
            values[alias] = value

    return values


def extract_nearest_values(
    ds: xr.Dataset,
    lat: float,
    lon: float,
    *,
    aliases: list[str] | None = None,
) -> dict[str, float]:
    """Extract requested values at the nearest HRRR grid point."""
    y_idx, x_idx = nearest_grid_index(ds, lat, lon)
    return extract_point_values(ds, y_idx=y_idx, x_idx=x_idx, aliases=aliases)


def _rename_data_var(ds: xr.Dataset, alias: str) -> xr.Dataset:
    """Rename the first data var in a dataset to a stable alias."""
    if alias in ds.data_vars:
        return ds

    data_vars = list(ds.data_vars)
    if not data_vars:
        raise ValueError(f"No data variables found for alias {alias!r}")
    return ds.rename({data_vars[0]: alias})


def _normalize_hour_dataset(
    ds: xr.Dataset,
    init_time: dt.datetime,
    fxx: int,
) -> xr.Dataset:
    """Normalize coordinates so each fetch is a single valid-time slice."""
    keep_coords = {"time", "latitude", "longitude", "x", "y"}
    drop_names = [name for name in ds.coords if name not in keep_coords]
    if drop_names:
        ds = ds.drop_vars(drop_names, errors="ignore")

    if "time" in ds.dims:
        ds = ds.isel(time=0, drop=True)
    ds = ds.expand_dims("time")

    valid_time = np.array(
        [np.datetime64(init_time + dt.timedelta(hours=int(fxx)))],
        dtype="datetime64[ns]",
    )
    ds = ds.assign_coords(time=("time", valid_time))
    return _normalize_longitudes(ds)


def _normalize_longitudes(ds: xr.Dataset) -> xr.Dataset:
    """Shift 0-360 longitude coordinates into -180..180 when needed."""
    if "longitude" not in ds.coords:
        return ds

    lons = ds.longitude
    try:
        lon_max = float(np.nanmax(np.asarray(lons.values)))
    except (TypeError, ValueError):
        return ds

    if lon_max <= 180.0:
        return ds

    shifted = ((lons + 180.0) % 360.0) - 180.0
    return ds.assign_coords(longitude=shifted)

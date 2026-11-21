"""Coordinate normalization and CF metadata helpers."""

import datetime
import logging

import numpy as np

logger = logging.getLogger(__name__)


def normalize_coords(ds, init_time, fxx):
    """Drop transient coords, expand time dim, stamp valid_time.

    A dataset already on a ``time`` axis (a sub-hourly file, see ``steps_to_time``)
    keeps it: its valid times came from the messages, not from ``init + fxx``.
    """
    keep = {"time", "latitude", "longitude"}
    drop = [n for n in ds.coords if n not in keep]
    if drop:
        ds = ds.drop_vars(drop, errors="ignore")
    if "time" in ds.dims:
        return ds
    valid_time = np.array(
        [np.datetime64(init_time + datetime.timedelta(hours=int(fxx)))]
    )
    if "time" in ds.coords:
        ds = ds.drop_vars("time", errors="ignore")
    if "time" not in ds.dims:
        ds = ds.expand_dims("time")
    ds = ds.assign_coords(time=("time", valid_time))
    return ds


def steps_to_time(ds):
    """Put a sub-hourly file's messages on a ``time`` axis of their own valid times.

    cfgrib stacks one field's 15-min messages along ``step`` with a ``valid_time``
    coordinate beside it (a lone message, e.g. the f00 analysis, has both as scalars).
    The result has ``time`` as a dimension, at the same microsecond resolution the
    hourly path stamps, and no ``step``/``valid_time``.
    """
    if "valid_time" not in ds.coords:
        raise ValueError("sub-hourly message has no valid_time coordinate to build time from")
    valid = ds["valid_time"]
    ds = ds.drop_vars([n for n in ("time",) if n in ds.coords])
    if valid.ndim == 0:
        stamp = np.atleast_1d(valid.values).astype("datetime64[us]")
        return ds.drop_vars(["valid_time", "step"], errors="ignore").expand_dims(time=stamp)
    (dim,) = valid.dims
    ds = ds.assign_coords(time=(dim, valid.values.astype("datetime64[us]")))
    return ds.swap_dims({dim: "time"}).drop_vars(["valid_time", "step"], errors="ignore")


def parse_cf(ds):
    """Parse CF metadata if MetPy is available; pass through otherwise."""
    try:
        import metpy  # noqa: F401
        return ds.metpy.parse_cf()
    except (ImportError, AttributeError):
        return ds

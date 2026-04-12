"""Coordinate normalization and CF metadata helpers."""

import datetime
import logging

import numpy as np

logger = logging.getLogger(__name__)


def normalize_coords(ds, init_time, fxx):
    """Drop transient coords, expand time dim, stamp valid_time."""
    keep = {"time", "latitude", "longitude"}
    drop = [n for n in ds.coords if n not in keep]
    if drop:
        ds = ds.drop_vars(drop, errors="ignore")
    valid_time = np.array(
        [np.datetime64(init_time + datetime.timedelta(hours=int(fxx)))]
    )
    if "time" in ds.coords:
        ds = ds.drop_vars("time", errors="ignore")
    if "time" not in ds.dims:
        ds = ds.expand_dims("time")
    ds = ds.assign_coords(time=("time", valid_time))
    return ds


def parse_cf(ds):
    """Parse CF metadata if MetPy is available; pass through otherwise."""
    try:
        import metpy  # noqa: F401
        return ds.metpy.parse_cf()
    except (ImportError, AttributeError):
        return ds

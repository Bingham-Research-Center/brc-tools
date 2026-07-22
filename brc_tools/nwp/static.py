"""Fetch-once, reuse-forever staging for model fields that do not vary with time.

A model's orography is fixed for the life of a model version, so re-fetching it for
every case date -- or worse, concurrently from several jobs -- is pure waste. It is
also an outright race: :class:`~brc_tools.nwp.NWPSource` asks Herbie for subsets with
``remove_grib=True``, so two processes requesting the *same* field land on the same
cache filename and one deletes the GRIB while the other is still reading it::

    FileNotFoundError: .../subset_7bef8322__hrrr.t06z.wrfsfcf00.grib2

Herbie fetches are guarded by an inter-process lock, but that lock defaults to
``tempfile.gettempdir()`` -- which is **node-local**, so it does not serialize jobs
spread across compute nodes. The cache here is keyed by ``(model, bbox)`` and its lock
lives beside the cache on shared storage, so concurrent jobs on different nodes either
reuse a staged file or serialize behind one download.

Verified for HRRR: terrain over the Uinta Basin was bit-identical between 2026-02-22
and 2026-07-15 (max |dz| = 0 m over the 6,264 shared grid points). The cache key does
**not** encode a model version, so purge ``BRC_TOOLS_STATIC_DIR`` after a model
upgrade that moves the grid or the orography.
"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

import xarray as xr

logger = logging.getLogger(__name__)

TERRAIN_ALIAS = "terrain_height"


def static_cache_dir(explicit: str | os.PathLike | None = None) -> Path:
    """Where staged time-invariant fields live.

    ``explicit`` > ``BRC_TOOLS_STATIC_DIR`` > a ``static/`` sibling of the Herbie
    cache > ``~/.cache/brc_tools/static``. Prefer somewhere shared and persistent:
    the whole point is that it outlives a single job and a single case date.
    """
    if explicit is not None:
        return Path(explicit)
    env = os.environ.get("BRC_TOOLS_STATIC_DIR")
    if env:
        return Path(env)
    herbie = os.environ.get("BRC_TOOLS_HERBIE_CACHE")
    base = Path(herbie).parent if herbie else Path.home() / ".cache" / "brc_tools"
    return base / "static"


def _cache_key(model: str, bbox) -> str:
    raw = f"{model}|" + ",".join(f"{float(v):.4f}" for v in bbox)
    return hashlib.sha1(raw.encode()).hexdigest()[:10]


def terrain_cache_path(model: str, bbox, *, cache_dir=None) -> Path:
    """Path this ``(model, bbox)`` pair stages its terrain to."""
    return static_cache_dir(cache_dir) / f"{model}_terrain_{_cache_key(model, bbox)}.nc"


def load_terrain(
    model: str,
    bbox,
    *,
    init_time,
    cache_dir=None,
    source=None,
    refresh: bool = False,
) -> xr.Dataset:
    """Return the model's static terrain over ``bbox``, downloading only on a miss.

    Parameters
    ----------
    model, bbox
        Model key and ``(sw_lat, sw_lon, ne_lat, ne_lon)``, together the cache key.
    init_time
        Any cycle that has an f00 -- used only when the cache misses. Terrain does
        not vary, so which cycle you pass does not affect the result.
    source
        An existing :class:`~brc_tools.nwp.NWPSource`; one is built if omitted.
    refresh
        Re-download and overwrite the staged copy (use after a model upgrade).
    """
    import fasteners

    path = terrain_cache_path(model, bbox, cache_dir=cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists() and not refresh:
        logger.debug("terrain cache hit: %s", path)
        return xr.open_dataset(path)

    # Lock beside the cache (shared storage) so jobs on different nodes serialize.
    lock = fasteners.InterProcessLock(str(path.with_suffix(".lock")))
    with lock:
        if path.exists() and not refresh:  # staged while we waited
            return xr.open_dataset(path)
        from brc_tools.nwp import NWPSource
        src = source if source is not None else NWPSource(model)
        logger.info("staging %s terrain -> %s", model, path)
        ds = src.fetch(init_time=init_time, forecast_hours=[0],
                       variables=[TERRAIN_ALIAS], bbox=bbox)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        ds.to_netcdf(tmp)
        os.replace(tmp, path)  # atomic: readers never see a partial file
    return xr.open_dataset(path)

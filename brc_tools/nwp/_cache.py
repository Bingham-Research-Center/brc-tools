"""GRIB cache validation and cleanup helpers."""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_GRIB_MAGIC = b"GRIB"
_MIN_GRIB_SIZE = 1000


def validate_cached_grib(grib_path, min_size_bytes=_MIN_GRIB_SIZE) -> bool:
    """Return True if file is valid or missing (Herbie will download fresh).
    Return False if file exists but is corrupt or truncated."""
    if grib_path is None:
        return True
    p = Path(grib_path)
    if not p.exists():
        return True
    try:
        if p.stat().st_size < min_size_bytes:
            logger.warning("GRIB too small: %s (%d bytes)", p.name, p.stat().st_size)
            return False
        with open(p, "rb") as f:
            if f.read(4) != _GRIB_MAGIC:
                logger.warning("GRIB bad magic: %s", p.name)
                return False
        return True
    except OSError as e:
        logger.warning("GRIB validation failed for %s: %s", p, e)
        return False


def purge_cached_files(herbie_inst):
    """Remove cached GRIB and index files for a Herbie instance."""
    for attr in ("idx", "grib"):
        path = getattr(herbie_inst, attr, None)
        if isinstance(path, (str, os.PathLike)) and os.path.exists(str(path)):
            try:
                os.remove(path)
            except FileNotFoundError:
                pass

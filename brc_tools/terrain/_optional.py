"""Lazy imports for the optional raster / hydrology stack."""
from __future__ import annotations

import importlib

EXTRA = "terrain"
HINT = ("pip install 'brc-tools[terrain]'  (rasterio, richdem, pyproj), or use the "
        "terrain-2026 conda env: environment-terrain.yml")


def require(module: str):
    """Import an optional module or raise ``ImportError`` naming the extra that has it."""
    try:
        return importlib.import_module(module)
    except ImportError as exc:  # noqa: BLE001
        raise ImportError(f"{module!r} is needed by brc_tools.terrain: {HINT}") from exc

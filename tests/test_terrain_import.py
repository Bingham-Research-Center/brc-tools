"""The terrain package must import without its optional raster stack."""

from __future__ import annotations

import importlib
import sys

import pytest


def test_package_imports_without_optional_deps(monkeypatch):
    for name in ("rasterio", "richdem", "pyproj"):
        monkeypatch.setitem(sys.modules, name, None)      # `import name` now raises ImportError
    for mod in ("brc_tools.terrain", "brc_tools.terrain.dem", "brc_tools.terrain.d8",
                "brc_tools.terrain.catchments", "brc_tools.terrain.gates", "brc_tools.terrain.validate"):
        sys.modules.pop(mod, None)
        importlib.import_module(mod)


def test_require_names_the_extra(monkeypatch):
    from brc_tools.terrain import _optional
    monkeypatch.setitem(sys.modules, "richdem", None)
    with pytest.raises(ImportError, match="brc-tools\\[terrain\\]"):
        _optional.require("richdem")

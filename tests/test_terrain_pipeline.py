"""scripts/terrain_pipeline.py end to end on a synthetic bowl round the Ouray waypoint (the DEM
mosaic is replaced; needs richdem and pyproj, so it runs in the terrain-2026 env)."""

from __future__ import annotations

import csv
import importlib.util
import json
import sys
import tomllib
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("richdem")
pytest.importorskip("pyproj")

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def pipeline(monkeypatch):
    """The script as a module, with ``dem.mosaic_tiles`` returning a 41 x 41 bowl at 100 m whose
    floor holds the sink and whose river leaves east; the call's resolved cache dir is kept."""
    spec = importlib.util.spec_from_file_location("_terrain_pipeline", ROOT / "scripts" / "terrain_pipeline.py")
    tp = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = tp
    spec.loader.exec_module(tp)
    dem = tp.dem                  # the module the script holds (other tests re-import brc_tools.terrain)
    with open(ROOT / "brc_tools" / "nwp" / "lookups.toml", "rb") as fh:
        wp = tomllib.load(fh)["waypoints"]["ouray"]
    ny = nx = 41
    res = 100.0
    xo, yo = dem.Grid(0.0, 0.0, res, 1, 1).to_grid.transform(float(wp["lon"]), float(wp["lat"]))
    grid = dem.Grid(float(round(xo) - (nx // 2 + 0.5) * res), float(round(yo) + (ny // 2 + 0.5) * res), res, ny, nx)
    jj, ii = np.indices((ny, nx))
    z = 1000.0 + np.clip(np.hypot(jj - ny // 2, ii - nx // 2) - 6.0, 0.0, None) ** 2 * 3.0
    z = np.minimum(z, 1700.0)
    z[ny // 2, nx // 2:] = 1000.0 - 0.5 * (ii[ny // 2, nx // 2:] - nx // 2)        # the river, out to the east edge
    seen = {}

    def fake_mosaic(tiles_dir, source, extent, res_m, *, cache_dir=None, **kw):
        seen["cache"] = dem.terrain_cache_dir(cache_dir)
        return z.astype(np.float32), grid

    monkeypatch.setattr(dem, "mosaic_tiles", fake_mosaic)
    lon_a, lat_a = grid.lonlat(2, nx - 3)
    lon_b, lat_b = grid.lonlat(ny - 3, nx - 3)
    outlet = [str(float(v)) for v in (lat_a, lon_a, lat_b, lon_b)]

    def run(out, tag, *extra):
        argv = ["--tiles-dir", "unused", "--res", "100", "--extent", "-110", "-109", "40", "41", "--sink", "ouray",
                "--outlet", *outlet, "--out-dir", str(out), "--tag", tag, *extra]
        assert tp.main(argv) == 0
        with open(out / f"gates_{tag}.csv", newline="") as fh:
            rows = list(csv.reader(fh))
        basin = json.loads((out / f"basin_{tag}.json").read_text())
        return rows, basin, dict(np.load(out / f"terrain_{tag}.npz"))

    return tp, run, seen, grid


def test_pipeline_writes_gates_and_totals(pipeline, tmp_path, monkeypatch):
    tp, run, seen, _ = pipeline
    monkeypatch.setenv("BRC_TOOLS_TERRAIN_CACHE", str(tmp_path / "envcache"))
    rows, basin, npz = run(tmp_path, "a", "--rims", "1150", "--channel-km2", "0.05")
    assert rows[0] == tp.FIELDS and len(rows) > 1
    assert basin["rims"]["1150"]["channel_gates"] + basin["rims"]["1150"]["truncated_gates"] == len(rows) - 1
    assert (npz["lab_rim1150"] >= 0).any()
    assert seen["cache"] == tmp_path / "envcache"              # the wrapper's cache, not one inside --out-dir
    run(tmp_path, "b", "--rims", "1150", "--cache-dir", str(tmp_path / "mine"))
    assert seen["cache"] == tmp_path / "mine"


def test_pipeline_with_no_qualifying_crossing_still_writes_its_outputs(pipeline, tmp_path):
    tp, run, *_ = pipeline
    rows, basin, npz = run(tmp_path, "none", "--rims", "1150", "--channel-km2", "1e6")     # crossings, none a channel
    assert rows == [tp.FIELDS]
    assert basin["rims"]["1150"]["channel_gates"] == 0 and (npz["lab_rim1150"] == -1).all()
    rows, basin, npz = run(tmp_path, "zero", "--rims", "1800")                             # above every cell: no crossing
    assert rows == [tp.FIELDS]
    assert basin["rims"]["1800"] == {"floor_km2": basin["rims"]["1800"]["floor_km2"], "channel_gates": 0,
                                     "truncated_gates": 0, "channel_km2": 0, "truncated_km2": 0,
                                     "inward_draining_km2": 0}
    assert (npz["lab_rim1800"] == -1).all() and npz["floor_rim1800"].any()


def test_pipeline_refuses_a_sink_outside_the_grid(pipeline, tmp_path, monkeypatch):
    tp, run, _, grid = pipeline
    far = tp.dem.Grid(grid.x0 + 50e3, grid.y1, grid.res, grid.ny, grid.nx)
    z = np.full(grid.shape, 1500.0, dtype=np.float32)
    monkeypatch.setattr(tp.dem, "mosaic_tiles", lambda *a, **k: (z, far))
    with pytest.raises(ValueError, match="outside the grid"):
        tp.main(["--tiles-dir", "unused", "--res", "100", "--extent", "-110", "-109", "40", "41", "--sink", "ouray",
                 "--outlet", "40.0", "-109.0", "40.1", "-109.0", "--out-dir", str(tmp_path), "--tag", "far"])

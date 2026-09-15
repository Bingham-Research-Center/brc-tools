"""brc_tools.terrain.dem: the Grid geometry and the label NPZ round trip."""

from __future__ import annotations

import numpy as np
import pytest

from brc_tools.terrain import dem


def test_grid_dict_round_trip_and_shape():
    g = dem.Grid(600_000.0, 4_500_000.0, 30.0, 100, 200)
    assert dem.Grid.from_dict(g.to_dict()) == g
    assert g.shape == (100, 200) and g.cell_area_m2 == 900.0
    assert g.inside(np.array([0, 99, 100]), np.array([0, 199, 0])).tolist() == [True, True, False]
    assert g.flat(2, 3) == 2 * 200 + 3


def test_grid_ji_lonlat_round_trip():
    pytest.importorskip("pyproj")
    g = dem.Grid(600_000.0, 4_500_000.0, 30.0, 100, 200)
    lon, lat = g.lonlat(np.array([10, 50]), np.array([20, 150]))
    j, i = g.ji(lat, lon)
    assert j.tolist() == [10, 50] and i.tolist() == [20, 150]
    lon_w, lon_e, lat_s, lat_n = g.extent_lonlat()
    assert lon_w < lon_e and lat_s < lat_n and -111.0 < lon_w < -108.0


def test_line_cells_unique_and_inside():
    pytest.importorskip("pyproj")
    g = dem.Grid(600_000.0, 4_500_000.0, 30.0, 100, 200)
    lon0, lat0 = g.lonlat(10, 10)
    lon1, lat1 = g.lonlat(10, 60)
    cells = g.line_cells(lat0, lon0, lat1, lon1)
    assert cells.size >= 50 and np.unique(cells).size == cells.size
    assert np.all(cells // 200 == 10)
    thick = g.line_cells(lat0, lon0, lat1, lon1, width_cells=3)
    assert thick.size > cells.size


def test_sample_labels_outside_is_fill():
    pytest.importorskip("pyproj")
    g = dem.Grid(600_000.0, 4_500_000.0, 30.0, 10, 10)
    lab = np.arange(100, dtype=np.int32).reshape(10, 10)
    lon, lat = g.lonlat(np.array([3, 3]), np.array([4, 40]))
    out = dem.sample_labels(lab, g, lat, lon)
    assert out.tolist() == [34, -1]


def test_labels_npz_round_trip(tmp_path):
    g = dem.Grid(600_000.0, 4_500_000.0, 30.0, 4, 5)
    lab = np.arange(20, dtype=np.int32).reshape(4, 5)
    p = dem.save_labels_npz(tmp_path / "labels.npz", g, lab_rim2000=lab, floor=lab > 7)
    g2, arrays = dem.load_labels_npz(p)
    assert g2 == g and set(arrays) == {"lab_rim2000", "floor"}
    np.testing.assert_array_equal(arrays["lab_rim2000"], lab)


def test_cache_dir_and_path(monkeypatch, tmp_path):
    monkeypatch.setenv("BRC_TOOLS_TERRAIN_CACHE", str(tmp_path))
    assert dem.terrain_cache_dir() == tmp_path
    assert dem.terrain_cache_dir("/x/y") == dem.Path("/x/y")
    p = dem.dem_cache_path("1as", 30.0, (-111.6, -108.0, 39.4, 41.2))
    assert p.parent == tmp_path and p.name.startswith("dem_1as_30m_") and p.suffix == ".npz"


def test_mosaic_tiles_two_synthetic_tifs(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    pytest.importorskip("pyproj")
    from rasterio.transform import from_origin

    tiles = tmp_path / "1as"
    tiles.mkdir()
    # two 1-degree tiles side by side at 1/60 degree, a plane rising eastward
    for k, west in enumerate((-111.0, -110.0)):
        arr = np.fromfunction(lambda j, i: 1500.0 + 10.0 * (i + 60 * k), (60, 60), dtype=float).astype("float32")
        with rasterio.open(tiles / f"USGS_1_n41w{int(-west):03d}.tif", "w", driver="GTiff", height=60, width=60,
                           count=1, dtype="float32", crs="EPSG:4269",
                           transform=from_origin(west, 41.0, 1 / 60, 1 / 60), nodata=-32768.0) as ds:
            ds.write(arr, 1)
    z, grid = dem.mosaic_tiles(tmp_path, "1as", (-110.6, -109.4, 40.3, 40.7), 500.0, cache_dir=tmp_path / "cache")
    assert z.ndim == 2 and grid.res == 500.0 and np.isfinite(z).mean() > 0.9
    # rises eastward
    row = z[z.shape[0] // 2]
    assert np.nanmean(row[-5:]) > np.nanmean(row[:5])
    z2, grid2 = dem.mosaic_tiles(tmp_path, "1as", (-110.6, -109.4, 40.3, 40.7), 500.0, cache_dir=tmp_path / "cache")
    np.testing.assert_array_equal(z, z2)
    assert grid2 == grid
    with pytest.raises(FileNotFoundError):
        dem.mosaic_tiles(tmp_path, "1as", (-100.0, -99.0, 30.0, 31.0), 500.0, cache_dir=tmp_path / "cache")

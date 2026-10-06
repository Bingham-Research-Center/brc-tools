"""Model-grid helpers: block reduction and regridding (dem), path tracing and fill depth (d8),
conditioning, profiles and sections, catchment matching and names, WPS tiles and geo_em."""

from __future__ import annotations

import numpy as np
import pytest

from brc_tools.terrain import catchments as ct
from brc_tools.terrain import conditioning as cond
from brc_tools.terrain import d8, dem, profiles, wrfgrid
from brc_tools.terrain.dem import Grid


# ------------------------------------------------------------------ dem
def test_block_reduce_means_mins_and_nan_blocks():
    a = np.arange(16.0).reshape(4, 4)
    assert dem.block_reduce(a, 2).tolist() == [[2.5, 4.5], [10.5, 12.5]]
    assert dem.block_reduce(a, 2, "min").tolist() == [[0.0, 2.0], [8.0, 10.0]]
    a[0:2, 0:2] = np.nan
    r = dem.block_reduce(a, 2)
    assert np.isnan(r[0, 0]) and r[0, 1] == 4.5
    assert dem.block_reduce(np.ones((5, 7)), 2).shape == (2, 3)      # ragged edge dropped


def test_coarsen_grid_keeps_the_corner():
    g = Grid(x0=1000.0, y1=9000.0, res=30.0, ny=100, nx=200)
    c = dem.coarsen_grid(g, 20)
    assert (c.x0, c.y1, c.res, c.ny, c.nx) == (1000.0, 9000.0, 600.0, 5, 10)


def test_regrid_nearest_lays_a_coarse_raster_on_a_fine_one():
    fine = Grid(x0=0.0, y1=600.0, res=100.0, ny=6, nx=6)
    coarse = dem.coarsen_grid(fine, 3)
    lab = np.array([[1, 2], [3, 4]], dtype=np.int32)
    up = dem.regrid_nearest(lab, coarse, fine)
    assert up[:3, :3].tolist() == [[1] * 3] * 3 and up[3:, 3:].tolist() == [[4] * 3] * 3
    shifted = Grid(x0=-100.0, y1=700.0, res=100.0, ny=8, nx=8)
    out = dem.regrid_nearest(lab, coarse, shifted, fill=-1)
    assert out[0, 0] == -1 and out[1, 1] == 1


# ------------------------------------------------------------------ d8
def valley(ny=9, nx=40, res=30.0, drop=1.0, wall=6.0):
    jj, ii = np.indices((ny, nx))
    return (500.0 - drop * ii + wall * np.abs(jj - ny // 2)).astype(np.float64)


def test_trace_downstream_and_upstream_follow_the_axis():
    z = valley()
    ny, nx = z.shape
    rcv = d8.d8_receivers(z, 30.0)
    acc = d8.flow_accumulation(rcv).acc
    start = (ny // 2) * nx + 5
    down = d8.trace_downstream(rcv, start)
    assert down[0] == start and down[-1] == (ny // 2) * nx + nx - 1
    assert np.all(down // nx == ny // 2)
    up = d8.trace_upstream_main(rcv, acc, start, nx, min_acc=ny)      # wall cells drain < ny cells: stop at the head
    assert up[0] == start and np.all(up // nx == ny // 2) and up[-1] % nx == 0
    climbing = d8.trace_upstream_main(rcv, acc, start, nx)            # with no threshold it goes on up a wall
    assert climbing.size > up.size and np.array_equal(climbing[:up.size], up)
    stop = np.zeros(z.size, bool)
    stop[(ny // 2) * nx + 10] = True
    assert d8.trace_downstream(rcv, start, stop=stop)[-1] == (ny // 2) * nx + 10


def test_fill_depth_of_a_dammed_valley():
    pytest.importorskip("richdem")
    z = valley(drop=1.0)
    z[:, 30] += 12.0                                  # a dam across the valley at column 30
    g = Grid(x0=0.0, y1=270.0, res=30.0, ny=z.shape[0], nx=z.shape[1])
    depth = d8.fill_depth(z.astype(np.float32), g)
    mid = z.shape[0] // 2
    assert depth[mid, 29] == pytest.approx(11.0, abs=0.01)     # just upstream of the dam crest
    assert depth[mid, 35] == 0.0 and depth[mid, 5] == 0.0      # below the dam; above the pond's reach


# ------------------------------------------------------------------ conditioning
def test_limit_slope_tames_a_cliff_and_spares_the_flats():
    z = np.zeros((40, 40))
    z[:, 20:] = 600.0                                 # a 600 m cliff on a 100 m grid
    out, n = cond.limit_slope(z, 100.0, 30.0)
    assert n > 0
    assert np.degrees(np.arctan(cond.max_neighbour_slope(out, 100.0).max())) <= 30.0 + 1e-6
    assert out[:, 0].max() == 0.0 and out[:, -1].min() == 600.0      # far from the cliff: untouched
    same, n0 = cond.limit_slope(np.zeros((5, 5)), 100.0, 30.0)
    assert n0 == 0 and not same.any()


def test_breach_carves_a_monotone_channel():
    z = valley(drop=1.0)
    z[:, 20:24] += 50.0                               # a plug
    mid = z.shape[0] // 2
    cells = [(mid, i) for i in range(z.shape[1])]
    target = cond.monotone_downstream(500.0 - 1.0 * np.arange(z.shape[1]))
    out = cond.breach(z, cells, target)
    assert np.all(np.diff(out[mid]) <= 0)
    assert out[mid, 21] == pytest.approx(479.0) and out[mid - 1, 21] == z[mid - 1, 21]
    wide = cond.breach(z, cells, target, half_width_cells=1)
    assert wide[mid - 1, 21] == pytest.approx(478.0)                  # the lowest target among its three path neighbours


# ------------------------------------------------------------------ profiles
def test_long_profile_runs_downhill_and_slab_sections_match_a_v_valley():
    res, drop, wall = 30.0, 0.3, 6.0
    z = valley(ny=41, nx=120, res=res, drop=drop, wall=wall)
    ny, nx = z.shape
    g = Grid(x0=0.0, y1=ny * res, res=res, ny=ny, nx=nx)
    rcv = d8.d8_receivers(z, res)
    fo = d8.flow_accumulation(rcv)
    mid = ny // 2
    head = ny * res * res / 1e6                       # one column of cells: the walls drain less than this
    prof = profiles.long_profile(z, g, rcv, fo.acc, mid * nx + 60, head_km2=head)
    assert prof.dist_m[prof.i0] == 0.0 and prof.dist_m[0] < 0 < prof.dist_m[-1]
    assert np.all(prof.cells // nx == mid)            # the whole profile is on the valley axis
    assert np.all(np.diff(prof.z_m) > 0)              # downstream -> upstream: rising
    assert np.allclose(prof.slope, drop / res, atol=1e-6)
    stem = prof.cells[::-1]                           # upstream -> downstream
    stages = np.array([490.0, 520.0])
    sec = profiles.slab_sections(z, g, rcv, fo.order, fo.starts, stem, stages, slab_len_m=300.0, max_reach_m=1e9)
    # V section with side slope wall/res: at depth h the half-width is h * res / wall, area = h^2 * res / wall
    k = sec.s_m.size // 2
    h = stages - sec.bed_m[k]
    ok = h > 0
    # the slab's bed falls along its length, so compare at the slab-mean depth
    h_mean = h - 0.5 * drop * (sec.length_m[k] / res)
    assert sec.area_m2[k][ok] == pytest.approx((h_mean[ok] ** 2) * res / wall, rel=0.2)
    assert np.all(sec.top_m[k][ok] > 0) and np.all(sec.perimeter_m[k] >= sec.top_m[k])


def test_gorge_index_is_small_behind_a_throat():
    dist = np.linspace(-10.0, 30.0, 81)
    width = np.where(dist < 5.0, 300.0, 4000.0)
    idx, wmin, at = profiles.gorge_index(width, dist, -5.0, 5.0)
    assert idx == pytest.approx(300.0 / 4000.0) and wmin == 300.0 and -5.0 <= at <= 5.0


# ------------------------------------------------------------------ catchments
def test_match_labels_by_overlap():
    ref = np.full((10, 10), -1)
    ref[:, :5] = 0
    ref[:, 5:] = 1
    other = np.full((10, 10), -1)
    other[:, :4] = 0                                  # most of ref 0
    other[:, 4:] = 1                                  # all of ref 1 plus a strip of ref 0
    m = ct.match_labels(ref, 2, other, 2)
    assert m["partner"].tolist() == [0, 1]
    assert m["covered"][0] == pytest.approx(0.8) and m["covered"][1] == pytest.approx(1.0)
    assert m["iou"][1] == pytest.approx(50 / 60)
    lost = ct.match_labels(ref, 2, np.full((10, 10), -1), 1)
    assert lost["partner"].tolist() == [-1, -1]


def test_unique_names_qualifies_only_what_collides():
    primary = ["Dry Fork", "Little Brush Creek", "Little Brush Creek", "", "Nine Mile Creek", "Nine Mile Creek"]
    huc12 = ["Dry Fork", "Middle Little Brush Creek", "Reader Creek", "Timber Canyon", "Argyle Creek", "Argyle Creek"]
    names = ct.unique_names(primary, huc12)
    assert names[0] == "Dry Fork"
    assert names[1] == "Little Brush Creek [Middle Little Brush Creek]"
    assert names[2] == "Little Brush Creek [Reader Creek]"
    assert names[3] == "Timber Canyon"
    assert names[4] != names[5] and len(set(names)) == len(names)
    assert ct.slug("Little Brush Creek [Reader Creek]") == "little_brush_creek_reader_creek"


# ------------------------------------------------------------------ WPS tiles and geo_em
def test_wps_tile_coverage_reports_a_hole(tmp_path):
    d = tmp_path / "topo_x"
    d.mkdir()
    (d / "index").write_text("type = continuous\nsigned = yes\nprojection = regular_ll\ndx = 0.01\ndy = 0.01\n"
                             "known_x = 1.0\nknown_y = 1.0\nknown_lat = -89.995\nknown_lon = 0.005\nwordsize = 2\n"
                             "tile_x = 10\ntile_y = 10\ntile_z = 1\ntile_bdr=1\n")
    full = np.full((12, 12), 1500, dtype=">i2")
    holed = full.copy()
    holed[1:6, 1:11] = -32768                         # half of the core missing
    full.tofile(d / "00001-00010.00001-00010")
    holed.tofile(d / "00011-00020.00001-00010")
    rows = {r["name"]: r for r in wrfgrid.wps_tile_coverage(d)}
    assert rows["00001-00010.00001-00010"]["frac_valid"] == 1.0
    assert rows["00011-00020.00001-00010"]["frac_valid"] == pytest.approx(0.5)
    assert rows["00011-00020.00001-00010"]["n_missing"] == 50
    assert rows["00001-00010.00001-00010"]["has_missing_value"] is False


def test_read_geo_em_round_trips_its_own_coordinates(tmp_path):
    nc = pytest.importorskip("netCDF4")
    pyproj = pytest.importorskip("pyproj")
    ny, nx, dx = 30, 40, 600.0
    crs = ("+proj=lcc +lat_1=39 +lat_2=42 +lat_0=40.45 +lon_0=-109.6 +a=6370000 +b=6370000 +units=m +no_defs")
    tr = pyproj.Transformer.from_crs(crs, wrfgrid.sphere_geo_crs(), always_xy=True)
    x = (np.arange(nx) - nx / 2 + 0.5) * dx + 20000.0
    y = (np.arange(ny) - ny / 2 + 0.5) * dx - 10000.0
    xx, yy = np.meshgrid(x, y)
    lon, lat = tr.transform(xx, yy)
    hgt = (1500.0 + 0.01 * xx + 0.02 * yy).astype(np.float32)          # row 0 = south, as in WRF
    p = tmp_path / "geo_em.d02.nc"
    with nc.Dataset(p, "w") as ds:
        ds.createDimension("Time", 1)
        ds.createDimension("south_north", ny)
        ds.createDimension("west_east", nx)
        for name, arr in (("HGT_M", hgt), ("XLAT_M", lat), ("XLONG_M", lon), ("LU_INDEX", np.full((ny, nx), 21.0)),
                          ("LANDMASK", np.zeros((ny, nx)))):
            v = ds.createVariable(name, "f4", ("Time", "south_north", "west_east"))
            v[0] = arr
        ds.setncatts({"MAP_PROJ": 1, "DX": dx, "DY": dx, "TRUELAT1": 39.0, "TRUELAT2": 42.0, "MOAD_CEN_LAT": 40.45,
                      "STAND_LON": -109.6, "CEN_LAT": 40.4, "CEN_LON": -109.4, "grid_id": 2, "parent_grid_ratio": 5,
                      "ISLAKE": 21, "MMINLU": "MODIFIED_IGBP_MODIS_NOAH"})
    z, grid, meta = wrfgrid.read_geo_em(p)
    assert z.shape == (ny, nx) and meta["corner_error_m"] < 1.0
    assert z[0, 0] == pytest.approx(hgt[-1, 0])                         # north-up: first row is the northern one
    j, i = grid.ji(lat[3, 7], lon[3, 7])
    assert (int(j), int(i)) == (ny - 1 - 3, 7)
    assert meta["lake"].all()


def test_hgt_source_diff_finds_a_crater():
    src = np.full((20, 20), 1500.0)
    hgt = src + 3.0
    hgt[5, 9] = 900.0
    out = wrfgrid.hgt_source_diff(hgt, src, crater_m=50.0)
    assert out["n_crater"] == 1 and out["min_ji"] == (5, 9) and out["min_m"] == pytest.approx(-600.0)
    assert out["craters"][0][:2] == (5, 9)

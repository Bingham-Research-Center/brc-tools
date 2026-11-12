"""brc_tools.terrain.validate with canned NWIS / ArcGIS responses (no network)."""

from __future__ import annotations

import json

import numpy as np
import pytest

from brc_tools.terrain import d8
from brc_tools.terrain import validate as v
from brc_tools.terrain.dem import Grid

RDB = """# comment line
# another
agency_cd\tsite_no\tstation_nm\tdec_lat_va\tdec_long_va\tdrain_area_va
5s\t15s\t50s\t16s\t16s\t8s
USGS\t09266500\tASHLEY CREEK NEAR VERNAL, UT\t40.5800\t-109.6200\t101.0
USGS\t09999999\tNO AREA SITE\t40.5000\t-109.5000\t
USGS\t09261000\tGREEN RIVER NEAR JENSEN, UT\t40.4000\t-109.3000\t25400.0
"""


def test_nwis_rdb_parser_skips_format_line():
    sites = v.parse_nwis_rdb(RDB)
    assert [s.site_no for s in sites] == ["09266500", "09261000"]
    assert sites[0].drain_area_km2 == pytest.approx(101.0 * 2.589988)
    assert sites[0].name.startswith("ASHLEY")


def _valley_grid():
    pytest.importorskip("pyproj")
    ny, nx, res = 21, 41, 100.0
    jj, ii = np.indices((ny, nx))
    z = (2000.0 - 0.5 * ii + 15.0 * np.abs(jj - 10)).astype(np.float32)
    grid = Grid(620_000.0, 4_490_000.0, res, ny, nx)
    rcv = d8.d8_receivers(z, res)
    acc = d8.flow_accumulation(rcv).acc.reshape(ny, nx)
    return z, grid, acc


def test_compare_to_nwis_snaps_to_matching_area(monkeypatch):
    z, grid, acc = _valley_grid()
    lon, lat = grid.lonlat(12, 10)                       # two rows off the valley axis, a quarter down
    target = acc[10, 10] * grid.cell_area_m2 / 1e6
    sites = [v.NWISSite("1", "axis gauge", float(lat), float(lon), float(target)),
             v.NWISSite("2", "huge", float(lat), float(lon), 1e6)]
    df = v.compare_to_nwis(acc, grid, snap_m=300.0, sites=sites)
    row = df.filter(df["site_no"] == "1").row(0, named=True)
    assert row["ratio_d8_nwis"] == pytest.approx(1.0, abs=0.01)
    assert row["snap_m"] == pytest.approx(200.0, abs=1.0)
    assert df.filter(df["site_no"] == "2").row(0, named=True)["note"] == "exceeds grid"
    score = v.routing_score(df, min_km2=0.0)
    assert score["n"] == 1 and score["median_ratio"] == pytest.approx(1.0, abs=0.01)
    assert score["within_10pct"] == 1.0


def test_nwis_sites_uses_get_text(monkeypatch):
    monkeypatch.setattr(v, "_get_text", lambda url, params=None, **kw: RDB)
    sites = v.nwis_sites((-110.0, 40.0, -109.0, 41.0))
    assert len(sites) == 2


def test_wbd_name_and_failure(monkeypatch):
    monkeypatch.setattr(v, "_get_json", lambda url, params=None, **kw: {"features": [{"attributes": {"name": "Dry Fork"}}]})
    assert v.wbd_name(-109.7, 40.57) == "Dry Fork"
    monkeypatch.setattr(v, "_get_json", lambda url, params=None, **kw: {"features": []})
    assert v.wbd_name(-109.7, 40.57) == ""

    def boom(url, params=None, **kw):
        raise RuntimeError("down")
    monkeypatch.setattr(v, "_get_json", boom)
    assert v.wbd_name(-109.7, 40.57) == ""


def test_nhd_flowlines_paginates(monkeypatch):
    pages = [
        {"features": [{"attributes": {"gnis_name": "Dry Fork", "reachcode": "1"},
                       "geometry": {"paths": [[[-109.70, 40.60], [-109.69, 40.59]]]}}],
         "exceededTransferLimit": True},
        {"features": [{"attributes": {"gnis_name": "Ashley Creek", "reachcode": "2"},
                       "geometry": {"paths": [[[-109.60, 40.61], [-109.59, 40.60]], [[-109.58, 40.59]]]}}],
         "exceededTransferLimit": False},
    ]
    calls = []

    def fake(url, params=None, **kw):
        calls.append(params["resultOffset"])
        return pages[len(calls) - 1]
    monkeypatch.setattr(v, "_get_json", fake)
    fl = v.nhd_flowlines((-110.0, 40.0, -109.0, 41.0))
    assert [f.gnis_name for f in fl] == ["Dry Fork", "Ashley Creek", "Ashley Creek"]
    assert calls == [0, 1]
    assert fl[0].lonlat.shape == (2, 2)


def test_channel_agreement_perfect_on_identical_lines():
    z, grid, acc = _valley_grid()
    chan = acc >= 100
    cj, ci = np.nonzero(chan)
    lon, lat = grid.lonlat(cj, ci)
    fl = [v.Flowline("axis", "1", np.column_stack([lon, lat]))]
    out = v.channel_agreement(chan, grid, fl, tol_m=10.0)
    assert out["flowline_vertices_near_channel"] == 1.0
    assert out["channel_cells_near_flowline"] == 1.0
    assert v.channel_agreement(np.zeros_like(chan), grid, fl)["n_vertices"] == 0


def test_wbd_unit_returns_name_code_and_area(monkeypatch):
    monkeypatch.setattr(v, "_get_json", lambda url, params=None, **kw: {"features": [
        {"attributes": {"name": "Middle Little Brush Creek", "huc12": "140600100402", "areasqkm": 97.5}}]})
    u = v.wbd_unit(-109.42, 40.66, level=12)
    assert u == {"name": "Middle Little Brush Creek", "huc": "140600100402", "areasqkm": 97.5}
    monkeypatch.setattr(v, "_get_json", lambda url, params=None, **kw: {"features": []})
    empty = v.wbd_unit(-109.42, 40.66)
    assert empty["name"] == "" and empty["huc"] == "" and np.isnan(empty["areasqkm"])


def test_stream_name_takes_the_stream_the_path_follows_and_ignores_canals():
    grid = Grid(500000.0, 4500000.0, 30.0, 200, 200)
    path = np.array([100 * 200 + i for i in range(20, 180)])           # a west-east channel along row 100
    px, py = grid.xy(np.full(160, 100), np.arange(20, 180))
    lon, lat = grid.lonlat_xy(px, py)
    along = v.Flowline("Dry Fork", "1", np.column_stack([lon, lat]))
    far_x, far_y = grid.xy(np.full(160, 40), np.arange(20, 180))        # a named stream 1.8 km away
    flon, flat = grid.lonlat_xy(far_x, far_y)
    far = v.Flowline("Ashley Creek", "2", np.column_stack([flon, flat]))
    unnamed = v.Flowline("", "3", np.column_stack([lon, lat]))
    assert v.stream_name(grid, path, [far, unnamed, along]) == "Dry Fork"
    assert v.stream_name(grid, path, [far, unnamed]) == ""              # nothing named follows the path
    canal = v.Flowline("Yellowstone Feeder Canal", "4", np.column_stack([lon, lat]))
    assert v.stream_name(grid, path, [canal, far]) == ""                # a canal is not a catchment's name
    assert v.stream_name(grid, path, [canal], exclude=()) == "Yellowstone Feeder Canal"
    short = v.Flowline("Dry Fork", "5", np.column_stack([lon[:10], lat[:10]]))
    assert v.stream_name(grid, path, [short]) == ""                     # covers under a fifth of the path

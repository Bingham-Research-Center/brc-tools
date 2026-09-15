"""brc_tools.terrain.gates: perpendicular gates on a synthetic valley."""

from __future__ import annotations

import tomllib

import numpy as np
import pytest

from brc_tools.terrain import d8, gates
from brc_tools.terrain.dem import Grid


@pytest.fixture
def valley():
    """A valley draining EAST along row 10 with 15 m-per-row walls, on a real UTM grid
    near Vernal so lat/lon conversions are exercised (pyproj)."""
    pytest.importorskip("pyproj")
    ny, nx, res = 21, 41, 30.0
    jj, ii = np.indices((ny, nx))
    z = (2000.0 - 0.5 * ii + 15.0 * np.abs(jj - 10)).astype(np.float32)
    grid = Grid(620_000.0, 4_490_000.0, res, ny, nx)
    rcv = d8.d8_receivers(z, res)
    acc = d8.flow_accumulation(rcv).acc
    return z, grid, rcv, acc


def test_perpendicular_gate_is_normal_to_channel(valley):
    z, grid, rcv, acc = valley
    cell = 10 * grid.nx + 20
    g = gates.perpendicular_gate(z, grid, cell, rcv=rcv, acc=acc, name="test")
    assert g.azimuth_deg == pytest.approx(90.0, abs=1.0)            # channel runs east
    # the line runs north-south in the grid CRS; grid north differs from true north by
    # the meridian convergence (~1 deg here), so test the bearing a -> b, not the longitude
    ex = (g.b[1] - g.a[1]) * np.cos(np.deg2rad(g.a[0]))
    ey = g.b[0] - g.a[0]
    bearing = np.degrees(np.arctan2(ex, ey)) % 360.0
    assert min(abs(bearing - 0.0), abs(bearing - 360.0)) < 2.5 or abs(bearing - 180.0) < 2.5
    assert abs(g.a[0] - g.b[0]) > 0.01


def test_rightward_normal_points_downstream(valley):
    z, grid, rcv, acc = valley
    g = gates.perpendicular_gate(z, grid, 10 * grid.nx + 20, rcv=rcv, acc=acc)
    # walking a -> b, the rightward normal is (t_y, -t_x); it must point east (downstream)
    ex = (g.b[1] - g.a[1]) * np.cos(np.deg2rad(g.a[0]))
    ey = g.b[0] - g.a[0]
    n = np.array([ey, -ex])
    assert n[0] > 0.0 and abs(n[1]) < 0.05 * abs(n[0])
    assert g.direction_xy[0] == pytest.approx(1.0, abs=0.02)


def test_widths_increase_with_height_and_are_hand_computable(valley):
    z, grid, rcv, acc = valley
    g = gates.perpendicular_gate(z, grid, 10 * grid.nx + 20, rcv=rcv, acc=acc)
    w = [g.widths_m[h] for h in sorted(g.widths_m)]
    assert all(np.diff(w) >= 0.0)
    # walls rise 15 m per 30 m row: below thalweg + 100 m lies |dj| <= 6 -> 13 rows = 390 m
    assert g.widths_m[100.0] == pytest.approx(13 * 30.0)
    assert g.widths_m[50.0] == pytest.approx(7 * 30.0)
    assert g.thalweg_m == pytest.approx(float(z[10, 20]), abs=0.6)


def test_line_length_clipped_to_range(valley):
    z, grid, rcv, acc = valley
    g = gates.perpendicular_gate(z, grid, 10 * grid.nx + 20, rcv=rcv, acc=acc, line_km=(6.0, 12.0))
    assert g.line_length_m == pytest.approx(6000.0)                 # 1.5 x 570 m width, clipped up to 6 km
    h = gates.perpendicular_gate(z, grid, 10 * grid.nx + 20, rcv=rcv, acc=acc, line_km=(0.1, 0.5))
    assert h.line_length_m == pytest.approx(500.0)


def test_width_in_cells():
    assert gates.width_in_cells(4710.0, 600.0) == pytest.approx(7.85)
    assert gates.width_in_cells(1200.0, 200.0) == pytest.approx(6.0)


def test_gate_to_lookup_entry_round_trips_through_tomllib(valley):
    z, grid, rcv, acc = valley
    g = gates.perpendicular_gate(z, grid, 10 * grid.nx + 20, rcv=rcv, acc=acc, name="dry_fork")
    entry = gates.gate_to_lookup_entry(g, kind="rim", rim_m=2000, catchment_km2=265.43, huc10="Dry Fork",
                                       source="D8 on synthetic, test")
    text = gates.format_gate_toml("dry_fork", entry)
    parsed = tomllib.loads(text)["gates"]["dry_fork"]
    assert parsed["kind"] == "rim" and parsed["rim_m"] == 2000
    assert parsed["catchment_km2"] == 265.4 and parsed["huc10"] == "Dry Fork"
    assert parsed["a"] == [round(g.a[0], 5), round(g.a[1], 5)]
    assert parsed["width150_m"] == int(round(g.widths_m[150.0]))
    assert "source" in parsed
    with pytest.raises(ValueError):
        gates.gate_to_lookup_entry(g, kind="wall", rim_m=2000, catchment_km2=1.0, source="x")


def test_channel_direction_at_a_sink_points_south():
    ny, nx = 5, 5
    rcv = np.arange(ny * nx, dtype=np.int32)             # every cell its own sink
    acc = np.ones(ny * nx, dtype=np.uint32)
    d, up, dn = gates.channel_direction(rcv, acc, 12, nx, nsteps=2)
    assert d == (0.0, -1.0) and up == 12 and dn == 12

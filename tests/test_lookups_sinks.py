"""Integrity guards for the [sinks.*] table in lookups.toml and its reader."""

from __future__ import annotations

import re

import pytest

from brc_tools.drainage import sinks as sk


@pytest.fixture(scope="module")
def table() -> dict:
    t = sk.sinks()
    if not t:
        pytest.skip("no [sinks] table in lookups.toml yet")
    return t


def test_names_are_snake_case_and_kinds_known(table):
    for name, s in table.items():
        assert re.fullmatch(r"[a-z][a-z0-9_]*", name), f"{name}: not snake_case"
        assert s.kind in sk.SINK_KINDS
        assert s.snap_m > 0


def test_one_terminal_sink_and_every_chain_reaches_it(table):
    terminal = [n for n, s in table.items() if s.downstream is None]
    assert len(terminal) == 1, f"terminal sinks: {terminal}"
    for name in table:
        assert sk.chain(table, name)[-1] == terminal[0]


def test_upstream_first_puts_every_sink_before_its_receiver(table):
    order = sk.upstream_first(table)
    assert sorted(order) == sorted(table)
    for name, s in table.items():
        if s.downstream is not None:
            assert order.index(name) < order.index(s.downstream)


def test_exits_and_throat_ends_lie_inside_the_watershed_region(table):
    lon_w, lon_e, lat_s, lat_n = sk.region_extent("green_river_above_desolation")
    for name, s in table.items():
        for lat, lon in filter(None, (s.exit, s.throat_end)):
            assert lat_s <= lat <= lat_n and lon_w <= lon <= lon_e, f"{name}: ({lat}, {lon}) outside the region"


def test_a_floor_sink_never_drains_into_a_corridor_sink(table):
    for name, s in table.items():
        if s.kind == "floor" and s.downstream is not None:
            assert table[s.downstream].kind == "floor", f"{name} (floor) drains into a corridor sink"


def test_reader_rejects_a_cycle_and_an_unknown_receiver(tmp_path):
    p = tmp_path / "lookups.toml"
    p.write_text('[sinks.a]\nkind = "floor"\nexit = [40.0, -109.0]\ndownstream = "b"\n'
                 '[sinks.b]\nkind = "floor"\nexit = [40.1, -109.0]\ndownstream = "a"\n')
    with pytest.raises(ValueError):
        sk.sinks(p)
    p.write_text('[sinks.a]\nkind = "floor"\nexit = [40.0, -109.0]\ndownstream = "nowhere"\n')
    with pytest.raises(ValueError):
        sk.sinks(p)
    p.write_text('[sinks.a]\nkind = "lake"\nexit = [40.0, -109.0]\ndownstream = ""\n')
    with pytest.raises(ValueError):
        sk.sinks(p)


def test_waypoint_and_region_helpers():
    lat, lon = sk.waypoint_latlon("ouray")
    assert 39.9 < lat < 40.2 and -109.8 < lon < -109.6
    lon_w, lon_e, lat_s, lat_n = sk.region_extent("uinta_airshed")
    assert lon_w < lon_e and lat_s < lat_n

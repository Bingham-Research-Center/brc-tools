"""Integrity guards for the [gates.*] table in lookups.toml and its reader."""

from __future__ import annotations

import math
import re
import tomllib
from pathlib import Path

import pytest

from brc_tools.nwp import gates as gt

ROOT = Path(__file__).resolve().parents[1]
LOOKUPS = ROOT / "brc_tools" / "nwp" / "lookups.toml"


@pytest.fixture(scope="module")
def lookups() -> dict:
    return tomllib.loads(LOOKUPS.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def table(lookups) -> dict:
    t = lookups.get("gates", {})
    if not t:
        pytest.skip("no [gates] table in lookups.toml yet")
    return t


def _km(a, b):
    coslat = math.cos(math.radians(0.5 * (a[0] + b[0])))
    return math.hypot((b[1] - a[1]) * 111.32 * coslat, (b[0] - a[0]) * 110.54)


def test_every_gate_has_a_known_kind_and_a_source(table):
    for name, d in table.items():
        assert d.get("kind") in gt.GATE_KINDS, f"{name}: kind {d.get('kind')!r}"
        assert d.get("source"), f"{name}: no source string -- geometry must say where it came from"


def test_gate_names_are_snake_case_and_unique(table):
    for name in table:
        assert re.fullmatch(r"[a-z][a-z0-9_]*", name), f"{name}: not snake_case"


def test_every_gate_endpoint_and_mouth_inside_uinta_airshed(lookups, table):
    bad = [n for n, g in gt.gates(lookups=lookups).items() if not gt.in_region(g, "uinta_airshed", lookups=lookups)]
    assert not bad, f"gates outside uinta_airshed: {bad}"


def test_gate_lines_are_1_to_30_km(lookups, table):
    for n, g in gt.gates(lookups=lookups).items():
        assert 1.0 <= _km(g.a, g.b) <= 30.0, f"{n}: line is {_km(g.a, g.b):.1f} km"


def test_mouth_lies_near_the_line_midpoint(lookups, table):
    for n, g in gt.gates(lookups=lookups).items():
        if g.mouth is None:
            continue
        mid = (0.5 * (g.a[0] + g.b[0]), 0.5 * (g.a[1] + g.b[1]))
        assert _km(mid, g.mouth) < 2.0, f"{n}: mouth is {_km(mid, g.mouth):.1f} km from the line's midpoint"


def test_no_two_gate_lines_cross(lookups, table):
    """Two flux planes that cross count the air between them twice in any rim total
    (lake_fork and lake_fork_2 did, until both were clipped at the crossing).  Lines may
    meet at an end point; they may not pass through each other."""
    gs = gt.gates(lookups=lookups)

    def xy(p, lat0):
        return (p[1] * 111.32 * math.cos(math.radians(lat0)), p[0] * 110.54)

    def cross(u, v):
        return u[0] * v[1] - u[1] * v[0]

    names = sorted(gs)
    bad = []
    for i, n1 in enumerate(names):
        for n2 in names[i + 1:]:
            g1, g2 = gs[n1], gs[n2]
            lat0 = 0.25 * (g1.a[0] + g1.b[0] + g2.a[0] + g2.b[0])
            a, b, c, d = (xy(p, lat0) for p in (g1.a, g1.b, g2.a, g2.b))
            r, s = (b[0] - a[0], b[1] - a[1]), (d[0] - c[0], d[1] - c[1])
            den = cross(r, s)
            if abs(den) < 1e-12:
                continue
            qp = (c[0] - a[0], c[1] - a[1])
            t, u = cross(qp, s) / den, cross(qp, r) / den
            eps = 1e-3                      # a shared end point (to ~10 m) is a junction, not a crossing
            if eps < t < 1 - eps and eps < u < 1 - eps:
                bad.append(f"{n1} x {n2} at {t:.2f}/{u:.2f}")
    assert not bad, f"gate lines cross: {bad}"


def test_reader_filters_by_kind_and_exits_on_unknown(lookups, table):
    all_gates = gt.gates(lookups=lookups)
    assert len(all_gates) == len(table)
    for kind in gt.GATE_KINDS:
        sub = gt.gates(kind, lookups=lookups)
        assert all(g.kind == kind for g in sub.values())
    assert set(gt.gate_lines(lookups=lookups)) == set(all_gates)
    with pytest.raises(ValueError):
        gt.gates("wall", lookups=lookups)
    with pytest.raises(SystemExit):
        gt.gate("no_such_gate_anywhere", lookups=lookups)


def test_rightward_normal_is_downstream_for_rim_gates(lookups, table):
    """For a rim gate the export direction must point from the upstream point towards the
    mouth (downstream); the sign convention of integrate_flux_transect depends on it."""
    for n, g in gt.gates("rim", lookups=lookups).items():
        if g.upstream is None or g.mouth is None:
            continue
        coslat = math.cos(math.radians(g.mouth[0]))
        dx = (g.mouth[1] - g.upstream[1]) * coslat
        dy = g.mouth[0] - g.upstream[0]
        ne, nn = g.normal_en
        assert ne * dx + nn * dy > 0.0, f"{n}: rightward normal points upstream"

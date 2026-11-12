import math

from brc_tools.utils.places import gate_line, waypoint
from brc_tools.utils.tables import read_csv, write_csv


def test_waypoint_reads_the_registry():
    lat, lon, z = waypoint("vernal_airport")
    assert 40.4 < lat < 40.5 and -109.6 < lon < -109.4 and z > 1500
    assert math.isnan(waypoint("book_cliffs")[2])        # a landmark without an elevation


def test_gate_line_extends_both_ends_symmetrically():
    la, lo, lb, lob = gate_line("dry_fork")
    ela, elo, elb, elob = gate_line("dry_fork", extend_km=5.0)
    mid = (0.5 * (la + lb), 0.5 * (lo + lob))
    emid = (0.5 * (ela + elb), 0.5 * (elo + elob))
    assert abs(mid[0] - emid[0]) < 1e-9 and abs(mid[1] - emid[1]) < 1e-9
    kx = 111.32 * math.cos(math.radians(mid[0]))
    length = math.hypot((lob - lo) * kx, (lb - la) * 111.32)
    elength = math.hypot((elob - elo) * kx, (elb - ela) * 111.32)
    assert abs(elength - length - 10.0) < 1e-6


def test_csv_roundtrip(tmp_path):
    rows = [{"a": 1.23456789, "b": "x"}, {"a": 2.0, "c": True}]
    p = write_csv(tmp_path / "t.csv", rows)
    back = read_csv(p)
    assert back[0]["a"] == 1.23457 and back[0]["b"] == "x" and back[0]["c"] == ""
    assert back[1]["c"] == "True" and back[1]["b"] == ""

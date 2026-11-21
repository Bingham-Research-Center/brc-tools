"""NWPSource.latest_init(max_fxx=...): the newest run whose last lead is published.

Website ask P14: at :50 the waypoint job sent the run that began 2 h 50 min earlier,
although HRRR's f18 reaches S3 about 85 min after init. These tests drive the walk-back
through a stub ``_is_published``; one test drives the probe itself with a stub Herbie.
"""
from __future__ import annotations

import datetime as dt

import pytest

from brc_tools.nwp import source
from brc_tools.nwp.basinwx import latest_init_times
from brc_tools.nwp.source import NWPSource

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 21, 10, 50, tzinfo=UTC)    # the waypoint job's minute


def _published(monkeypatch, src, inits, calls=None):
    """Make ``inits`` (UTC hours on NOW's day) the only published runs."""
    have = {NOW.replace(hour=h, minute=0) for h in inits}

    def fake(init, fxx, product=None):
        if calls is not None:
            calls.append((init.hour, fxx, product))
        return init in have

    monkeypatch.setattr(src, "_is_published", fake)


def test_without_max_fxx_the_fixed_rule_is_unchanged(monkeypatch):
    src = NWPSource("hrrr")
    monkeypatch.setattr(src, "_is_published", lambda *a, **k: pytest.fail("no probe expected"))
    assert src.latest_init(now=NOW) == NOW.replace(hour=8, minute=0)


def test_finds_the_run_one_hour_newer_when_its_last_lead_is_up(monkeypatch):
    src = NWPSource("hrrr")
    calls = []
    _published(monkeypatch, src, inits=[8, 9], calls=calls)
    assert src.latest_init(now=NOW, max_fxx=18) == NOW.replace(hour=9, minute=0)
    assert calls == [(10, 18, None), (9, 18, None)]     # newest first, then stop


def test_falls_back_to_the_fixed_rule_without_probing_it(monkeypatch):
    src = NWPSource("hrrr")
    calls = []
    _published(monkeypatch, src, inits=[], calls=calls)   # nothing newer is up
    assert src.latest_init(now=NOW, max_fxx=18) == NOW.replace(hour=8, minute=0)
    assert [c[0] for c in calls] == [10, 9]               # 08Z itself is never probed


def test_a_run_up_already_is_taken(monkeypatch):
    src = NWPSource("hrrr")
    _published(monkeypatch, src, inits=[10])
    assert src.latest_init(now=NOW, max_fxx=0) == NOW.replace(hour=10, minute=0)


def test_product_is_passed_to_the_probe(monkeypatch):
    src = NWPSource("hrrr")
    calls = []
    _published(monkeypatch, src, inits=[9], calls=calls)
    src.latest_init(now=NOW, max_fxx=6, product="subh")
    assert calls[0] == (10, 6, "subh")


def test_rrfs_walks_back_on_its_three_hour_cycle(monkeypatch):
    src = NWPSource("rrfs")                       # cadence 3, lag 3
    now = NOW.replace(hour=13, minute=10)
    calls = []
    _published(monkeypatch, src, inits=[], calls=calls)
    assert src.latest_init(now=now, max_fxx=18) == now.replace(hour=9, minute=0)
    assert [c[0] for c in calls] == [12]


def test_latest_init_times_passes_max_fxx(monkeypatch):
    src = NWPSource("hrrr")
    _published(monkeypatch, src, inits=[9])
    got = latest_init_times(3, now=NOW, source=src, max_fxx=18)
    assert [t.hour for t in got] == [9, 8, 7]


class _FakeHerbie:
    found: set = set()

    def __init__(self, date, *, model, product, fxx, verbose, priority, **kw):
        assert date.tzinfo is None               # Herbie wants naive UTC
        assert priority == ["aws"]               # never let a NOMADS "yes" steer the fetch
        self.grib = (f"s3://{model}/{product}/{date:%Y%m%d%H}/f{fxx:02d}"
                     if (date.hour, product, fxx) in self.found else None)


def test_the_probe_reads_herbies_answer(monkeypatch):
    monkeypatch.setattr(source, "Herbie", _FakeHerbie)
    _FakeHerbie.found = {(9, "sfc", 18), (9, "subh", 6)}
    src = NWPSource("hrrr")
    assert src._is_published(NOW.replace(hour=9, minute=0), 18) is True
    assert src._is_published(NOW.replace(hour=10, minute=0), 18) is False
    assert src._is_published(NOW.replace(hour=9, minute=0), 6, "subh") is True
    assert src.latest_init(now=NOW, max_fxx=18) == NOW.replace(hour=9, minute=0)


def test_a_herbie_error_counts_as_not_published(monkeypatch):
    def boom(*a, **k):
        raise ValueError("no file")
    monkeypatch.setattr(source, "Herbie", boom)
    src = NWPSource("hrrr")
    assert src._is_published(NOW, 18) is False
    assert src.latest_init(now=NOW, max_fxx=18) == NOW.replace(hour=8, minute=0)

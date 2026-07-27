"""stage_gfs_soil candidate ranking: never reach forward, degrade gracefully.

The soil stream is a single file, so its selection rule carries real weight: it
decides the initial soil state of the whole run. Two properties must hold no matter
what is missing from the archive.

1. **Never reach past the WRF init.** An initial condition taken from a later
   analysis is not something the model could have had; it is a hindcast artefact.
2. **Degrade monotonically.** When the ideal file is missing, the next choice must
   be no worse, and the ordering must not zig-zag between "newest cycle" and
   "closest valid time" -- those two are not the same preference, and an early
   version of this ranking mixed them.

Ranking is by staleness (|valid - init|) first, then by shortest lead. Valid time
beats cycle recency for soil specifically: GFS barely assimilates soil, so a longer
forecast lead costs little, whereas being hours off catches the top layer partway
through its diurnal swing.
"""

from __future__ import annotations

import datetime as dt

import pytest

from brc_tools.nwp.wrf_staging import (
    GFS_CADENCE_HOURS,
    _parse_init_time,
    _snap_down_to_cadence,
)


def ranked(init: str, max_back: int = 4) -> list[tuple[int, int, dt.datetime, int]]:
    """Mirror of the ordering inside stage_gfs_soil: (staleness, lead, cycle, lead)."""
    init_dt = _parse_init_time(init)
    cycle0 = _snap_down_to_cadence(init_dt, GFS_CADENCE_HOURS)
    out: list[tuple[int, int, dt.datetime, int]] = []
    for back in range(max_back + 1):
        c = cycle0 - dt.timedelta(hours=GFS_CADENCE_HOURS * back)
        lead_at_init = int((init_dt - c).total_seconds() // 3600)
        for ld in ({lead_at_init, 0} if lead_at_init else {0}):
            stale = int((init_dt - (c + dt.timedelta(hours=ld))).total_seconds() // 3600)
            out.append((stale, ld, c, ld))
    out.sort(key=lambda x: (x[0], x[1]))
    return out


OFF_CYCLE = "2026-04-24 23:00"   # the Ashley 120 m init: 5 h past the 18Z cycle
ON_CYCLE = "2026-04-24 18:00"    # exactly on a GFS cycle


def test_first_choice_is_valid_at_init():
    stale, lead, cycle, _ = ranked(OFF_CYCLE)[0]
    assert stale == 0
    assert cycle.hour == 18 and lead == 5
    assert cycle + dt.timedelta(hours=lead) == dt.datetime(2026, 4, 24, 23)


def test_never_reaches_past_init():
    init_dt = _parse_init_time(OFF_CYCLE)
    for _, _, cycle, lead in ranked(OFF_CYCLE):
        assert cycle <= init_dt
        assert cycle + dt.timedelta(hours=lead) <= init_dt


def test_degrades_monotonically_in_staleness():
    stale = [x[0] for x in ranked(OFF_CYCLE)]
    assert stale == sorted(stale), stale
    assert stale[0] == 0


def test_prefers_shortest_lead_at_equal_staleness():
    leads = [x[1] for x in ranked(OFF_CYCLE) if x[0] == 0]
    assert leads == sorted(leads)
    assert leads[0] == 5  # 18Z f005 before 12Z f011


def test_on_cycle_init_needs_no_lead():
    stale, lead, cycle, _ = ranked(ON_CYCLE)[0]
    assert (stale, lead) == (0, 0) and cycle.hour == 18


def test_fallbacks_exist_when_everything_recent_is_missing():
    """A single missing object must not be able to fail the gate."""
    r = ranked(OFF_CYCLE, max_back=4)
    assert len(r) >= 8
    assert len({(c, ld) for _, _, c, ld in r}) == len(r)  # no duplicate probes


@pytest.mark.parametrize("init", [OFF_CYCLE, ON_CYCLE, "2026-04-25 03:00"])
def test_every_candidate_is_on_the_cadence_grid(init):
    for _, _, cycle, _ in ranked(init):
        assert cycle.hour % GFS_CADENCE_HOURS == 0
        assert (cycle.minute, cycle.second) == (0, 0)

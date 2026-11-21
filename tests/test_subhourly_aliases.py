"""Instantaneous aliases must pick one message per 15-min step from the real ``subh`` files.

Fixtures are index files copied unchanged from the live feeds for the 2026-11-20 13Z
cycle: HRRR ``wrfsubhf00``-``f02`` (``s3://noaa-hrrr-bdp-pds``) and RRFS
``2dfld.3km.subh.f001``/``f002`` (``s3://noaa-rrfs-ops-pds``; RRFS has no subh f000).
NWPSource stacks a field's messages along time (GH #82), so a search has to match the
four steps of an hour and nothing else. HRRR's 10 m wind is the trap: the file also
carries a 5-min average of it at every step, so the bare search matches eight.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from brc_tools.nwp.aviation import AIRPORT_VARIABLES
from brc_tools.nwp.source import NWPSource, load_lookups

FIXTURES = Path(__file__).parent / "fixtures"
LOOKUPS = load_lookups()
FILES = {
    ("hrrr", 0): "hrrr/hrrr.t13z.wrfsubhf00.grib2.idx",
    ("hrrr", 1): "hrrr/hrrr.t13z.wrfsubhf01.grib2.idx",
    ("hrrr", 2): "hrrr/hrrr.t13z.wrfsubhf02.grib2.idx",
    ("rrfs", 1): "rrfs/rrfs.t13z.2dfld.3km.subh.f001.conus.grib2.idx",
    ("rrfs", 2): "rrfs/rrfs.t13z.2dfld.3km.subh.f002.conus.grib2.idx",
}
#: Instantaneous 2-D fields a sub-hourly caller reads; accumulations and window maxima
#: (precip, max wind) use different windows in subh and are not covered here.
INSTANT = (
    "temp_2m", "dewpoint_2m", "wind_u_10m", "wind_v_10m", "wind_gust_10m",
    "wind_u_80m", "wind_v_80m", "pressure_surface", "visibility", "refl_comp",
    "refl_1km", "echo_top", "categorical_rain", "categorical_snow",
)


def _lines(model, fxx):
    text = (FIXTURES / FILES[(model, fxx)]).read_text()
    return [":" + ":".join(line.split(":")[3:]) for line in text.splitlines()]


@pytest.mark.parametrize("model, fxx", list(FILES))
@pytest.mark.parametrize("name", INSTANT)
def test_instant_alias_matches_one_message_per_step(name, model, fxx):
    alias = LOOKUPS["aliases"][name]
    search = NWPSource(model)._search_for(alias, "subh", alias["search"][model])
    hits = [line for line in _lines(model, fxx) if re.search(search, line)]

    assert len(hits) == (1 if fxx == 0 else 4), f"{name} {model} f{fxx:02d}: {search!r} -> {hits}"
    assert not [h for h in hits if " ave " in h or " acc " in h], hits
    steps = [h.split(":")[3] for h in hits]
    assert len(set(steps)) == len(steps), f"{name}: two messages on one step {steps}"


def test_the_bare_hrrr_wind_search_would_match_the_averages_too():
    """Why wind_u_10m/wind_v_10m carry a search_by_product pin for HRRR subh."""
    bare = LOOKUPS["aliases"]["wind_u_10m"]["search"]["hrrr"]
    hits = [line for line in _lines("hrrr", 1) if re.search(bare, line)]
    assert len(hits) == 8 and sum(" ave " in h for h in hits) == 4


def test_aviation_reads_only_pinned_instant_aliases():
    assert set(AIRPORT_VARIABLES) <= set(INSTANT)


def test_both_subh_products_are_flagged_subhourly():
    for model in ("hrrr", "rrfs"):
        assert LOOKUPS["models"][model]["products"]["subh"].get("subhourly") is True
        assert NWPSource(model)._is_subhourly("subh")
        assert not NWPSource(model)._is_subhourly(LOOKUPS["models"][model]["default_product"])

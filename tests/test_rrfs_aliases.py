"""Every RRFS alias in lookups.toml must pick exactly one message from the real feed.

The fixtures are index (.idx) files copied unchanged from the operational bucket,
``s3://noaa-rrfs-ops-pds/rrfs.20261120/12/`` (CONUS 3 km). Herbie selects a message by
regex-searching ``:VAR:level:forecast:`` built from each index line; a search that
matches nothing fails the fetch, and one that matches two makes Herbie return a list of
datasets instead of one. The prototype-era strings did both once the feed went
operational and split surface fields out of ``prslev`` into ``2dfld``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from brc_tools.nwp import basinwx, waypoint_forecast
from brc_tools.nwp.source import load_lookups

FIXTURES = Path(__file__).parent / "fixtures" / "rrfs"
LOOKUPS = load_lookups()
RRFS = LOOKUPS["models"]["rrfs"]
#: Accumulations and hourly maxima with no window at RRFS f000, as lookups.toml declares
#: them (``absent_at_f00``). The test below holds that list to the index both ways: a
#: declared alias must match nothing at f000, an undeclared one exactly one message.
ABSENT_AT_F000 = {
    name for name, alias in LOOKUPS["aliases"].items()
    if "rrfs" in alias.get("absent_at_f00", ())
}


def _search_lines(product: str, fxx: int) -> list[str]:
    path = FIXTURES / f"rrfs.t12z.{product}.3km.f{fxx:03d}.conus.grib2.idx"
    return [":" + ":".join(line.rstrip("\n").split(":")[3:]) for line in path.read_text().splitlines()]


def _rrfs_aliases():
    for name, alias in LOOKUPS["aliases"].items():
        search = alias.get("search", {}).get("rrfs")
        if search is not None:
            yield name, search, alias.get("products", {}).get("rrfs", RRFS["default_product"])


@pytest.mark.parametrize("name, search, product", list(_rrfs_aliases()))
def test_alias_matches_one_message(name, search, product):
    assert product in RRFS["products"], f"{name}: product {product!r} is not an RRFS product"
    pattern = search.format(level=700) if "{level}" in search else search
    leads = [6] if product == "prslev" else [0, 1, 6]
    for fxx in leads:
        hits = [line for line in _search_lines(product, fxx) if re.search(pattern, line)]
        if fxx == 0 and name in ABSENT_AT_F000:
            assert not hits
            continue
        assert len(hits) == 1, f"{name} at f{fxx:03d} in {product}: {pattern!r} matched {hits}"


def test_basinwx_export_variables_all_resolve_for_rrfs():
    wanted = set(basinwx.SURFACE_EXPORT_VARIABLES) | set(waypoint_forecast.SOURCE_VARIABLES)
    missing = sorted(v for v in wanted if "rrfs" not in LOOKUPS["aliases"][v].get("search", {}))
    assert not missing


def test_rrfs_cycle_settings_match_the_feed():
    # Hourly 2dfld/prslev files exist only for 00/03/.../21Z; 00/06/12/18Z run to f084.
    assert RRFS["init_cadence_hours"] == 3
    assert RRFS["default_product"] == "2dfld"
    assert (RRFS["default_max_fxx"], RRFS["extended_max_fxx"]) == (18, 84)
    assert RRFS["extended_init_hours"] == [0, 6, 12, 18]

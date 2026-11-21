"""Every GEFS alias in lookups.toml must pick exactly one message from the file it names.

The fixtures are index (.idx) files copied unchanged from the operational bucket,
``s3://noaa-gefs-pds/gefs.20261120/00/atmos/`` (control member ``c00``):
``pgrb2a.0p50`` is Herbie's ``atmos.5``, ``pgrb2s.0p25`` its ``atmos.25``. The 0.25 deg
file has no pressure levels at all (26 messages at f000), which is why every ``_pl``
alias reads ``atmos.5``; until 2026-11 they all pointed at ``atmos.25`` and matched
nothing. Herbie picks a message by regex-searching ``:VAR:level:forecast:`` built from
each index line; no match fails the fetch, two matches return a list.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from brc_tools.nwp.source import load_lookups

FIXTURES = Path(__file__).parent / "fixtures" / "gefs"
LOOKUPS = load_lookups()
GEFS = LOOKUPS["models"]["gefs"]
FILE_FOR_PRODUCT = {"atmos.5": "pgrb2a.0p50", "atmos.25": "pgrb2s.0p25"}
#: Time-invariant fields: GEFS writes them at f000 only, so only f000 is checked.
STATIC = {"terrain_height"}
#: Known gaps, each with the reason; a strict xfail flips to a failure once fixed.
OPEN: dict[str, str] = {}


def _search_lines(product: str, fxx: int) -> list[str]:
    path = FIXTURES / f"gec00.t00z.{FILE_FOR_PRODUCT[product]}.f{fxx:03d}.idx"
    return [":" + ":".join(line.rstrip("\n").split(":")[3:]) for line in path.read_text().splitlines()]


def _gefs_aliases():
    for name, alias in LOOKUPS["aliases"].items():
        search = alias.get("search", {}).get("gefs")
        if search is None:
            continue
        product = alias.get("products", {}).get("gefs", GEFS["default_product"])
        marks = [pytest.mark.xfail(reason=OPEN[name], strict=True)] if name in OPEN else []
        yield pytest.param(name, search, product, alias, id=name, marks=marks)


@pytest.mark.parametrize("name, search, product, alias", list(_gefs_aliases()))
def test_alias_matches_one_message(name, search, product, alias):
    assert product in GEFS["products"], f"{name}: {product!r} is not a GEFS product"
    levels = alias.get("default_levels", []) if "{level}" in search else [None]
    absent_f00 = "gefs" in alias.get("absent_at_f00", ())
    for fxx in [0] if name in STATIC else [0, 6]:
        lines = _search_lines(product, fxx)
        for level in levels:
            pattern = search if level is None else search.format(level=level)
            hits = [line for line in lines if re.search(pattern, line)]
            if fxx == 0 and absent_f00:
                assert not hits, f"{name} is declared absent at GEFS f000 but matched {hits}"
            else:
                assert len(hits) == 1, f"{name} f{fxx:03d} {product}: {pattern!r} matched {hits}"


def test_pressure_levels_are_not_in_the_quarter_degree_file():
    """The fact the _pl products rest on: atmos.25 has no isobaric message at all."""
    for fxx in (0, 6):
        assert not [line for line in _search_lines("atmos.25", fxx) if re.search(r":\d+ mb:", line)]


def test_every_gefs_product_an_alias_names_has_a_fixture():
    for name, alias in LOOKUPS["aliases"].items():
        if "gefs" in alias.get("search", {}):
            product = alias.get("products", {}).get("gefs", GEFS["default_product"])
            assert product in FILE_FOR_PRODUCT, f"{name}: add a {product} index fixture"


def test_gefs_omega_is_skipped_not_fetched_from_a_file_without_it(monkeypatch, tmp_path):
    """No GEFS file holds 850-300 mb VVEL, so GEFS has no omega_pl entry (2026-11-21)."""
    import datetime as dt

    from _nwp_fakes import make_fake_herbie, regular_grid
    from brc_tools.nwp import source
    from brc_tools.nwp.source import NWPSource

    assert "gefs" not in LOOKUPS["aliases"]["omega_pl"]["search"]
    monkeypatch.setenv("BRC_TOOLS_LOCK_DIR", str(tmp_path))
    monkeypatch.delenv("BRC_TOOLS_HERBIE_CACHE", raising=False)
    fake = make_fake_herbie(regular_grid())
    monkeypatch.setattr(source, "Herbie", fake)
    ds = NWPSource("gefs").fetch(dt.datetime(2026, 11, 21, 0), [6], ["temp_2m", "omega_pl"])
    assert set(ds.data_vars) == {"temp_2m"}
    assert not [s for _, _, s in fake.searches if "VVEL" in s]

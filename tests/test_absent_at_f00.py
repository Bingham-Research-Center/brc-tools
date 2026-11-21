"""``absent_at_f00`` in lookups.toml: which aliases a model's analysis hour cannot supply.

NWPSource skips those fetches at f00 instead of retrying a search that cannot match --
the surface cron logged six false "Fetch failed f000 precip_1hr" warnings a run before.
The HRRR fixtures are the live ``wrfsfc`` index files for 2026-11-21 05Z, copied
unchanged from ``s3://noaa-hrrr-bdp-pds``; the RRFS half is pinned in
``test_rrfs_aliases.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from brc_tools.nwp import NWPSource
from brc_tools.nwp.source import load_lookups

FIXTURES = Path(__file__).parent / "fixtures" / "hrrr"
LOOKUPS = load_lookups()
HRRR = LOOKUPS["models"]["hrrr"]


def _search_lines(fxx: int) -> list[str]:
    path = FIXTURES / f"hrrr.t05z.wrfsfcf{fxx:02d}.grib2.idx"
    return [":" + ":".join(line.rstrip("\n").split(":")[3:]) for line in path.read_text().splitlines()]


def _hrrr_sfc_aliases():
    for name, alias in LOOKUPS["aliases"].items():
        search = alias.get("search", {}).get("hrrr")
        product = alias.get("products", {}).get("hrrr", HRRR["default_product"])
        if search is not None and "{level}" not in search and product == "sfc":
            yield name, search, "hrrr" in alias.get("absent_at_f00", ())


def test_every_absent_model_is_a_real_model():
    models = set(LOOKUPS["models"])
    for name, alias in LOOKUPS["aliases"].items():
        assert set(alias.get("absent_at_f00", ())) <= models, name


@pytest.mark.parametrize("name, search, absent", list(_hrrr_sfc_aliases()))
def test_hrrr_absent_at_f00_matches_the_index(name, search, absent):
    for fxx in (0, 1):
        hits = [line for line in _search_lines(fxx) if re.search(search, line)]
        if fxx == 0 and absent:
            assert not hits, f"{name} is declared absent at HRRR f00 but matched {hits}"
        else:
            assert len(hits) == 1, f"{name} at f{fxx:02d}: {search!r} matched {hits}"


def _fake_message(name):
    lon = np.array([[-110.4, -109.5], [-110.4, -109.5]])
    lat = np.array([[40.0, 40.0], [40.3, 40.3]])
    return xr.Dataset(
        {name: (("y", "x"), np.full((2, 2), 1.0))},
        coords={"longitude": (("y", "x"), lon), "latitude": (("y", "x"), lat)},
    )


def test_fetch_skips_an_absent_alias_at_f00_and_leaves_it_nan(monkeypatch):
    src = NWPSource("hrrr")
    calls = []

    def fake(init, fxx, search, product, retries):
        calls.append((fxx, search))
        return _fake_message(search.split(":")[0])

    monkeypatch.setattr(src, "_herbie_fetch", fake)
    ds = src.fetch("2026-11-21 05Z", [0, 1], ["temp_2m", "precip_1hr"], max_workers=1)

    assert not [s for f, s in calls if f == 0 and s.startswith("APCP")]
    assert [s for f, s in calls if f == 1 and s.startswith("APCP")]
    assert ds.sizes["time"] == 2
    precip = ds["precip_1hr"]
    assert np.isnan(precip.isel(time=0)).all()
    assert np.isfinite(precip.isel(time=1)).all()

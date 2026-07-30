"""Guard: layer-specific aliases must pin their layer in the search string.

HRRR reuses variable names across level types and accumulation windows, so a
plausible-looking search can match *two* messages (Herbie then returns a list)
or zero.  Two real defects came from exactly this:

* ``precip_1hr`` -- a bare ``APCP:surface`` matches both the run-total and the
  1-hour bucket from f02 on.
* the Ashley gate-A0 shear column -- ``VUCSH`` alone matches both the
  ``0-1000 m`` and the ``0-6000 m`` layer.

Confirmed against the live gate-A0 inventories (HRRR sfc, 2025-10-11 21Z/23Z):
``VUCSH:0-6000 m above ground`` and ``VUCSH:0-1000 m above ground`` each match
exactly one message at f00, f01, f02 and f06, while a bare ``VUCSH`` matches
two.  This test keeps the depth token from being dropped again.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOOKUPS = ROOT / "brc_tools" / "nwp" / "lookups.toml"

#: alias-name depth suffix -> the metres token the search string must carry
_DEPTH_TOKENS = {
    "0to1km": "1000",
    "0to3km": "3000",
    "0to6km": "6000",
}


def _aliases() -> dict:
    return tomllib.loads(LOOKUPS.read_text(encoding="utf-8")).get("aliases", {})


def test_layer_aliases_pin_their_depth():
    aliases = _aliases()
    assert aliases, "no [aliases.*] found in lookups.toml"

    offenders = []
    for name, spec in aliases.items():
        for suffix, token in _DEPTH_TOKENS.items():
            if not name.endswith(suffix):
                continue
            for model, search in (spec.get("search") or {}).items():
                if token not in search:
                    offenders.append(f"{name}[{model}] = {search!r} (missing {token})")

    assert not offenders, (
        "layer-specific alias(es) whose search string does not pin the layer, so "
        "they may match more than one GRIB message: " + "; ".join(offenders)
    )


def test_shear_components_exist_for_the_layers_hrrr_ships():
    # HRRR carries VUCSH/VVCSH for 0-1 km and 0-6 km only.  The magnitude is
    # deliberately NOT here -- it is derived (see derived.add_shear_fields).
    aliases = _aliases()
    for layer in ("0to1km", "0to6km"):
        for comp in ("u", "v"):
            assert f"shear_{comp}_{layer}" in aliases
    assert not [n for n in aliases if n.startswith("shear_mag")], (
        "shear magnitude must stay a derived field, not a lookup alias -- "
        "requesting it as an alias is what produced the all-NaN gate-A0 column"
    )


def test_no_search_string_is_a_bare_variable_name():
    # Every search must carry a level/layer qualifier after the colon, or it can
    # match across level types.  A handful of whole-atmosphere fields legitimately
    # look bare, so require the colon rather than guessing at the level text.
    offenders = [
        f"{name}[{model}] = {search!r}"
        for name, spec in _aliases().items()
        for model, search in (spec.get("search") or {}).items()
        if not re.search(r"\S:\S", search)
    ]
    assert not offenders, "search string(s) with no level qualifier: " + "; ".join(offenders)

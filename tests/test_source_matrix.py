"""Guard: every NWP source in lookups.toml must be documented in the source matrix.

Enforces the "don't reinvent the wheel" process — each `[models.*]` added to
`brc_tools/nwp/lookups.toml` has to gain a row in `docs/nwp/NWP-SOURCE-MATRIX.md`
recording its Herbie-vs-direct download decision. This guards the *process* (the
wheel-check is written down), not an automated Herbie lookup: Herbie model names do
not map 1:1 to ours, so a name-collision check would mislead.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOOKUPS = ROOT / "brc_tools" / "nwp" / "lookups.toml"
MATRIX = ROOT / "docs" / "nwp" / "NWP-SOURCE-MATRIX.md"


def test_every_nwp_model_documented_in_source_matrix():
    models = tomllib.loads(LOOKUPS.read_text(encoding="utf-8")).get("models", {})
    assert models, "no [models.*] found in lookups.toml"
    doc = MATRIX.read_text(encoding="utf-8")
    missing = [name for name in models if f"`{name}`" not in doc]
    assert not missing, (
        f"NWP source(s) missing a row in {MATRIX.relative_to(ROOT)}: {missing}. "
        "Add each with its Herbie-native-vs-direct-download decision (see the doc header)."
    )

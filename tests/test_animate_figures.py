"""Frame discovery for `scripts/animate_figures.py`.

The script is a script, so it is imported by path.  What is tested here is the
part that silently produced a *plausible* wrong answer: which frames belong to
which series.

Two layouts exist in one output root, and only one of them is obvious.  The
history families write ``<time>/<view>/<kind>_<stamp>.png``; the ``aux`` family
writes ``<time>/<kind>_<view>_aux_<stamp>.png``, with no view directory at all.
A walk that only descends into view directories finds nothing from the auxiliary
stream -- and the auxiliary stream is the densest series in the root, so its
absence looks exactly like "that family was never rendered".

The tag scan then has to be longest-first: ``d02`` is a prefix of ``d02_ashley``,
so a shortest-first match files every zoomed frame under the full nest and the
zoom animation silently doubles up the parent's frames.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location(
        "_animate_figures", SCRIPTS / "animate_figures.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


def test_stamp_splits_kind_from_time(mod):
    m = mod.STAMP_RE.match("topdown_theta_2m_d02_20250909_0300")
    assert m.group("kind") == "topdown_theta_2m_d02"
    assert datetime.strptime(m.group("stamp"), mod.STAMP_FMT) == datetime(2025, 9, 9, 3, 0)


def test_a_name_without_a_stamp_is_not_a_frame(mod):
    assert mod.STAMP_RE.match("track_d02") is None


@pytest.mark.parametrize("kind, expected", [
    ("plan_llws_d02_aux", "d02"),
    ("plan_llws_d02_ashley_aux", "d02_ashley"),
    ("plan_refl_comp_d02_ashley_aux", "d02_ashley"),
    ("plan_llws_d01_aux", None),
])
def test_view_of_prefers_the_longest_tag(mod, kind, expected):
    # Deliberately shortest-first on the way in: the helper is responsible for
    # the ordering, because a caller that forgets it gets a plausible wrong answer
    # rather than an error.
    tags = sorted(["d02", "d02_ashley"], key=len)
    assert mod._view_of(kind, sorted(tags, key=len, reverse=True)) == expected


def test_time_dirs_ignore_the_animations_sibling(tmp_path, mod):
    for name in ("20251012_0100", "20251012_0110", "animations", "notes"):
        (tmp_path / name).mkdir()
    (tmp_path / "manifest_1.json").write_text("{}")
    got = [p.name for p in mod._time_dirs(tmp_path)]
    assert got == ["20251012_0100", "20251012_0110"]


def test_even_spacing_reports_mixed_cadence(mod):
    even = [datetime(2025, 10, 12, 1, m) for m in (0, 10, 20, 30)]
    assert mod._even_spacing(even) == (True, "10 min")
    mixed = [datetime(2025, 10, 12, 1, 0), datetime(2025, 10, 12, 1, 1),
             datetime(2025, 10, 12, 2, 0)]
    ok, described = mod._even_spacing(mixed)
    assert not ok and "1" in described and "59" in described

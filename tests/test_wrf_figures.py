"""Acceptance tests for the dataset-agnostic figure engine (brc_tools.nwp.wrf_figures).

Exercises the engine on a NON-pelican shape written to disk: a 2-nest run at a
shifted region, a focus point outside the innermost domain, and one domain missing
``SNOWH``.  Asserts that ``build_tasks`` adapts to the domain count/labels and that a
genuine mismatch becomes a NAMED skip/warning (not a silent per-figure ``[ERROR]``).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from _wrf_synthetic import write_synthetic_run

from brc_tools.nwp import wrf_figures as wf
from brc_tools.visualize.style import use_publication_style

# A minimal, fully declarative case: 2 nests, focus point off-grid, no soundings.
_TOML = """
[case]
slug = "synthtest"
label = "Synthetic Test"
archive_dir = "/does/not/exist"
run_subdir = ""
annotation = "synthetic | test"
crest_m = 1700.0
profile_hours = [12]
sounding_hour = 12
focus_point = { name = "OffGrid", lat = 10.0, lon = 10.0 }
surface_vars = [
  { key = "theta2m", style = "theta_2m",      wind = true  },
  { key = "t2",      style = "temp_2m",        wind = true  },
  { key = "wspd10",  style = "wind_speed_10m", wind = true  },
  { key = "snow",    style = "snow_depth",     wind = false },
  { key = "pblh",    style = "pblh",           wind = false },
]

[soundings]
stations = []
ic_cases = []

[runs]
main = { dir = "maincase", label = "Main" }
"""


def _make_case(tmp_path, monkeypatch):
    monkeypatch.delenv("BRC_WRF_ARCHIVE", raising=False)
    archive = tmp_path / "archive"
    run = archive / "maincase" / "run_20130202"
    times = [datetime(2013, 2, 2, 12), datetime(2013, 2, 2, 13)]
    write_synthetic_run(
        run,
        {
            1: {"ny": 8, "nx": 8, "dx": 3000.0, "drop_vars": ("SNOWH",)},
            2: {"ny": 10, "nx": 10, "dx": 1000.0},
        },
        times,
        lat0=45.0,
        lon0=-120.0,
    )
    toml = tmp_path / "synthtest.toml"
    toml.write_text(_TOML)
    return wf.CaseConfig.from_toml(toml, archive_override=str(archive))


def test_preflight_reports_named_skips(tmp_path, monkeypatch):
    cfg = _make_case(tmp_path, monkeypatch)
    rep = wf.preflight(cfg, "main")

    # domain-aware from the data (2 nests, not the pelican 3)
    assert rep.domains == [1, 2]
    assert rep.innermost == 2 and rep.outermost == 1

    # focus point off-grid -> warned, and point-dependent families skipped by name
    assert rep.point_ok is False
    assert any("outside d02" in w for w in rep.warnings)
    assert any("off-grid" in s for s in rep.skips)

    # missing SNOWH -> NAMED skip, not a silent drop
    assert any("surface:snow" in s for s in rep.skips)
    usable = [sv.key for sv in rep.usable_surface_vars]
    assert "snow" not in usable
    assert "theta2m" in usable and "pblh" in usable


def test_build_tasks_surface_enumerates_present_domains(tmp_path, monkeypatch):
    cfg = _make_case(tmp_path, monkeypatch)
    sel = wf.Selection(
        cases=["main"], families=["surface"], time="12", output_dir=str(tmp_path / "out")
    )
    tasks = wf.build_tasks(cfg, sel)

    surf = [t for t in tasks if t[1] is wf.task_surface]
    assert surf, "expected surface tasks"
    # args tuple is (cfg, run, domains, case, label, valid, sv, out)
    assert all(args[2] == [1, 2] for _name, _fn, args in surf)
    keys = {args[6].key for _name, _fn, args in surf}
    assert "theta2m" in keys and "snow" not in keys  # snow dropped, others kept


def test_build_tasks_skips_focus_families_when_point_off_grid(tmp_path, monkeypatch):
    cfg = _make_case(tmp_path, monkeypatch)
    sel = wf.Selection(
        cases=["main"], families=["profile", "skewt", "heatdeficit"],
        time="12", output_dir=str(tmp_path / "out"),
    )
    # focus point is off-grid, so every focus-dependent family is skipped
    assert wf.build_tasks(cfg, sel) == []


def test_engine_renders_on_non_pelican_shape(tmp_path, monkeypatch):
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
    cfg = _make_case(tmp_path, monkeypatch)
    sel = wf.Selection(
        cases=["main"], families=["surface"], time="12", output_dir=str(tmp_path / "out")
    )
    tasks = wf.build_tasks(cfg, sel)
    surf = [t for t in tasks if t[1] is wf.task_surface]

    use_publication_style()
    _name, fn, args = surf[0]  # theta2m panel (first usable surface var)
    fn(*args)

    out = Path(args[7])
    pngs = list(out.glob("*.png"))
    assert pngs and pngs[0].stat().st_size > 0

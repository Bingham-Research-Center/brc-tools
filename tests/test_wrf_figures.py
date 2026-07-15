"""Acceptance tests for the dataset-agnostic figure engine (brc_tools.nwp.wrf_figures).

Exercises the engine on a NON-pelican shape written to disk: a 2-nest run at a
shifted region, a focus point outside the innermost domain, and one domain missing
``SNOWH``.  Asserts that ``build_tasks`` adapts to the domain count/labels and that a
genuine mismatch becomes a NAMED skip/warning (not a silent per-figure ``[ERROR]``).
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from _wrf_synthetic import write_synthetic_run

from brc_tools.nwp import wrf_figures as wf
from brc_tools.nwp import wrf_output as wo
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

[[transects]]
name = "gate"
label = "Test Gate"
lat_a = 45.2
lon_a = -119.8
lat_b = 45.6
lon_b = -119.4
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
    # args tuple is (cfg, run, domains, case, label, valid, sv, out, skip_existing)
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


def test_heatdeficit_map_emits_and_renders(tmp_path, monkeypatch):
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
    cfg = _make_case(tmp_path, monkeypatch)
    sel = wf.Selection(
        cases=["main"], families=["heatdeficit_map"], time="12",
        output_dir=str(tmp_path / "out"),
    )
    tasks = wf.build_tasks(cfg, sel)

    # the field family does not depend on the focus point, so it emits even though the
    # test case's focus point is off-grid; it renders on the innermost nest by default.
    hd = [t for t in tasks if t[1] is wf.task_heatdeficit_map]
    assert hd, "expected heatdeficit_map field tasks"
    # args: (cfg, run, dom, case, label, valid, out, skip_existing)
    assert all(args[2] == 2 for _n, _fn, args in hd)

    use_publication_style()
    _name, fn, args = hd[0]
    fn(*args)
    pngs = list(Path(args[6]).glob("*.png"))
    assert pngs and pngs[0].stat().st_size > 0


def test_deficitflux_families_emit_and_render(tmp_path, monkeypatch):
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
    cfg = _make_case(tmp_path, monkeypatch)
    sel = wf.Selection(
        cases=["main"], families=["deficitflux_map", "deficitflux_div"],
        time="12", output_dir=str(tmp_path / "out"),
    )
    tasks = wf.build_tasks(cfg, sel)

    maps = [t for t in tasks if t[1] is wf.task_deficitflux_map]
    divs = [t for t in tasks if t[1] is wf.task_deficitflux_div]
    assert maps and divs, "expected deficitflux map + div tasks"
    # args: (cfg, run, dom, case, label, valid, out, skip_existing); innermost by default
    assert all(args[2] == 2 for _n, _fn, args in maps + divs)

    use_publication_style()
    for _name, fn, args in (maps[0], divs[0]):
        fn(*args)
        pngs = list(Path(args[6]).glob("*.png"))
        assert pngs and pngs[0].stat().st_size > 0


def test_deficitflux_transect_emits_and_renders(tmp_path, monkeypatch):
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
    cfg = _make_case(tmp_path, monkeypatch)
    assert [t.name for t in cfg.transects] == ["gate"]
    sel = wf.Selection(
        cases=["main"], families=["deficitflux_transect"], output_dir=str(tmp_path / "out")
    )
    tasks = wf.build_tasks(cfg, sel)

    # one task per configured transect; independent of the (off-grid) focus point
    tr = [t for t in tasks if t[1] is wf.task_deficitflux_transect]
    assert len(tr) == 1

    use_publication_style()
    _name, fn, args = tr[0]  # args: (cfg, dfx_runs, transect, out, skip_existing)
    fn(*args)
    pngs = list(Path(args[3]).glob("*.png"))
    assert pngs and pngs[0].stat().st_size > 0


def test_build_tasks_lead_selects_forecast_hour(tmp_path, monkeypatch):
    # run inits at 12Z (earliest wrfout); --lead 1 => the 13Z valid time.
    cfg = _make_case(tmp_path, monkeypatch)
    sel = wf.Selection(
        cases=["main"], families=["surface"], lead="1", output_dir=str(tmp_path / "out")
    )
    tasks = wf.build_tasks(cfg, sel)
    surf = [t for t in tasks if t[1] is wf.task_surface]
    assert surf, "expected surface tasks at the 1-hour lead"
    # args: (cfg, run, domains, case, label, valid, sv, out, skip_existing)
    assert {args[5] for _n, _fn, args in surf} == {datetime(2013, 2, 2, 13)}
    assert all(args[8] is False for _n, _fn, args in surf)  # skip_existing threaded through


def test_build_tasks_unavailable_lead_is_skipped_not_crashed(tmp_path, monkeypatch, capsys):
    # only 12Z/13Z exist; lead 12h (-> next-day 00Z) is absent -> named skip, no crash.
    cfg = _make_case(tmp_path, monkeypatch)
    sel = wf.Selection(
        cases=["main"], families=["surface"], lead="12", output_dir=str(tmp_path / "out")
    )
    tasks = wf.build_tasks(cfg, sel)  # must not raise
    assert [t for t in tasks if t[1] is wf.task_surface] == []
    assert "not available yet" in capsys.readouterr().out


def test_lead_overrides_time(tmp_path, monkeypatch):
    # --time asks for hour 12, --lead asks for +1h (=13Z); lead wins.
    cfg = _make_case(tmp_path, monkeypatch)
    sel = wf.Selection(
        cases=["main"], families=["surface"], time="12", lead="1",
        output_dir=str(tmp_path / "out"),
    )
    surf = [t for t in wf.build_tasks(cfg, sel) if t[1] is wf.task_surface]
    assert {args[5] for _n, _fn, args in surf} == {datetime(2013, 2, 2, 13)}


def test_skip_existing_skips_fresh_and_regenerates_stale(tmp_path, monkeypatch):
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
    cfg = _make_case(tmp_path, monkeypatch)
    sel = wf.Selection(
        cases=["main"], families=["surface"], time="12",
        output_dir=str(tmp_path / "out"), skip_existing=True,
    )
    _name, fn, args = [t for t in wf.build_tasks(cfg, sel) if t[1] is wf.task_surface][0]
    _cfg, run, domains, _case, _label, valid, _sv, out, skip = args
    assert skip is True

    use_publication_style()
    fn(*args)  # first render (PNG absent) -> writes it
    png = next(Path(out).glob("*.png"))
    srcs = [wo.wrfout_path(run, dom, valid) for dom in domains]

    # figure newer than every source wrfout -> idempotent skip (not rewritten)
    fresh = max(s.stat().st_mtime for s in srcs) + 10
    os.utime(png, (fresh, fresh))
    fn(*args)
    assert png.stat().st_mtime == fresh  # untouched

    # a source rewritten newer than the figure -> regenerate ("move to newer output")
    stale = 1_000_000_000.0  # year 2001, safely older than any real render time
    os.utime(png, (stale, stale))
    os.utime(srcs[0], (stale + 100, stale + 100))
    fn(*args)
    assert png.stat().st_mtime > stale  # rewritten to real 'now'

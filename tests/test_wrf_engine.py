"""Unit tests for brc_tools.nwp.wrf_engine -- the shared engine plumbing.

Covers the parts both the winds and convective engines depend on, so a change that
breaks one is caught rather than discovered on a compute node.
"""

import json
import os
from datetime import datetime, timedelta

import pytest

from brc_tools.nwp import wrf_engine as we

_TOML = """
[case]
slug = "testcase"
label = "Test case"
run_dir = "$TESTRUN/wrf_run"

[map]
states = true
counties = false

[style.overrides.refl_comp]
vmax = 60.0

[[domains]]
domain = 2
tag = "d02"
sections = ["one"]

[[sections]]
key = "one"
a = [40.0, -110.0]
b = [40.5, -109.5]

[[beams]]
key = "kgjx"
site = "KGJX"
elevations_deg = [0.5]
"""


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setenv("TESTRUN", str(tmp_path / "run"))
    path = tmp_path / "case.toml"
    path.write_text(_TOML)
    return we.load_config(path, index=("sections", "beams"))


class TestLoadConfig:
    def test_expands_run_dir_env_vars(self, config, tmp_path):
        assert config["case"]["run_dir"] == tmp_path / "run" / "wrf_run"

    def test_indexes_arrays_of_tables_by_key(self, config):
        assert set(config["_sections"]) == {"one"}
        assert set(config["_beams"]) == {"kgjx"}
        assert config["_beams"]["kgjx"]["site"] == "KGJX"

    def test_missing_case_table_is_fatal(self, tmp_path):
        path = tmp_path / "bad.toml"
        path.write_text("[map]\nstates = true\n")
        with pytest.raises(SystemExit, match=r"\[case\]"):
            we.load_config(path)

    def test_an_unkeyed_entry_is_reported(self, tmp_path):
        path = tmp_path / "bad.toml"
        path.write_text('[case]\nslug = "x"\n\n[[sections]]\nlabel = "no key"\n')
        with pytest.raises(SystemExit, match="needs a 'key'"):
            we.load_config(path, index=("sections",))


class TestStyleFor:
    def test_override_is_applied(self, config):
        assert we.style_for(config, "refl_comp").vmax == 60.0

    def test_unoverridden_fields_keep_the_default(self, config):
        base = we.style_for(config, "refl_comp")
        assert base.vmin == 5.0  # the package default survives a partial override

    def test_a_variable_with_no_override_is_untouched(self, config):
        from brc_tools.visualize.style import get_style

        assert we.style_for(config, "wspd10max") == get_style("wspd10max")


class TestWaypoints:
    def test_resolves_a_group_to_title_case(self):
        group = we.waypoints("ashley_outflow")
        assert "Vernal Airport" in group
        assert set(group["Vernal Airport"]) >= {"lat", "lon"}

    def test_empty_group_is_empty(self):
        assert we.waypoints(None) == {}

    def test_unknown_group_names_the_alternatives(self):
        with pytest.raises(SystemExit, match="ashley_outflow"):
            we.waypoints("no_such_group")

    def test_single_waypoint_lookup(self):
        assert we.waypoint("ashley_spotter")["lat"] == pytest.approx(40.41076)

    def test_unknown_waypoint_points_at_lookups(self):
        with pytest.raises(SystemExit, match="lookups.toml"):
            we.waypoint("nowhere_at_all")


class TestOutputRoot:
    def test_cli_override_wins(self, config, tmp_path):
        assert we.output_root(config, tmp_path / "figs") == tmp_path / "figs"

    def test_falls_back_to_the_slug_under_the_default_root(self, config):
        assert we.output_root(config).name == "testcase"

    def test_refuses_the_brc_tools_checkout(self, config):
        repo = we.Path(we.__file__).resolve().parents[2]
        with pytest.raises(SystemExit, match="repo checkout"):
            we.output_root(config, repo / "figures")

    def test_refuses_the_case_repo(self, config, tmp_path):
        # A case config living in a git repo must not receive figures either.
        case_repo = tmp_path / "caserepo"
        (case_repo / ".git").mkdir(parents=True)
        cfg_path = case_repo / "case.toml"
        cfg_path.write_text(_TOML)
        with pytest.raises(SystemExit, match="repo checkout"):
            we.output_root(config, case_repo / "figs", config_path=cfg_path)

    def test_a_stray_git_dir_above_scratch_does_not_veto(self, config, tmp_path):
        # This is a real failure mode: /tmp/.git exists on CHPC, and a guard that
        # rejected any ancestor holding a .git vetoed every legitimate scratch path.
        (tmp_path / ".git").mkdir()
        scratch = tmp_path / "scratch" / "figs"
        assert we.output_root(config, scratch) == scratch


class TestSelectTimes:
    @staticmethod
    def _lister(mapping):
        return lambda dom: mapping[dom]

    def test_sweep_takes_the_union_across_domains(self, capsys):
        # A coarse nest on hourly output must not throw away a fine nest's
        # sub-hourly frames.
        coarse = [datetime(2025, 10, 12, 2), datetime(2025, 10, 12, 3)]
        fine = coarse + [datetime(2025, 10, 12, 2, 30)]
        got = we.select_times(
            "/nowhere", [1, 2], every=30, times_for=self._lister({1: coarse, 2: fine})
        )
        assert datetime(2025, 10, 12, 2, 30) in got
        assert len(got) == 3

    def test_hourly_is_every_60(self):
        stamps = [datetime(2025, 10, 12, 2), datetime(2025, 10, 12, 2, 30),
                  datetime(2025, 10, 12, 3)]
        got = we.select_times("/nowhere", [2], hourly=True,
                              times_for=self._lister({2: stamps}))
        assert got == [datetime(2025, 10, 12, 2), datetime(2025, 10, 12, 3)]

    def test_all_times_keeps_native_cadence(self):
        stamps = [datetime(2025, 10, 12, 2), datetime(2025, 10, 12, 2, 1)]
        got = we.select_times("/nowhere", [2], all_times=True,
                              times_for=self._lister({2: stamps}))
        assert got == stamps

    def test_explicit_valid_time(self):
        stamps = [datetime(2025, 10, 12, 2), datetime(2025, 10, 12, 3)]
        got = we.select_times("/nowhere", [2], valid="2025-10-12_02:00",
                              times_for=self._lister({2: stamps}))
        assert got == [datetime(2025, 10, 12, 2)]

    def test_default_is_the_latest_common_time(self, capsys):
        a = [datetime(2025, 10, 12, 2), datetime(2025, 10, 12, 3)]
        b = a + [datetime(2025, 10, 12, 4)]
        got = we.select_times("/nowhere", [1, 2], times_for=self._lister({1: a, 2: b}))
        assert got == [datetime(2025, 10, 12, 3)]

    def test_a_domain_without_the_stream_is_skipped_not_fatal(self, capsys):
        """Streams are per-domain in WRF.

        A run with `auxhist2_interval = 0, 1` writes the high-cadence stream on the
        inner nest only. Letting the absent parent stream abort the job is what
        killed the first 1-minute sweep of this case.
        """
        stamps = [datetime(2025, 10, 12, 2), datetime(2025, 10, 12, 2, 1)]
        got = we.select_times(
            "/nowhere", [1, 2], all_times=True,
            times_for=self._lister({1: [], 2: stamps}), label="auxhist",
        )
        assert got == stamps
        assert "d01 has no auxhist times" in capsys.readouterr().out

    def test_fatal_only_when_no_domain_has_the_stream(self):
        with pytest.raises(SystemExit, match="for any requested domain"):
            we.select_times("/nowhere", [1, 2], times_for=self._lister({1: [], 2: []}))

    def test_a_cadence_matching_nothing_is_fatal(self):
        stamps = [datetime(2025, 10, 12, 2, 7)]
        with pytest.raises(SystemExit, match="matches a 30-minute cadence"):
            we.select_times("/nowhere", [2], every=30, times_for=self._lister({2: stamps}))

    def test_label_appears_in_the_message(self):
        with pytest.raises(SystemExit, match="no auxhist times"):
            we.select_times("/nowhere", [1], times_for=self._lister({1: []}),
                            label="auxhist")


def test_overlays_default_off(config):
    overlays = we.overlays_from(config)
    assert overlays["states"] is True
    assert overlays["counties"] is False
    assert overlays["rivers"] is False  # absent from the TOML
    assert set(overlays) == set(we.MAP_LAYERS)


class TestTimeWindow:
    """--start/--end. Without them a 1-minute sweep of a 5 h run is 301 times."""

    @staticmethod
    def _stamps():
        base = datetime(2025, 10, 12, 1, 0)
        return [base + timedelta(minutes=k) for k in range(0, 121, 10)]

    def _select(self, **kwargs):
        stamps = self._stamps()
        return we.select_times("/nowhere", [2], every=10,
                               times_for=lambda d: stamps, **kwargs)

    def test_start_only(self):
        got = self._select(start="2025-10-12_02:00")
        assert got[0] == datetime(2025, 10, 12, 2, 0)
        assert got[-1] == datetime(2025, 10, 12, 3, 0)

    def test_end_only(self):
        got = self._select(end="2025-10-12_01:30")
        assert got[-1] == datetime(2025, 10, 12, 1, 30)

    def test_both_bounds_are_inclusive(self):
        got = self._select(start="2025-10-12_01:20", end="2025-10-12_01:40")
        assert got == [
            datetime(2025, 10, 12, 1, 20),
            datetime(2025, 10, 12, 1, 30),
            datetime(2025, 10, 12, 1, 40),
        ]

    def test_datetime_objects_are_accepted(self):
        got = self._select(start=datetime(2025, 10, 12, 2, 30))
        assert got[0] == datetime(2025, 10, 12, 2, 30)

    def test_an_empty_window_is_fatal_and_says_why(self):
        with pytest.raises(SystemExit, match="inside the requested window"):
            self._select(start="2025-10-12_09:00")

    def test_no_window_keeps_everything(self):
        assert len(self._select()) == len(self._stamps())


class TestSectionPreflight:
    """The off-grid transect warning, shared by both engines.

    ``WRF-WINDS.md`` warned about this in prose; the point of the helper is that
    the warning now actually fires, before a sweep spends an hour on a curtain
    that is an artefact of unbounded nearest-neighbour search.
    """

    @staticmethod
    def _plane():
        from _wrf_synthetic import make_synthetic_wrf

        from brc_tools.nwp import wrf_section as ws

        return ws.load_plane(make_synthetic_wrf())

    def test_an_on_grid_transect_passes_quietly(self, capsys):
        spec = {"a": (40.1, -109.9), "b": (40.4, -109.6), "n_points": 40}
        assert we.check_section_on_grid(self._plane(), "valley", spec, tag="d02") is True
        assert capsys.readouterr().out == ""

    def test_a_partly_off_grid_transect_warns_but_still_renders(self, capsys):
        spec = {"a": (40.25, -109.75), "b": (40.25, -108.0), "n_points": 60}
        assert we.check_section_on_grid(self._plane(), "runoff", spec, tag="d02") is True
        out = capsys.readouterr().out
        assert "[WARN]" in out and "runoff" in out
        assert "leaves the grid" in out
        assert "edge column" in out  # says what was done about it

    def test_a_wholly_off_grid_transect_is_skipped(self, capsys):
        spec = {"a": (45.0, -100.0), "b": (45.5, -99.0), "n_points": 20}
        assert we.check_section_on_grid(self._plane(), "elsewhere", spec, tag="d01") is False
        out = capsys.readouterr().out
        assert "[SKIP]" in out and "elsewhere" in out

    def test_n_points_defaults_when_the_case_omits_it(self):
        spec = {"a": (40.1, -109.9), "b": (40.4, -109.6)}
        assert we.check_section_on_grid(self._plane(), "valley", spec, tag="d02") is True


class TestFigureLedger:
    """The render chokepoint: idempotence, manifest, tally and dry run.

    These were four separate gaps in the SOP because each family rendered on its
    own and reported an int. They are one seam.
    """

    @staticmethod
    def _ok(text="fig"):
        def render(path):
            path.write_text(text, encoding="utf-8")
        return render

    @staticmethod
    def _boom(path):
        raise RuntimeError("renderer exploded")

    # -- rendering ---------------------------------------------------------- #
    def test_a_successful_render_writes_and_counts(self, tmp_path):
        led = we.FigureLedger()
        out = tmp_path / "sub" / "a.png"
        assert led.emit(out, self._ok(), family="surface") == 1
        assert out.read_text() == "fig"          # parent dir created for it
        assert led.rendered == 1 and led.errors == 0

    def test_a_failing_render_is_caught_and_recorded_not_raised(self, tmp_path):
        led = we.FigureLedger()
        assert led.emit(tmp_path / "a.png", self._boom, family="beam") == 0
        assert led.errors == 1 and led.rendered == 0
        assert "RuntimeError" in led.records[0].detail

    def test_one_bad_figure_does_not_stop_the_others(self, tmp_path):
        led = we.FigureLedger()
        led.emit(tmp_path / "a.png", self._boom, family="beam")
        led.emit(tmp_path / "b.png", self._ok(), family="beam")
        assert (led.rendered, led.errors) == (1, 1)

    # -- idempotence (gap 1) ------------------------------------------------ #
    def test_without_skip_existing_it_re_renders(self, tmp_path):
        out, src = tmp_path / "a.png", tmp_path / "wrfout"
        src.write_text("x")
        out.write_text("old")
        we.FigureLedger().emit(out, self._ok("new"), sources=[src], family="surface")
        assert out.read_text() == "new"

    def test_skip_existing_keeps_a_figure_newer_than_its_source(self, tmp_path):
        out, src = tmp_path / "a.png", tmp_path / "wrfout"
        src.write_text("x")
        out.write_text("old")
        os.utime(src, (1000, 1000))
        os.utime(out, (2000, 2000))
        led = we.FigureLedger(skip_existing=True)
        assert led.emit(out, self._ok("new"), sources=[src], family="surface") == 0
        assert out.read_text() == "old"
        assert led.count(we.SKIPPED) == 1

    def test_a_source_rewritten_later_forces_a_re_render(self, tmp_path):
        # The run is still writing: a newer wrfout must beat an older figure.
        out, src = tmp_path / "a.png", tmp_path / "wrfout"
        out.write_text("old")
        src.write_text("x")
        os.utime(out, (1000, 1000))
        os.utime(src, (2000, 2000))
        led = we.FigureLedger(skip_existing=True)
        assert led.emit(out, self._ok("new"), sources=[src], family="surface") == 1
        assert out.read_text() == "new"

    def test_a_missing_source_is_not_current(self, tmp_path):
        out = tmp_path / "a.png"
        out.write_text("old")
        led = we.FigureLedger(skip_existing=True)
        assert not led.is_current(out, [tmp_path / "gone"])

    # -- dry run (gap 8) ---------------------------------------------------- #
    def test_dry_run_plans_without_writing(self, tmp_path):
        led = we.FigureLedger(dry_run=True)
        out = tmp_path / "a.png"
        assert led.emit(out, self._ok(), family="surface") == 0
        assert not out.exists()
        assert led.count(we.PLANNED) == 1
        assert any("a.png" in line for line in led.planned_lines())

    def test_a_dry_run_that_planned_nothing_still_exits_zero(self):
        assert we.FigureLedger(dry_run=True).exit_code() == 0

    # -- exit code (gap 3) -------------------------------------------------- #
    def test_any_error_exits_non_zero_even_when_most_succeeded(self, tmp_path):
        # The whole complaint: `return 0 if total else 1` could not tell
        # 400-of-400 from 399-of-400.
        led = we.FigureLedger()
        for i in range(9):
            led.emit(tmp_path / f"ok{i}.png", self._ok(), family="surface")
        led.emit(tmp_path / "bad.png", self._boom, family="surface")
        assert led.rendered == 9
        assert led.exit_code() == 1

    def test_allow_errors_opts_out(self, tmp_path):
        led = we.FigureLedger()
        led.emit(tmp_path / "ok.png", self._ok(), family="surface")
        led.emit(tmp_path / "bad.png", self._boom, family="surface")
        assert led.exit_code(allow_errors=True) == 0

    def test_rendering_nothing_at_all_exits_non_zero(self):
        assert we.FigureLedger().exit_code() == 1

    def test_a_run_that_only_skipped_is_a_success(self, tmp_path):
        out = tmp_path / "a.png"
        out.write_text("old")
        led = we.FigureLedger(skip_existing=True)
        led.emit(out, self._ok(), family="surface")
        assert led.exit_code() == 0  # everything was already up to date

    def test_summarise_names_each_status(self, tmp_path):
        led = we.FigureLedger()
        led.emit(tmp_path / "ok.png", self._ok(), family="surface")
        led.emit(tmp_path / "bad.png", self._boom, family="surface")
        led.note(we.ABSENT, "not written by this run", family="surface", var="hail_max")
        text = led.summarise()
        assert "1 rendered" in text and "1 error" in text and "1 absent" in text

    # -- manifest (gap 2) --------------------------------------------------- #
    def test_manifest_records_what_happened(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SLURM_JOB_ID", "12345")
        cfg = tmp_path / "case.toml"
        cfg.write_text("[case]\n")
        led = we.FigureLedger()
        led.emit(tmp_path / "a.png", self._ok(), family="surface",
                 domain=2, valid=datetime(2025, 10, 12, 2, 20), var="refl_comp")
        path = led.write_manifest(tmp_path / "out", config_path=cfg,
                                  run_dir=tmp_path, argv=["--figure", "surface"])
        assert path.name == "manifest_12345.json"
        man = json.loads(path.read_text())
        assert man["counts"]["rendered"] == 1
        assert man["argv"] == ["--figure", "surface"]
        assert len(man["config_sha256"]) == 64      # config pinned by hash
        fig = man["figures"][0]
        assert fig["family"] == "surface" and fig["domain"] == 2
        assert fig["var"] == "refl_comp" and fig["valid"] == "2025-10-12_02:20"

    def test_each_slurm_job_gets_its_own_manifest(self, tmp_path, monkeypatch):
        # Four jobs sweeping into one output root must not clobber each other.
        root = tmp_path / "out"
        for job in ("111", "222"):
            monkeypatch.setenv("SLURM_JOB_ID", job)
            led = we.FigureLedger()
            led.emit(tmp_path / f"{job}.png", self._ok(), family="aux")
            led.write_manifest(root)
        assert len(list(root.glob("manifest_*.json"))) == 2
        assert len(we.read_manifests(root)) == 2

    def test_report_reads_every_job_and_flags_failures(self, tmp_path, monkeypatch, capsys):
        root = tmp_path / "out"
        monkeypatch.setenv("SLURM_JOB_ID", "777")
        led = we.FigureLedger()
        led.emit(tmp_path / "ok.png", self._ok(), family="surface")
        led.emit(tmp_path / "bad.png", self._boom, family="beam")
        led.write_manifest(root)
        capsys.readouterr()

        assert we.report_coverage(root) == 1  # non-zero because one errored
        out = capsys.readouterr().out
        assert "1 job(s)" in out and "surface" in out and "beam" in out
        assert "errored" in out

    def test_report_on_an_empty_root_says_so(self, tmp_path, capsys):
        assert we.report_coverage(tmp_path) == 1
        assert "no manifests" in capsys.readouterr().out

    def test_an_unreadable_manifest_is_skipped_not_fatal(self, tmp_path, capsys):
        (tmp_path / "manifest_bad.json").write_text("{not json")
        assert we.read_manifests(tmp_path) == []
        assert "unreadable manifest" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# figure provenance
# --------------------------------------------------------------------------- #
class TestComposeTitle:
    """Whether a figure is model output or a measurement is not a detail of the
    caption -- on a beam comparison it is the entire claim, and until now only
    the observed panel said which it was."""

    def test_source_leads_and_empty_parts_are_dropped(self):
        got = we.compose_title(we.SOURCE_WRF, "d02 0.6 km", "", "valid 02:20Z")
        assert got == "WRF | d02 0.6 km | valid 02:20Z"

    def test_model_and_observed_titles_are_distinguishable_at_a_glance(self):
        model = we.compose_title(we.SOURCE_WRF, "d02 0.6 km", "KGJX 0.5 deg beam")
        obs = we.compose_title(we.SOURCE_OBSERVED, "KGJX N0B 0.5 deg", "d02 0.6 km")
        assert model.startswith("WRF")
        assert obs.startswith("OBSERVED")
        assert not obs.startswith(we.SOURCE_WRF)

    def test_a_comparison_names_both(self):
        assert we.compose_title(we.SOURCE_COMPARISON, "x").startswith("WRF vs OBS")


class TestStyleGammaOverride:
    def test_a_case_can_retune_gamma(self):
        cfg = {"style": {"overrides": {"uphel_2to5km": {"gamma": 1.0, "vmax": 80.0}}}}
        got = we.style_for(cfg, "uphel_2to5km")
        assert got.gamma == 1.0 and got.vmax == 80.0
        assert got.vmin == 5.0  # untouched keys fall through to the shared table

    def test_gamma_zero_means_linear_not_a_broken_norm(self):
        """PowerNorm(0) is not a scale; an explicit falsy value has to read as
        'make this linear again' or a case silently produces a blank panel."""
        cfg = {"style": {"overrides": {"uphel_2to5km": {"gamma": 0.0}}}}
        assert we.style_for(cfg, "uphel_2to5km").gamma is None

    def test_untouched_variables_keep_a_linear_scale(self):
        assert we.style_for({}, "theta").gamma is None


class TestMapLayers:
    def test_cities_is_reachable_from_a_case_toml(self):
        """basemap.draw_cities existed but MAP_LAYERS omitted it, and the engines
        build their overlay dict by iterating exactly that tuple -- so no case
        could switch it on."""
        assert "cities" in we.MAP_LAYERS
        assert we.overlays_from({"map": {"cities": True}})["cities"] is True

    def test_layers_default_off(self):
        overlays = we.overlays_from({})
        assert set(overlays) == set(we.MAP_LAYERS)
        assert not any(overlays.values())

    def test_every_layer_is_one_add_reference_overlays_accepts(self):
        """A layer name that the renderer does not take is a silent no-op."""
        import inspect

        from brc_tools.visualize.basemap import add_reference_overlays

        accepted = inspect.signature(add_reference_overlays).parameters
        for layer in we.MAP_LAYERS:
            assert layer in accepted, f"{layer} is not a add_reference_overlays kwarg"

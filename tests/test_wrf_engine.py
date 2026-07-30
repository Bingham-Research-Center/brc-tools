"""Unit tests for brc_tools.nwp.wrf_engine -- the shared engine plumbing.

Covers the parts both the winds and convective engines depend on, so a change that
breaks one is caught rather than discovered on a compute node.
"""

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

    def test_no_times_for_a_domain_is_fatal(self):
        with pytest.raises(SystemExit, match="no wrfout times"):
            we.select_times("/nowhere", [1], times_for=self._lister({1: []}))

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

"""Tests for the optional 3-D extras on WRFPlane / NWPSection.

Each extra is another full-depth read of a ~900 MB file, so the contract is that
they are **opt-in and fail-soft**: a plain wind sweep pays for none of them, and a
config that asks for a curtain the run cannot supply is named-skipped rather than
taking the sweep down.  Both halves of that are easy to break by accident.
"""

from __future__ import annotations

import numpy as np
import pytest
from _wrf_synthetic import make_synthetic_wrf

from brc_tools.nwp import wrf_section as ws

A, B = (40.05, -109.95), (40.45, -109.55)


class TestOptIn:
    def test_nothing_extra_is_loaded_by_default(self):
        plane = ws.load_plane(make_synthetic_wrf(moisture=True, tracers=2))
        for name in ws.PLANE_EXTRAS:
            assert getattr(plane, name) is None, name

    def test_a_requested_extra_is_populated(self):
        plane = ws.load_plane(make_synthetic_wrf(moisture=True),
                              extras=("rh", "tke"))
        assert plane.rh is not None and plane.tke is not None
        assert plane.qv is None          # not asked for

    def test_an_unknown_extra_is_refused(self):
        with pytest.raises(ValueError, match="unknown plane extras"):
            ws.load_plane(make_synthetic_wrf(), extras=("bogus",))

    def test_an_extra_the_run_cannot_supply_is_skipped_not_raised(self, capsys):
        """One config across runs with different output variable sets is the
        normal case; a hard failure would make the config non-portable."""
        plane = ws.load_plane(make_synthetic_wrf(), extras=("cloud", "tke"))
        assert plane.cloud is None and plane.tke is None
        assert "SKIP" in capsys.readouterr().out

    def test_tracers_carry_their_names_alongside_the_array(self):
        plane = ws.load_plane(make_synthetic_wrf(tracers=3), extras=("tracers",))
        assert plane.tracers.shape[0] == 3
        assert plane.tracer_names == ("tr17_1", "tr17_2", "tr17_3")

    def test_a_run_with_no_tracers_leaves_them_none(self):
        plane = ws.load_plane(make_synthetic_wrf(), extras=("tracers",))
        assert plane.tracers is None and plane.tracer_names == ()


class TestSectionCarriesThem:
    @pytest.fixture
    def section(self):
        plane = ws.load_plane(make_synthetic_wrf(moisture=True, tracers=2),
                              extras=("rh", "qv", "cloud", "vis", "tke",
                                      "theta_grad", "tracers"))
        return ws.section_from_plane(plane, A, B, n_points=12)

    def test_every_extra_reaches_the_curtain(self, section):
        for attr in ("rh2d", "qv2d", "cloud2d", "vis2d", "tke2d", "thetagrad2d"):
            assert getattr(section, attr) is not None, attr
        assert section.tracers2d.shape[0] == 2
        assert section.tracer_names == ("tr17_1", "tr17_2")

    def test_an_unsampled_extra_stays_none(self):
        plane = ws.load_plane(make_synthetic_wrf(moisture=True))
        sec = ws.section_from_plane(plane, A, B, n_points=8)
        assert sec.rh2d is None and sec.tracers2d is None

    def test_offgrid_samples_are_blanked_in_the_extras_too(self):
        """The whole point of blanking: nearest-neighbour has no upper bound, so
        an unblanked extra would extrude the boundary column across the gap and
        draw a flat, entirely physical-looking curtain."""
        plane = ws.load_plane(make_synthetic_wrf(moisture=True, tracers=2),
                              extras=("rh", "tracers"))
        # The synthetic grid stops at lon -109.5; run well past it.
        sec = ws.section_from_plane(plane, (40.25, -109.9), (40.25, -108.5),
                                    n_points=40)
        assert sec.offgrid1d.any()
        assert np.isnan(np.asarray(sec.rh2d)[:, sec.offgrid1d]).all()
        assert np.isnan(np.asarray(sec.tracers2d)[:, :, sec.offgrid1d]).all()
        # Geometry survives, so the axes and terrain fill stay well defined.
        assert np.isfinite(sec.height2d).all()


class TestPlanDiagnostics:
    def test_it_returns_only_what_the_run_can_supply(self):
        ds = make_synthetic_wrf()          # no QCLOUD
        out = ws.plan_diagnostics(ds, ["fog_depth", "theta_grad_sfc", "nonsense"])
        assert set(out) == {"theta_grad_sfc"}

    def test_case_knobs_reach_the_diagnostic(self):
        ds = make_synthetic_wrf()
        shallow = ws.plan_diagnostics(ds, ["theta_grad_sfc"],
                                      params={"theta_grad_sfc": {"depth_m": 100.0}})
        deep = ws.plan_diagnostics(ds, ["theta_grad_sfc"],
                                   params={"theta_grad_sfc": {"depth_m": 300.0}})
        assert np.asarray(shallow["theta_grad_sfc"]).shape == (6, 6)
        assert np.isfinite(deep["theta_grad_sfc"]).all()

    def test_the_result_is_usable_as_plan_dataset_extra(self):
        """The whole point of the helper: it feeds the `extra=` hook the
        convective engine already uses, so a derived field becomes a plain
        style-keyed variable the plan renderer can look a colour scale up for."""
        ds = make_synthetic_wrf(moisture=True)
        pds = ws.plan_dataset(ds, extra=ws.plan_diagnostics(
            ds, ["fog_depth", "visibility_sfc", "rnet_sfc"]))
        for key in ("fog_depth", "visibility_sfc", "rnet_sfc"):
            assert key in pds
        assert "wind_speed_10m" in pds     # the built-ins survive


def test_nearest_column_matches_the_dataset_helper():
    from brc_tools.nwp import wrf_output as wo

    ds = make_synthetic_wrf()
    plane = ws.load_plane(ds)
    assert ws.nearest_column(plane, 40.25, -109.75) == wo.nearest_column_index(
        ds, 40.25, -109.75)

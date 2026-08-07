"""Tests for brc_tools.nwp.wrf_derived -- the diagnostics WRF never writes.

Most of these pin a *convention* rather than a number, because the conventions
are where these fields go wrong silently: a visibility that is really an
extinction coefficient, a fog depth that counts a stratus deck a kilometre up, a
ceiling reported for air sitting on the ground, an energy budget assembled with
``GRDFLX`` the wrong way round.  All four look plausible on a map.
"""

from __future__ import annotations

import numpy as np
import pytest
from _wrf_synthetic import make_synthetic_wrf

from brc_tools.nwp import wrf_derived as wd


@pytest.fixture
def ds():
    return make_synthetic_wrf(moisture=True)


# --------------------------------------------------------------------------- #
# visibility and fog
# --------------------------------------------------------------------------- #
class TestVisibility:
    def test_clear_air_is_capped_not_infinite(self, ds):
        """With no hydrometeors the extinction is zero and the visual range is
        infinite, which is not a number a colour bar or a METAR can carry."""
        vis = wd.visibility_km(ds)
        assert np.isfinite(vis).all()
        assert vis.max() == pytest.approx(wd.VISIBILITY_MAX_KM)

    def test_the_fog_column_is_far_below_the_fog_threshold(self, ds):
        """0.5 g/kg of cloud water is dense fog: tens of metres, not hundreds."""
        vis = wd.visibility_km(ds)
        assert (vis[:2, :, 0] < 0.2).all()
        assert vis[:2, :, 1] == pytest.approx(wd.VISIBILITY_MAX_KM)

    def test_it_matches_stoelinga_warner_by_hand(self, ds):
        """A regression on the constants themselves: they are the whole physics
        here, and a transcription error would still produce a plausible map."""
        rho = wd.air_density(ds)[0, 0, 0]
        conc = 0.5 * rho  # g/kg -> g/m3
        beta = 144.7 * conc ** 0.88
        assert wd.visibility_km(ds)[0, 0, 0] == pytest.approx(-np.log(0.02) / beta)

    def test_negative_mixing_ratios_do_not_become_nan(self):
        """Advection undershoots leave small negatives; a power law on one is a
        NaN that propagates into the figure rather than an error anyone sees."""
        ds = make_synthetic_wrf(moisture=True)
        ds["QCLOUD"][:] = -1e-9
        assert np.isfinite(wd.visibility_km(ds)).all()


class TestFogDepth:
    def test_it_is_the_top_of_the_ground_based_layer(self, ds):
        """Two obscured levels, so the depth is the second level's height AGL."""
        depth = wd.fog_depth_m(ds)
        from brc_tools.nwp import wrf_output as wo

        assert depth[0, 0] == pytest.approx(wo.height_agl(ds)[1, 0, 0])

    def test_clear_ground_is_nan_not_zero(self, ds):
        """Zero-depth fog and no fog are the same thing physically, and a depth
        scale that paints the second one reads as shallow fog everywhere."""
        assert np.isnan(wd.fog_depth_m(ds)[:, 1:]).all()

    def test_an_elevated_deck_is_not_counted_as_fog(self):
        """Ground-based and CONTIGUOUS: obscuration aloft over clear ground is a
        cloud, and calling it fog is the failure this function exists to avoid."""
        ds = make_synthetic_wrf(moisture=True)
        ds["QCLOUD"][:] = 0.0
        ds["QCLOUD"][0, 2, :, :] = 0.5e-3  # level 2 only, nothing beneath it
        assert np.isnan(wd.fog_depth_m(ds)).all()


class TestCloud:
    def test_cloud_base_finds_the_lowest_cloudy_level(self, ds):
        from brc_tools.nwp import wrf_output as wo

        base = wd.cloud_base_agl(ds)
        assert base[0, 0] == pytest.approx(wo.height_agl(ds)[0, 0, 0])
        assert base[0, 1] == pytest.approx(wo.height_agl(ds)[2, 0, 1])

    def test_a_surface_obscuration_is_not_a_ceiling(self, ds):
        """Same computation as cloud_base, different question: a base at 5 m is
        fog, and an aviation reader must not read one as the other."""
        ceiling = wd.ceiling_agl(ds)
        assert np.isnan(ceiling[0, 0])          # the fog column
        assert np.isfinite(ceiling[0, 1])       # the genuine deck at level 2

    def test_layer_amounts_partition_by_pressure(self, ds):
        layers = wd.cloud_fraction_layers(ds)
        assert set(layers) == {"low", "mid", "high"}
        # The synthetic column runs 90-87 kPa, so every cloudy cell is "low".
        assert layers["low"].max() == pytest.approx(1.0)
        assert layers["mid"].max() == pytest.approx(0.0)
        assert layers["high"].max() == pytest.approx(0.0)


class TestHumidity:
    def test_saturated_air_is_a_hundred_percent(self):
        ds = make_synthetic_wrf()
        # Choose q so that e == e_s exactly at the surface values.
        t2, psfc = 270.0, 90000.0
        es = wd.saturation_vapour_pressure_pa(t2)
        ds["Q2"][:] = 0.622 * es / (psfc - es)
        assert wd.relative_humidity_2m(ds) == pytest.approx(100.0)

    def test_lcl_is_zero_for_saturated_air_and_positive_otherwise(self):
        ds = make_synthetic_wrf()
        assert (wd.lcl_height_agl(ds) > 0).all()   # the fixture's air is dry
        ds["Q2"][:] = 1.0                          # absurdly moist -> saturated
        assert (wd.lcl_height_agl(ds) == 0.0).all()


# --------------------------------------------------------------------------- #
# surface energy budget
# --------------------------------------------------------------------------- #
class TestEnergyBudget:
    def test_the_budget_closes_with_grdflx_positive_upward(self, ds):
        """The convention this package assumes, asserted rather than trusted.
        Getting it backwards turns a closed budget into a ~120 W/m2 error that
        still looks entirely plausible on a map."""
        terms = wd.surface_energy_balance(ds)
        assert terms["residual"] == pytest.approx(0.0, abs=1e-6)

    def test_the_opposite_sign_does_not_close(self, ds):
        """The discriminating test: if both signs closed, the assertion above
        would be measuring nothing."""
        t = wd.surface_energy_balance(ds)
        wrong = t["rnet"] - t["grdflx"] - t["hfx"] - t["lh"]
        assert np.abs(wrong).min() > 50.0

    def test_net_radiation_falls_back_when_the_boundary_fluxes_are_absent(self, ds):
        """A run that did not switch on the boundary flux diagnostics still has
        SWDOWN/GLW/ALBEDO/TSK, which is the common case."""
        assert "SWDNB" not in ds
        assert np.isfinite(wd.net_radiation(ds)).all()


# --------------------------------------------------------------------------- #
# stability and turbulence
# --------------------------------------------------------------------------- #
class TestStability:
    def test_theta_gradient_matches_the_synthetic_profile(self, ds):
        """theta rises 2 K per level and levels are 100 m apart."""
        from brc_tools.nwp import wrf_output as wo

        grad = wd.theta_gradient_k_per_100m(wo.potential_temperature(ds),
                                            wo.geopotential_height_mass(ds))
        assert grad == pytest.approx(2.0)

    def test_brunt_vaisala_is_positive_for_a_stable_profile(self, ds):
        from brc_tools.nwp import wrf_output as wo

        n2 = wd.brunt_vaisala_squared(wo.potential_temperature(ds),
                                      wo.geopotential_height_mass(ds))
        assert (n2 > 0).all()

    def test_surface_gradient_uses_a_bulk_difference_over_the_layer(self, ds):
        assert wd.surface_theta_gradient(ds, depth_m=100.0) == pytest.approx(2.0)

    def test_tke_is_half_of_qke(self, ds):
        """MYNN writes QKE, which is twice the TKE, and writes TKE_PBL as
        identically zero -- so plotting TKE_PBL gives a blank that looks real."""
        assert wd.turbulent_kinetic_energy(ds) == pytest.approx(0.2)

    def test_a_run_with_neither_says_so(self):
        with pytest.raises(KeyError, match="QKE"):
            wd.turbulent_kinetic_energy(make_synthetic_wrf())


# --------------------------------------------------------------------------- #
# the surface-diagnostic registry
# --------------------------------------------------------------------------- #
class TestRegistry:
    def test_every_key_has_a_style(self):
        """A diagnostic with no colour scale is a renderer KeyError inside a
        per-figure try/except, i.e. a figure silently missing from a sweep."""
        from brc_tools.visualize.style import VAR_STYLES

        missing = [k for k in wd.SURFACE_REQUIRES if k not in VAR_STYLES]
        assert not missing

    def test_availability_reflects_what_the_run_wrote(self):
        rich = wd.available_surface_diagnostics(make_synthetic_wrf(moisture=True))
        bare = wd.available_surface_diagnostics(make_synthetic_wrf())
        assert "fog_depth" in rich and "fog_depth" not in bare
        assert "theta_grad_sfc" in bare      # needs only T

    def test_every_available_key_actually_computes(self, ds):
        for key in wd.available_surface_diagnostics(ds):
            out = wd.surface_diagnostic(ds, key)
            assert np.asarray(out).shape == (6, 6), key

    def test_a_missing_ingredient_raises_rather_than_returning_zeros(self):
        with pytest.raises(KeyError, match="QCLOUD"):
            wd.surface_diagnostic(make_synthetic_wrf(), "fog_depth")

    def test_an_unknown_key_is_refused(self, ds):
        with pytest.raises(KeyError, match="unknown surface diagnostic"):
            wd.surface_diagnostic(ds, "not_a_field")


def test_column_max_can_be_bounded_by_height(ds):
    from brc_tools.nwp import wrf_output as wo

    field = np.arange(4).reshape(4, 1, 1) * np.ones((4, 6, 6))
    z = wo.height_agl(ds)
    # Levels sit at 50/150/250/350 m AGL, so below 200 m keeps levels 0 and 1.
    assert wd.column_max(field, height=z, below_m=200.0) == pytest.approx(1.0)
    assert wd.column_max(field) == pytest.approx(3.0)

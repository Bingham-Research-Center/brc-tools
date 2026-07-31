"""Surface-mesoanalysis diagnostics -- the fields WRF does not write.

The signs are the whole point and are the easy thing to get backwards: every
field here is defined so that **positive means the feature being hunted**, so a
convergence line is a positive maximum rather than a negative one.  A sign error
would be invisible in the figure and would invert the diagnosis.
"""

from __future__ import annotations

import numpy as np
import pytest
from _wrf_synthetic import make_synthetic_wrf

from brc_tools.nwp import wrf_convective as wc


@pytest.fixture
def ds():
    return make_synthetic_wrf(convective=True)


class TestConvergenceSign:
    @staticmethod
    def _with_wind(ds, u, v):
        """Replace U10/V10 with 2-D fields, keeping the leading Time dimension."""
        ds = ds.copy()
        ds["U10"] = (ds["U10"].dims, np.asarray(u, dtype=float)[None, ...])
        ds["V10"] = (ds["V10"].dims, np.asarray(v, dtype=float)[None, ...])
        return ds

    @staticmethod
    def _shape(ds):
        return ds["U10"].shape[-2:]

    def test_confluent_flow_is_positive_convergence(self, ds):
        """u decreasing eastward is air piling up: du/dx < 0, so -div > 0."""
        ny, nx = self._shape(ds)
        u = np.tile(np.linspace(5.0, -5.0, nx), (ny, 1))
        conv = wc.meso_field(self._with_wind(ds, u, np.zeros_like(u)), "conv_10m")
        assert np.nanmean(conv) > 0

    def test_diffluent_flow_is_negative(self, ds):
        ny, nx = self._shape(ds)
        u = np.tile(np.linspace(-5.0, 5.0, nx), (ny, 1))
        conv = wc.meso_field(self._with_wind(ds, u, np.zeros_like(u)), "conv_10m")
        assert np.nanmean(conv) < 0

    def test_uniform_flow_has_no_convergence(self, ds):
        u = np.full(self._shape(ds), 7.0)
        conv = wc.meso_field(self._with_wind(ds, u, u * 0.5), "conv_10m")
        assert np.allclose(conv, 0.0, atol=1e-9)


class TestGridSpacing:
    def test_gradient_uses_the_files_own_dx_not_the_3km_default(self, ds):
        """derived.horizontal_gradient_magnitude defaults to HRRR's 3 km.  Left
        alone, a 600 m nest would report every gradient five times too small."""
        from brc_tools.nwp import wrf_output as wo
        from brc_tools.nwp.derived import horizontal_gradient_magnitude

        dx, _dy = wo.dx_dy(ds)
        theta_e = wc.surface_theta_e(ds)
        got = wc.meso_field(ds, "theta_e_grad_2m")
        expected = np.asarray(horizontal_gradient_magnitude(theta_e, dx_m=dx)) * 1000.0
        assert np.allclose(got, expected)
        # and it must NOT match the default, or the test proves nothing
        wrong = np.asarray(horizontal_gradient_magnitude(theta_e, dx_m=3000.0)) * 1000.0
        assert not np.allclose(got, wrong)


class TestMoisture:
    def test_dewpoint_never_exceeds_temperature(self, ds):
        from brc_tools.nwp import wrf_output as wo

        td = wc.meso_field(ds, "dewpoint_2m")
        t = wo.surface_field(ds, "T2") - 273.15
        assert np.all(td <= t + 1e-6)

    def test_depression_is_temperature_minus_dewpoint(self, ds):
        dep = wc.meso_field(ds, "dewpoint_depression_2m")
        assert np.all(dep >= -1e-6)

    def test_theta_e_exceeds_theta(self, ds):
        """Latent heat is added, never removed -- theta_e < theta means the
        moisture term went in with the wrong sign."""
        from brc_tools.nwp import wrf_output as wo

        assert np.all(wc.surface_theta_e(ds) >= wo.theta_2m(ds) - 1e-6)


class TestMissingInputs:
    def test_a_field_whose_inputs_are_absent_raises_a_named_error(self):
        """The engine turns this into one named-skipped panel, so the message has
        to say which variable is missing rather than failing anonymously."""
        ds = make_synthetic_wrf(convective=True, drop_vars=("Q2",))
        with pytest.raises(KeyError, match="Q2"):
            wc.meso_field(ds, "theta_e_2m")

    def test_an_unknown_key_lists_the_known_ones(self, ds):
        with pytest.raises(KeyError, match="dewpoint_2m"):
            wc.meso_field(ds, "not_a_field")


def test_every_meso_field_has_a_style():
    """A field the engine can build but cannot colour is a job-killing KeyError
    at render time, not a missing panel."""
    from brc_tools.visualize.style import VAR_STYLES

    for key in wc.MESO_REQUIRES:
        assert key in VAR_STYLES, f"{key} has no VAR_STYLES entry"

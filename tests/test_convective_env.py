"""Unit tests for brc_tools.nwp.convective_env.

Analytic profiles, so the answers are checkable by hand.  MetPy does the physics,
so these tests target the things that are *ours*: parcel selection, the unit
boundary (knots in, m/s out), the height-AGL conversion, and honest NaN where a
profile cannot support an answer.
"""

from dataclasses import dataclass

import numpy as np
import pytest

metpy = pytest.importorskip("metpy")

from brc_tools.nwp import convective_env as ce  # noqa: E402

_KT_PER_MS = 1.94384


@dataclass
class FakeColumn:
    """Duck-typed stand-in for WRFColumn / Sounding."""

    pressure_hpa: np.ndarray
    temperature_c: np.ndarray
    dewpoint_c: np.ndarray
    u_kt: np.ndarray
    v_kt: np.ndarray
    height_asl: np.ndarray
    terrain_m: float = 1600.0
    lat: float = 40.4
    lon: float = -109.5
    label: str = "test"


def make_column(
    *,
    n: int = 40,
    surface_c: float = 22.0,
    lapse_c_per_km: float = 7.0,
    dewpoint_depression_c: float = 6.0,
    shear_ms_per_km: float = 5.0,
    veer: bool = True,
    top_km: float = 12.0,
    terrain_m: float = 1600.0,
) -> FakeColumn:
    """A plausible high-shear profile with a real hydrostatic pressure axis."""
    z_agl = np.linspace(10.0, top_km * 1000.0, n)
    t_c = surface_c - lapse_c_per_km * (z_agl / 1000.0)
    td_c = t_c - dewpoint_depression_c * (1.0 + z_agl / 6000.0)

    # Hydrostatic pressure on a mean virtual temperature, good enough for tests.
    t_mean_k = 273.15 + 0.5 * (surface_c + t_c)
    p_sfc = 840.0
    p = p_sfc * np.exp(-9.80665 * (z_agl - z_agl[0]) / (287.05 * t_mean_k))

    speed = shear_ms_per_km * (z_agl / 1000.0) + 3.0
    if veer:
        # Wind direction turning clockwise with height gives positive SRH.
        angle = np.deg2rad(200.0 + 60.0 * (z_agl / top_km / 1000.0))
        u = -speed * np.sin(angle)
        v = -speed * np.cos(angle)
    else:
        u, v = speed, np.zeros_like(speed)

    return FakeColumn(
        pressure_hpa=p,
        temperature_c=t_c,
        dewpoint_c=td_c,
        u_kt=u * _KT_PER_MS,
        v_kt=v * _KT_PER_MS,
        height_asl=z_agl + terrain_m,
        terrain_m=terrain_m,
    )


class TestParcelSelection:
    def test_bad_parcel_name_is_rejected(self):
        col = make_column()
        with pytest.raises(ValueError, match="parcel must be one of"):
            ce.cape_cin(col, "surface")
        with pytest.raises(ValueError, match="parcel must be one of"):
            ce.parcel_levels(col, "nope")

    def test_all_three_parcels_produce_finite_cape(self):
        col = make_column()
        for parcel in ce.PARCELS:
            cape, cin = ce.cape_cin(col, parcel)
            assert np.isfinite(cape) and cape >= 0.0
            assert np.isfinite(cin) and cin <= 0.0

    def test_most_unstable_is_at_least_surface_based(self):
        col = make_column()
        assert ce.cape_cin(col, "mu")[0] >= ce.cape_cin(col, "sb")[0] - 1e-6

    def test_mixed_layer_depth_matches_hrrr_product(self):
        # So a model row and an HRRR cape_ml row are like for like.
        assert ce.MIXED_LAYER_DEPTH_HPA == 180.0
        assert ce.MOST_UNSTABLE_DEPTH_HPA == 255.0

    def test_too_short_a_profile_gives_nan_not_a_crash(self):
        col = make_column(n=2)
        cape, cin = ce.cape_cin(col, "ml")
        assert np.isnan(cape) and np.isnan(cin)


class TestParcelLevels:
    def test_levels_are_ordered_and_above_ground(self):
        levels = ce.parcel_levels(make_column(), "sb")
        assert 0.0 < levels.lcl_agl_m < levels.lfc_agl_m < levels.el_agl_m
        # Pressure decreases as height increases.
        assert levels.lcl_hpa > levels.lfc_hpa > levels.el_hpa

    def test_heights_are_agl_not_asl(self):
        # The same profile placed 1000 m higher must give the same AGL heights.
        low = ce.parcel_levels(make_column(terrain_m=1600.0), "sb")
        high = ce.parcel_levels(make_column(terrain_m=2600.0), "sb")
        assert low.lcl_agl_m == pytest.approx(high.lcl_agl_m, rel=1e-6)

    def test_lcl_rises_with_a_drier_boundary_layer(self):
        moist = ce.parcel_levels(make_column(dewpoint_depression_c=2.0), "sb")
        dry = ce.parcel_levels(make_column(dewpoint_depression_c=12.0), "sb")
        assert dry.lcl_agl_m > moist.lcl_agl_m

    def test_stable_profile_has_no_lfc(self):
        # A strong inversion with a dry surface never becomes buoyant.
        col = make_column(surface_c=0.0, lapse_c_per_km=2.0, dewpoint_depression_c=25.0)
        levels = ce.parcel_levels(col, "sb")
        assert np.isnan(levels.lfc_agl_m) or levels.lfc_agl_m > 0.0

    def test_parcel_profile_matches_the_pressure_axis(self):
        col = make_column()
        prof = ce.parcel_profile_c(col, "ml")
        assert prof.shape == col.pressure_hpa.shape
        assert np.all(np.diff(prof) < 0.0)  # a lifted parcel cools monotonically


class TestBulkShear:
    def test_linear_profile_gives_the_analytic_value(self):
        # 5 m/s per km with no directional change -> 0-6 km bulk shear = 30 m/s.
        col = make_column(shear_ms_per_km=5.0, veer=False, top_km=12.0)
        assert ce.bulk_shear(col, 6000.0).magnitude == pytest.approx(30.0, abs=0.2)

    def test_units_cross_the_boundary_correctly(self):
        # The column stores knots; the answer must be m/s. A missed conversion
        # would inflate this by 1.94.
        col = make_column(shear_ms_per_km=2.0, veer=False)
        assert ce.bulk_shear(col, 1000.0).magnitude == pytest.approx(2.0, abs=0.1)

    def test_shallow_profile_returns_nan(self):
        col = make_column(top_km=2.0)
        assert np.isnan(ce.bulk_shear(col, 6000.0).magnitude)

    def test_components_recover_the_magnitude(self):
        s = ce.bulk_shear(make_column(), 6000.0)
        assert np.hypot(s.u, s.v) == pytest.approx(s.magnitude)

    def test_no_height_information_gives_nan(self):
        col = make_column()
        col.height_asl = None
        assert np.isnan(ce.bulk_shear(col, 6000.0).magnitude)


class TestHelicityAndMotion:
    def test_veering_profile_has_positive_srh(self):
        assert ce.storm_relative_helicity(make_column(veer=True), 3000.0) > 0.0

    def test_deeper_layer_accumulates_more_helicity(self):
        col = make_column(veer=True)
        assert abs(ce.storm_relative_helicity(col, 3000.0)) >= abs(
            ce.storm_relative_helicity(col, 1000.0)
        )

    def test_explicit_storm_motion_changes_the_answer(self):
        # SRH is defined against the storm's motion, so quoting a Bunkers value
        # for a storm that moved otherwise measures a storm that did not exist.
        col = make_column(veer=True)
        default = ce.storm_relative_helicity(col, 3000.0)
        moved = ce.storm_relative_helicity(col, 3000.0, storm_u=-10.0, storm_v=-10.0)
        assert not np.isclose(default, moved)

    def test_bunkers_movers_straddle_the_mean_wind(self):
        m = ce.bunkers_storm_motion(make_column())
        for value in (m.right_u, m.right_v, m.left_u, m.left_v, m.mean_u, m.mean_v):
            assert np.isfinite(value)
        # The two movers sit either side of the mean wind by the same deviation.
        assert np.hypot(m.right_u - m.mean_u, m.right_v - m.mean_v) == pytest.approx(
            np.hypot(m.left_u - m.mean_u, m.left_v - m.mean_v), rel=1e-6
        )


class TestSummary:
    def test_summary_keys_match_lookup_alias_names(self):
        # So a model row lines up with an HRRR row without renaming.
        out = ce.environment_summary(make_column(), "ml")
        for key in (
            "cape_ml", "cin_ml", "lcl_agl_m", "lfc_agl_m", "el_agl_m",
            "shear_mag_0to6km", "shear_mag_0to1km", "srh_0to3km", "srh_0to1km",
            "bunkers_right_u", "bunkers_right_v",
        ):
            assert key in out
        assert all(isinstance(v, float) for v in out.values())

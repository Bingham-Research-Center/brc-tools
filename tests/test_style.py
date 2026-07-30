"""Unit tests for brc_tools.visualize.style."""

from __future__ import annotations

import numpy as np

from brc_tools.visualize import style as st


def test_registry_theta_range_is_clipped_low_layer():
    s = st.get_style("theta")
    assert (s.vmin, s.vmax) == (270.0, 300.0)
    assert s.cmap == "RdYlBu_r"


def test_diff_style_is_symmetric_diverging():
    d = st.diff_style("theta")
    assert d.diverging is True
    assert d.cmap == "RdBu_r"
    assert d.vmin == -5.0 and d.vmax == 5.0
    assert d.label.startswith(r"$\Delta$")


def test_diff_style_feedback_uses_smaller_limit():
    assert st.diff_style("theta", feedback=True).vmax == 3.0


def test_diff_style_explicit_limit():
    d = st.diff_style("snow_depth", limit=0.1)
    assert (d.vmin, d.vmax) == (-0.1, 0.1)


def test_shared_range_robust():
    a = np.array([0.0, 1.0, 2.0, 3.0, 100.0])  # outlier trimmed by 99th pct
    lo, hi = st.shared_range(a, np.array([0.5, 1.5]))
    assert lo <= 0.5
    assert hi < 100.0


def test_symmetric_limit_capped():
    a = np.array([-2.0, 5.0, -8.0])
    assert st.symmetric_limit(a, cap=4.0) == 4.0


def test_resolve_style_default_is_fixed():
    assert st.resolve_style("theta_2m") == st.get_style("theta_2m")


def test_resolve_style_autoscale_nulls_limits():
    base = st.get_style("theta_2m")
    a = st.resolve_style("theta_2m", autoscale=True)
    assert a.vmin is None and a.vmax is None
    assert a.cmap == base.cmap and a.label == base.label


def test_resolve_style_override_wins_over_autoscale():
    ov = st.VarStyle("viridis", "custom", vmin=1.0, vmax=2.0)
    got = st.resolve_style("theta_2m", overrides={"theta_2m": ov}, autoscale=True)
    assert got is ov


def test_use_publication_style_sets_rcparams(tmp_path, monkeypatch):
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
    import matplotlib

    st.use_publication_style(dpi=300)
    assert matplotlib.rcParams["savefig.dpi"] == 300
    assert matplotlib.rcParams["mathtext.fontset"] == "stixsans"
    assert matplotlib.rcParams["font.family"] == ["sans-serif"]
    assert "Nimbus Sans" in matplotlib.rcParams["font.sans-serif"]


class TestConvectiveStyles:
    """Limits come from measured values on the Ashley run, not Plains intuition.

    A Basin environment with 580-980 J/kg MLCAPE renders as uniformly blank on a
    scale built for 4000 J/kg, which is the failure this class pins down.
    """

    def test_every_convective_key_is_registered(self):
        for key in (
            "refl_comp", "refl", "refl_beam", "echo_top", "uphel_2to5km",
            "uphel_0to3km", "vert_vorticity", "srh_0to3km", "srh_0to1km",
            "cape_ml", "cape_mu", "cin_ml", "shear_mag_0to6km",
            "shear_mag_0to1km", "wspd10max", "hail_max", "tornado_mask", "llws",
        ):
            assert key in st.VAR_STYLES, f"{key} missing from VAR_STYLES"

    def test_reflectivity_spans_the_observed_range(self):
        s = st.VAR_STYLES["refl_comp"]
        # 5 dBZ floor keeps clear air unpainted; the run's domain max was 70.6.
        assert (s.vmin, s.vmax) == (5.0, 75.0)
        assert s.extend == "max"

    def test_cape_scale_fits_a_basin_environment(self):
        s = st.VAR_STYLES["cape_ml"]
        assert (s.vmin, s.vmax) == (0.0, 1200.0)
        # Gate A0 measured 580-980 J/kg, so the range must resolve that band.
        assert s.vmax < 2000.0, "a Plains-width CAPE scale renders this event blank"

    def test_cin_is_negative_and_extends_downward(self):
        s = st.VAR_STYLES["cin_ml"]
        assert s.vmin == -400.0 and s.vmax == 0.0
        assert s.extend == "min"

    def test_max_wind_scale_exceeds_the_winter_one(self):
        # Domain-max 10 m wind reached 33.9 m/s; the winter style saturates at 15.
        assert st.VAR_STYLES["wspd10max"].vmax >= 33.9
        assert st.VAR_STYLES["wspd10max"].vmax > st.VAR_STYLES["wind_speed_10m"].vmax

    def test_vorticity_is_diverging_and_symmetric(self):
        s = st.VAR_STYLES["vert_vorticity"]
        assert s.diverging is True
        assert s.vmin == -s.vmax
        # Deliberately set for a boundary shear line (1-5e-3), letting storm
        # cores (~20e-3) saturate; extend="both" declares that on the bar.
        assert s.extend == "both"

    def test_srh_covers_the_measured_maximum(self):
        # 0-3 km SRH reached 824 m2 s-2 at 02Z in the 23Z cycle.
        assert st.VAR_STYLES["srh_0to3km"].vmax >= 824.0

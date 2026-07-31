"""Unit tests for brc_tools.visualize.profile."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pytest
from _wrf_synthetic import make_synthetic_wrf

from brc_tools.nwp import wrf_output as wo
from brc_tools.visualize.profile import (
    PlaceholderFileSounding,
    Sounding,
    plot_skewt,
    plot_theta_profiles,
    plot_theta_wind_profile,
    sounding_from_column,
)


def test_plot_theta_profiles_writes_png(tmp_path, monkeypatch):
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
    ds = make_synthetic_wrf(nz=8, ny=10, nx=10)
    cols = {
        "run A": wo.extract_column(ds, 40.3, -109.7),
        "run B": wo.extract_column(ds, 40.5, -109.5),
    }
    out = tmp_path / "theta.png"

    plot_theta_profiles(cols, out, terrain_m=1590.0, crest_m=2200.0, title="theta(z)")

    assert out.exists() and out.stat().st_size > 0


def test_plot_skewt_writes_png(tmp_path, monkeypatch):
    pytest.importorskip("metpy")
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
    ds = make_synthetic_wrf(nz=12, ny=8, nx=8)
    col = wo.extract_column(ds, 40.3, -109.7)
    snd = sounding_from_column(col, source="WRF", station="TEST",
                               valid_time=dt.datetime(2013, 2, 2, 12))
    out = tmp_path / "skewt.png"

    plot_skewt(snd, out, title="skew-T")

    assert out.exists() and out.stat().st_size > 0


def test_plot_theta_wind_profile_writes_png(tmp_path, monkeypatch):
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
    ds = make_synthetic_wrf(nz=12, ny=10, nx=10)
    col = wo.extract_column(ds, 40.3, -109.7)
    m12 = sounding_from_column(col, source="WRF", station="T", valid_time=dt.datetime(2013, 2, 2, 12))
    m13 = sounding_from_column(col, source="WRF", station="T", valid_time=dt.datetime(2013, 2, 2, 13))
    # Observed sounding with NO reported height -> exercises the hydrostatic fallback.
    obs = Sounding(
        pressure_hpa=np.array([850.0, 800.0, 700.0, 500.0]),
        temperature_c=np.array([-5.0, -7.0, -12.0, -25.0]),
        dewpoint_c=np.array([-8.0, -10.0, -18.0, -35.0]),
        u_kt=np.array([5.0, 8.0, 12.0, 20.0]),
        v_kt=np.array([1.0, 2.0, 3.0, 5.0]),
        source="RAOB", station="T", valid_time=dt.datetime(2013, 2, 2, 12),
    )
    out = tmp_path / "thetaz.png"

    plot_theta_wind_profile({"12Z": m12, "13Z": m13}, out, obs=obs, title="thetaz", crest_m=2200.0)

    assert out.exists() and out.stat().st_size > 0


def test_placeholder_sounding_raises():
    with pytest.raises(NotImplementedError):
        PlaceholderFileSounding().get("OURAY", dt.datetime(2013, 2, 2, 12))


class TestSkewTConvectiveAdditions:
    """The convective options are opt-in; defaults must reproduce the old figure.

    The pelican evidence packet pins a brc-tools SHA, so a default-argument call
    has to render exactly what it rendered before these options existed.
    """

    @staticmethod
    def _sounding():
        import numpy as np

        from brc_tools.visualize.profile import Sounding

        z = np.linspace(10.0, 12000.0, 40)
        t = 22.0 - 7.0 * z / 1000.0
        p = 840.0 * np.exp(-9.80665 * (z - z[0]) / (287.05 * (273.15 + 0.5 * (22.0 + t))))
        speed = 3.0 + 5.0 * z / 1000.0
        return Sounding(
            pressure_hpa=p,
            temperature_c=t,
            dewpoint_c=t - 6.0,
            u_kt=speed * 1.94384,
            v_kt=np.zeros_like(speed),
            source="test",
            station="TST",
            height_m=z + 1600.0,
        )

    def test_default_axis_limits_are_unchanged(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
        import inspect

        from brc_tools.visualize.profile import plot_skewt

        sig = inspect.signature(plot_skewt)
        assert sig.parameters["p_bottom_hpa"].default == 1000.0
        assert sig.parameters["p_top_hpa"].default == 500.0
        assert sig.parameters["t_range"].default == (-40.0, 20.0)
        # And the convective extras default to off.
        assert sig.parameters["parcel"].default is None
        assert sig.parameters["mark_levels"].default is False
        assert sig.parameters["shade_cape"].default is False

    def test_default_call_still_renders(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
        from brc_tools.visualize.profile import plot_skewt

        out = tmp_path / "default.png"
        assert plot_skewt(self._sounding(), out, title="default") == out
        assert out.stat().st_size > 0

    def test_parcel_overlay_changes_the_figure(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
        from brc_tools.visualize.profile import plot_skewt

        snd = self._sounding()
        plain = tmp_path / "plain.png"
        parcelled = tmp_path / "parcel.png"
        plot_skewt(snd, plain, title="t")
        plot_skewt(snd, parcelled, title="t", parcel="ml", mark_levels=True,
                   shade_cape=True, p_top_hpa=150.0)
        assert plain.stat().st_size != parcelled.stat().st_size

    def test_a_parcel_failure_does_not_kill_the_figure(self, tmp_path, monkeypatch):
        # The T/Td traces are the primary content; a profile too short to lift a
        # parcel must still produce a skew-T.
        monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
        import numpy as np

        from brc_tools.visualize.profile import Sounding, plot_skewt

        tiny = Sounding(
            pressure_hpa=np.array([840.0, 800.0]),
            temperature_c=np.array([20.0, 18.0]),
            dewpoint_c=np.array([10.0, 9.0]),
            u_kt=np.array([5.0, 6.0]),
            v_kt=np.array([0.0, 0.0]),
            source="test",
            station="TST",
        )
        out = tmp_path / "tiny.png"
        assert plot_skewt(tiny, out, title="t", parcel="ml", mark_levels=True) == out
        assert out.stat().st_size > 0


# --------------------------------------------------------------------------- #
# opt-in profile options (PR-B) -- all default off so `thetaz` is unchanged
# --------------------------------------------------------------------------- #
def _demo_sounding():
    from brc_tools.visualize.profile import Sounding

    z = np.linspace(1500.0, 5000.0, 40)
    p = 1013.25 * (1.0 - 2.25577e-5 * z) ** 5.25588
    t = 20.0 - 6.5e-3 * (z - 1500.0)
    return Sounding(
        pressure_hpa=p, temperature_c=t, dewpoint_c=t - 8.0,
        u_kt=np.linspace(2.0, 40.0, z.size), v_kt=np.full(z.size, 5.0),
        source="WRF", station="demo", height_m=z,
    )


def test_barb_levels_are_paced_in_height_not_level_index():
    """Eta levels are stretched, so every-nth-level crowds the surface.  A fixed
    metre interval must give near-uniform height spacing whatever the grid."""
    from brc_tools.visualize.profile import _barb_levels

    # deliberately stretched: dense low down, sparse aloft
    z = 1500.0 + np.cumsum(np.linspace(10.0, 400.0, 60))
    idx = _barb_levels(z, z_top=z.max(), interval_m=500.0)
    gaps = np.diff(z[idx])
    assert gaps.min() > 250.0        # nothing crowded together
    assert gaps.max() < 900.0        # nothing left bare


def test_barb_levels_default_keeps_the_historical_count():
    from brc_tools.visualize.profile import _barb_levels

    z = np.linspace(1500.0, 5000.0, 80)
    assert _barb_levels(z, z_top=5000.0).size == 14


def test_humidity_trace_rh_is_percent_not_a_fraction():
    """derived.relative_humidity already returns 0-100; scaling it again would
    put every value off the axis."""
    from brc_tools.visualize.profile import _humidity_trace

    vals, label = _humidity_trace(_demo_sounding(), "rh")
    assert "%" in label
    assert 10.0 < float(np.nanmax(vals)) <= 100.0


def test_humidity_trace_q_is_positive_and_in_g_per_kg():
    from brc_tools.visualize.profile import _humidity_trace

    vals, label = _humidity_trace(_demo_sounding(), "q")
    assert "q" in label
    assert 0.0 < float(np.nanmax(vals)) < 40.0


def test_humidity_kind_is_validated():
    from brc_tools.visualize.profile import _humidity_trace

    with pytest.raises(ValueError, match="rh"):
        _humidity_trace(_demo_sounding(), "specific")


def test_profile_options_default_off_so_thetaz_is_unchanged():
    """The pelican `thetaz` family calls this renderer.  Every option added for
    the winds engine must be opt-in or that frozen figure set moves."""
    import inspect

    from brc_tools.visualize.profile import plot_theta_wind_profile

    sig = inspect.signature(plot_theta_wind_profile).parameters
    assert sig["humidity"].default is None
    assert sig["wind_bars"].default is False
    assert sig["barb_interval_m"].default is None


def test_theta_wind_profile_renders_with_every_option_on(tmp_path):
    from brc_tools.visualize.profile import plot_theta_wind_profile

    out = plot_theta_wind_profile(
        {"02Z": _demo_sounding()}, tmp_path / "p.png", title="WRF | demo",
        humidity="rh", wind_bars=True, barb_interval_m=400.0, dpi=60,
    )
    assert out.exists() and out.stat().st_size > 0

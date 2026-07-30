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

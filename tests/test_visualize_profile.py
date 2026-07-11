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

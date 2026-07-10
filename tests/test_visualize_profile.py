"""Unit tests for brc_tools.visualize.profile."""

from __future__ import annotations

import datetime as dt

import pytest
from _wrf_synthetic import make_synthetic_wrf

from brc_tools.nwp import wrf_output as wo
from brc_tools.visualize.profile import (
    PlaceholderFileSounding,
    plot_skewt,
    plot_theta_profiles,
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


def test_placeholder_sounding_raises():
    with pytest.raises(NotImplementedError):
        PlaceholderFileSounding().get("OURAY", dt.datetime(2013, 2, 2, 12))

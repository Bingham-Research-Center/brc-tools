"""Unit tests for brc_tools.visualize.surface and the scalar time series."""

from __future__ import annotations

import datetime as dt

import numpy as np
from _wrf_synthetic import make_synthetic_wrf

from brc_tools.nwp import wrf_output as wo
from brc_tools.visualize.style import get_style
from brc_tools.visualize.surface import plot_domain_panels, plot_field_difference
from brc_tools.visualize.timeseries import plot_scalar_timeseries


def _panel(ds, label):
    return {
        "label": label,
        "lon": wo.surface_field(ds, "XLONG"),
        "lat": wo.surface_field(ds, "XLAT"),
        "field": wo.theta_2m(ds),
        "terrain": wo.surface_field(ds, "HGT"),
        "u": wo.surface_field(ds, "U10"),
        "v": wo.surface_field(ds, "V10"),
    }


def test_plot_domain_panels_writes_png(tmp_path, monkeypatch):
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
    ds = make_synthetic_wrf(nz=4, ny=10, nx=10)
    panels = [_panel(ds, "d01"), _panel(ds, "d02"), _panel(ds, "d03")]
    out = tmp_path / "panels.png"

    result = plot_domain_panels(
        panels, out, style=get_style("theta_2m"), wind=True,
        suptitle="2 m theta", waypoints={"hp": {"lat": 40.3, "lon": -109.7}},
    )

    assert result == out
    assert out.exists() and out.stat().st_size > 0


def test_plot_field_difference_writes_png(tmp_path, monkeypatch):
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
    ds = make_synthetic_wrf(nz=4, ny=10, nx=10)
    a = wo.theta_2m(ds)
    b = wo.theta_2m(ds) + 1.5
    out = tmp_path / "diff.png"

    plot_field_difference(
        wo.surface_field(ds, "XLONG"), wo.surface_field(ds, "XLAT"), a, b, out,
        var="theta", limit=5.0, title="A - B", terrain=wo.surface_field(ds, "HGT"),
    )

    assert out.exists() and out.stat().st_size > 0


def test_plot_scalar_timeseries_writes_png(tmp_path, monkeypatch):
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
    times = [dt.datetime(2013, 2, 2, h) for h in (12, 13, 14)]
    series = {
        "GFS": (times, np.array([1.0, 2.0, 3.0])),
        "NAM": (times, np.array([1.5, 2.5, 2.0])),
    }
    out = tmp_path / "ts.png"

    plot_scalar_timeseries(series, out, ylabel="heat deficit (J m-2)", title="cold pool")

    assert out.exists() and out.stat().st_size > 0

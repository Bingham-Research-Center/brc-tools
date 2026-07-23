"""Unit tests for the forecast-funnel data layer + renderer (no network).

The NAM fetch is monkeypatched with a synthetic CONUS grid, so these exercise the
source auto-pick, the diagnostics (H/L centres, TFP), the panel-building crop, and the
headless montage render without touching Herbie or NCEI.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pytest

from brc_tools.nwp import forecast_funnel as ff
from brc_tools.nwp.forecast_funnel import (
    FunnelData,
    Panel,
    _assemble_full,
    absolute_vorticity,
    fetch_funnel_fields,
    funnel_source_for,
    pressure_centers,
    specific_humidity_g_per_kg,
    thermal_front_parameter,
)


# ── source auto-pick ────────────────────────────────────────────────────────
def test_funnel_source_for_recent_is_herbie():
    assert funnel_source_for(dt.datetime(2026, 7, 20, 0)) == "herbie"
    assert funnel_source_for(dt.datetime(2021, 1, 1, 0)) == "herbie"


def test_funnel_source_for_historical_is_ncei():
    assert funnel_source_for(dt.datetime(2013, 1, 31, 0)) == "ncei"
    assert funnel_source_for(dt.datetime(2016, 12, 1, 0)) == "ncei"


def test_funnel_source_for_gap_raises():
    with pytest.raises(ValueError, match="No NAM source"):
        funnel_source_for(dt.datetime(2018, 6, 1, 0))


# ── humidity helper ─────────────────────────────────────────────────────────
def test_specific_humidity_direct():
    q = specific_humidity_g_per_kg(np.array([0.006, 0.003]))
    np.testing.assert_allclose(q, [6.0, 3.0])


def test_specific_humidity_derived_from_rh_is_positive():
    q = specific_humidity_g_per_kg(rh_pct=np.array([80.0]), temp_k=np.array([275.0]),
                                   pressure_hpa=600.0)
    assert q[0] > 0.0 and np.isfinite(q[0])


# ── diagnostics ─────────────────────────────────────────────────────────────
def _gaussian(lon2d, lat2d, lon0, lat0, amp, width=3.0):
    return amp * np.exp(-((lon2d - lon0) ** 2 + (lat2d - lat0) ** 2) / (2 * width**2))


def test_pressure_centers_finds_low_and_high():
    lon = np.linspace(-120.0, -100.0, 60)
    lat = np.linspace(30.0, 50.0, 60)
    lon2d, lat2d = np.meshgrid(lon, lat)
    field = (1013.0
             - _gaussian(lon2d, lat2d, -112.0, 40.0, 20.0)   # a Low
             + _gaussian(lon2d, lat2d, -104.0, 44.0, 15.0))  # a High
    centers = pressure_centers(field, lon2d, lat2d, window_pts=11, min_sep_deg=3.0)
    lows = [c for c in centers if c["kind"] == "L"]
    highs = [c for c in centers if c["kind"] == "H"]
    assert lows and highs
    # strongest low near (-112, 40); strongest high near (-104, 44)
    lo = min(lows, key=lambda c: c["value"])
    hi = max(highs, key=lambda c: c["value"])
    assert abs(lo["lon"] + 112.0) < 2.0 and abs(lo["lat"] - 40.0) < 2.0
    assert abs(hi["lon"] + 104.0) < 2.0 and abs(hi["lat"] - 44.0) < 2.0


def test_absolute_vorticity_cyclonic_positive():
    # Cyclonic shear (v increases eastward -> dv/dx > 0 -> positive relative vorticity),
    # plus planetary f, must exceed f alone at NH mid-latitudes.
    x = np.linspace(-115.0, -105.0, 40)
    y = np.linspace(38.0, 46.0, 40)
    lon2d, lat2d = np.meshgrid(x, y)
    u = np.zeros_like(lon2d)
    v = 1.0e-3 * (lon2d - lon2d.min()) * 111_000.0  # ~m/s ramp with longitude
    av = absolute_vorticity(u, v, lat2d, dx_m=12000.0, dy_m=12000.0)
    f_only = 2.0 * 7.2921e-5 * np.sin(np.deg2rad(42.0)) * 1e5
    assert np.isfinite(av).all()
    assert float(np.nanmean(av)) > f_only  # cyclonic relative vorticity adds to f


def test_thermal_front_parameter_nonzero_across_gradient():
    ny, nx = 40, 40
    # A sharp N-S temperature front (tanh) -> strong TFP in the transition band.
    y = np.linspace(-3, 3, ny)[:, None] * np.ones((1, nx))
    temp = 280.0 + 6.0 * np.tanh(y * 2.0)
    tfp = thermal_front_parameter(temp, dx_m=12000.0, dy_m=12000.0, smooth_sigma=1.0)
    assert np.isfinite(tfp).all()
    assert np.nanmax(np.abs(tfp)) > 0.0


# ── synthetic full grid + panel building ────────────────────────────────────
def _synthetic_full(levels=(250, 500, 600)):
    lon = np.linspace(-128.0, -64.0, 65)
    lat = np.linspace(20.0, 52.0, 33)
    lon2d, lat2d = np.meshgrid(lon, lat)
    base_h = {250: 10500.0, 500: 5600.0, 600: 4300.0}
    gh = {lv: base_h[lv] - 40.0 * (lat2d - 36.0) for lv in levels}
    u = {lv: np.full_like(lon2d, 20.0) for lv in levels}
    v = {lv: np.full_like(lon2d, 5.0) for lv in levels}
    t600 = 268.0 - 0.5 * (lat2d - 36.0)
    t850 = 285.0 - 0.5 * (lat2d - 36.0)
    q600 = np.full_like(lon2d, 3.0)
    mslp = (1013.0e2
            - _gaussian(lon2d, lat2d, -110.0, 42.0, 18.0) * 100.0
            + _gaussian(lon2d, lat2d, -95.0, 34.0, 12.0) * 100.0)
    return _assemble_full(
        lat2d=lat2d, lon2d=lon2d, levels=levels, gh=gh, u=u, v=v,
        t600=t600, t850=t850, u850=u[500], v850=v[500], q600_g_kg=q600, mslp_pa=mslp,
    )


def test_fetch_funnel_fields_builds_four_panels(monkeypatch):
    monkeypatch.setattr(ff, "_herbie_fetch_full",
                        lambda init_dt, levels, cache_dir: _synthetic_full(levels))
    data = fetch_funnel_fields("2026-07-20 00Z", source="herbie")
    assert isinstance(data, FunnelData)
    assert data.source == "herbie"
    assert data.init_time == data.valid_time == dt.datetime(2026, 7, 20, 0)
    kinds = {p.key: p.kind for p in data.panels}
    assert kinds == {"1a": "isotach", "1b": "vorticity",
                     "1c": "moisture", "1d": "synoptic"}
    # the local (1c) panel carries basin waypoints + thermal advection; surface = fronts
    p1c = next(p for p in data.panels if p.key == "1c")
    p1d = next(p for p in data.panels if p.key == "1d")
    assert p1c.waypoints and "duchesne" in p1c.waypoints
    assert "t_adv" in p1c.fields
    assert p1d.fronts is not None and "tfp" in p1d.fronts
    assert p1d.centers is not None


def test_fetch_funnel_fields_auto_picks_ncei(monkeypatch):
    captured = {}

    def fake_ncei(init_time, levels, cache_dir):
        captured["called"] = True
        return _synthetic_full(levels)

    monkeypatch.setattr(ff, "_ncei_fetch_full", fake_ncei)
    data = fetch_funnel_fields("2013-01-31 00Z", source="auto")
    assert captured.get("called") and data.source == "ncei"


# ── renderer (headless) ─────────────────────────────────────────────────────
def _panels_from(full):
    from brc_tools.nwp.source import load_lookups
    lu = load_lookups()
    return [ff._build_panel(full, spec, lu) for spec in ff.FUNNEL_PANELS]


def test_plot_forecast_funnel_writes_png(tmp_path):
    panels = [p for p in _panels_from(_synthetic_full()) if p is not None]
    data = FunnelData(init_time=dt.datetime(2026, 7, 20, 0),
                      valid_time=dt.datetime(2026, 7, 20, 0), source="herbie",
                      model_label="NAM test", panels=panels)
    from brc_tools.visualize.funnel import plot_forecast_funnel
    out = plot_forecast_funnel(data, tmp_path / "funnel.png", dpi=80)
    assert out.exists() and out.stat().st_size > 0


def test_synoptic_panel_draws_fronts():
    # A TFP field that crosses the 1.5 threshold within a uniform cold-advection region
    # must add a frontal contour; masking by advection sign (not the threshold) is what
    # lets contour find the crossing. Compare against the same panel with no TFP.
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from brc_tools.visualize.funnel import plot_synoptic_panel

    x = np.linspace(-120.0, -105.0, 30)
    y = np.linspace(35.0, 48.0, 26)
    lon, lat = np.meshgrid(x, y)
    mslp = 1013.0 - 0.2 * (lat - 40.0)
    ext = (-120.0, -105.0, 35.0, 48.0)
    tfp = 3.0 * (lat - 35.0) / 13.0          # ramps 0 -> 3, crosses 1.5
    adv = np.full_like(tfp, -1.0)            # all cold advection

    fig, (a0, a1) = plt.subplots(1, 2)
    plot_synoptic_panel(a0, lon, lat, mslp, centers=[], tfp=None, extent=ext)
    plot_synoptic_panel(a1, lon, lat, mslp, centers=[], tfp=tfp, t_adv=adv, extent=ext)
    assert len(a1.collections) > len(a0.collections)
    plt.close(fig)


def test_plot_forecast_funnel_refuses_repo_path():
    from brc_tools.visualize.funnel import _REPO_ROOT, plot_forecast_funnel
    data = FunnelData(init_time=dt.datetime(2026, 7, 20, 0),
                      valid_time=dt.datetime(2026, 7, 20, 0), source="herbie",
                      model_label="NAM test", panels=[])
    with pytest.raises(SystemExit, match="repo checkout"):
        plot_forecast_funnel(data, _REPO_ROOT / "figures" / "nope.png")

"""Unit tests for brc_tools.visualize.upperair."""

from __future__ import annotations

import numpy as np
from _wrf_synthetic import make_synthetic_wrf

from brc_tools.nwp import wrf_output as wo
from brc_tools.visualize.style import get_style
from brc_tools.visualize.upperair import (
    below_ground_mask,
    interp_to_height_surface,
    interp_to_pressure_surface,
    plot_height_surface,
    temperature_advection,
)


def test_interp_to_height_surface_and_masking():
    nz, ny, nx = 4, 3, 3
    z = np.stack([np.full((ny, nx), 1000.0 + 500.0 * k) for k in range(nz)])
    f = np.stack([np.full((ny, nx), 10.0 * k) for k in range(nz)])
    np.testing.assert_allclose(interp_to_height_surface(f, z, 1250.0), 5.0)
    assert np.all(np.isnan(interp_to_height_surface(f, z, 800.0)))   # below ground
    assert np.all(np.isnan(interp_to_height_surface(f, z, 3000.0)))  # above top


def test_interp_to_pressure_surface():
    nz, ny, nx = 4, 2, 2
    p = np.stack([np.full((ny, nx), 90000.0 - 1000.0 * k) for k in range(nz)])
    f = np.stack([np.full((ny, nx), float(k)) for k in range(nz)])
    np.testing.assert_allclose(interp_to_pressure_surface(f, p, 88500.0), 1.5)


def test_below_ground_mask():
    terrain = np.array([[2000.0, 2300.0]])
    assert below_ground_mask(2200.0, terrain).tolist() == [[False, True]]


def test_temperature_advection_sign():
    temp = np.tile(280.0 + 0.01 * np.arange(5), (5, 1))  # warmer to the east
    u = np.ones((5, 5))
    v = np.zeros((5, 5))
    adv = temperature_advection(temp, u, v, dx_m=250.0, dy_m=250.0)
    assert adv.shape == (5, 5)
    assert np.all(adv < 0)  # westerly into a warm-east gradient -> cold advection


def test_temperature_advection_presmooth_tames_noise():
    rng = np.random.default_rng(0)
    base = np.tile(280.0 + 0.01 * np.arange(20), (20, 1))
    noisy = base + rng.normal(0.0, 0.3, size=base.shape)  # add small-scale noise
    u = np.ones_like(base)
    v = np.zeros_like(base)
    raw = temperature_advection(noisy, u, v, dx_m=250.0, dy_m=250.0)
    smoothed = temperature_advection(noisy, u, v, dx_m=250.0, dy_m=250.0, smooth_sigma=2.0)
    # pre-gradient smoothing must reduce the advection field's roughness (variance)
    assert np.nanvar(smoothed) < np.nanvar(raw)


def test_plot_height_surface_writes_png(tmp_path, monkeypatch):
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
    ds = make_synthetic_wrf(nz=6, ny=12, nx=12)
    lon = wo.surface_field(ds, "XLONG")
    lat = wo.surface_field(ds, "XLAT")
    z = wo.geopotential_height_mass(ds)
    ue, ve = wo.earth_relative_winds(ds)
    target = 1700.0
    th = interp_to_height_surface(wo.potential_temperature(ds), z, target)
    u2 = interp_to_height_surface(ue, z, target)
    v2 = interp_to_height_surface(ve, z, target)
    out = tmp_path / "upper.png"

    plot_height_surface(lon, lat, th, u2, v2, out, terrain=wo.surface_field(ds, "HGT"),
                        target_label="1700 m ASL", style=get_style("theta"), title="crest")

    assert out.exists() and out.stat().st_size > 0

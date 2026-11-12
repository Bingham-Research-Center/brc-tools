"""brc_tools.flow.volume: the composition of the closures into theta and wind per cell."""
from __future__ import annotations

import numpy as np
import pytest

from brc_tools.flow import G, THETA0, volume


def profile():
    return volume.TwoLayerProfile(z_inv=1700.0, dtheta=6.0, N=0.010, N_pool=0.004)


def test_profile_slopes_jump_and_reference():
    p = profile()
    assert p.gamma_aloft == pytest.approx(THETA0 * 1e-4 / G)
    assert p.gamma_pool == pytest.approx(THETA0 * 1.6e-5 / G)
    assert p.gprime == pytest.approx(G * 6.0 / THETA0)
    assert float(p(1700.0 + 1e-9) - p(1700.0 - 1e-9)) == pytest.approx(6.0, abs=1e-6)
    z = np.array([1500.0, 1600.0])
    assert np.allclose(np.diff(p(z)), 100.0 * p.gamma_pool)
    assert np.allclose(np.diff(p.aloft(z)), 100.0 * p.gamma_aloft)         # the reference continues down
    # the deficit against the pool-free reference shrinks with depth: the reference is the more stable
    assert float(p.aloft(1500.0) - p(1500.0)) == pytest.approx(6.0 - 200.0 * (p.gamma_aloft - p.gamma_pool))


def test_ridge_capped_has_no_wall_at_the_footprint_edge():
    z_inv = 1700.0
    x = np.arange(200)
    base = np.where(x < 100, 1650.0, 1900.0)          # the right half's base stands above the lid
    h = np.where((x > 40) & (x < 160), 120.0 * np.sin(np.pi * (x - 40) / 120.0), 0.0)
    z = base + h
    obs = volume.ridge_capped(z, h, z_inv)
    assert np.allclose(obs[:100], np.clip(z[:100] - z_inv, 0, None))   # base below the lid: terrain above it
    assert np.allclose(obs[100:], h[100:])                               # base above the lid: the ridge alone
    assert obs[159] < 10.0 and obs[160] == 0.0                           # falls to zero at the edge


def test_planes_to_columns_is_linear_and_clamped():
    zetas = np.array([0.0, 50.0, 200.0, 1000.0])
    planes = (3.0 * zetas + 1.0)[:, None, None] * np.ones((1, 2, 3))
    zeta = np.array([-20.0, 0.0, 25.0, 120.0, 999.0, 1500.0])[:, None, None] * np.ones((1, 2, 3))
    got = volume.planes_to_columns(planes, zetas, zeta)
    assert np.allclose(got, 3.0 * np.clip(zeta, 0.0, 1000.0) + 1.0)


def _column_grid(hgt, nz=120, top=2400.0):
    frac = np.linspace(0.0, 1.0, nz)[:, None, None]
    return hgt[None] + frac * (top - hgt[None])


def test_compose_theta_at_rest_is_the_profile_and_a_lift_moves_the_jump():
    p = profile()
    hgt = np.array([[1500.0, 1600.0, 1800.0]])
    z = _column_grid(hgt)
    pool0 = hgt < p.z_inv
    lid = np.where(pool0, p.z_inv, np.nan)
    assert np.allclose(volume.compose_theta(z, hgt, lid, pool0, p), p(z))
    dz = 30.0
    th = volume.compose_theta(z, hgt, lid + dz, pool0, p)
    for i in (0, 1):
        below = z[:, 0, i] < p.z_inv + dz
        top_pool = th[below, 0, i][-1]
        first_aloft = th[~below, 0, i][0]
        assert top_pool == pytest.approx(p.pool(p.z_inv), abs=0.05)   # the top of the pool is lifted intact
        assert first_aloft - top_pool > 5.9                             # the jump moved up with it
    assert np.allclose(th[:, 0, 2], p.aloft(z[:, 0, 2]))                 # dry ground stays in the air aloft


def test_compose_theta_labels_lifted_air_aloft():
    p = profile()
    hgt = np.array([[1800.0]])
    z = _column_grid(hgt)
    eta = np.full(z.shape, 100.0)
    th = volume.compose_theta(z, hgt, np.full(hgt.shape, np.nan), np.zeros(hgt.shape, bool), p, eta_aloft=eta)
    assert np.allclose(th, p.aloft(np.maximum(z - 100.0, p.z_inv)))


def test_pool_extent_runs_up_breaks_through_and_respects_connection():
    zg = np.tile(np.concatenate([np.linspace(1600.0, 1800.0, 40), np.full(5, 1900.0), np.full(10, 1650.0)]), (3, 1))
    pool0 = (zg < 1700.0) & (np.arange(zg.shape[1]) < 40)[None]           # the far hollow is another pool
    eta = np.where(pool0, 20.0, np.nan)
    z_lid, wet, broken = volume.pool_extent(zg, 1700.0, eta, pool0, reach_cells=30)
    shore0 = np.argmax(~pool0[0])
    shore = np.argmax(~wet[0])
    assert shore > shore0 and np.nanmax(z_lid) == pytest.approx(1720.0)    # run-up on the slope
    assert not wet[:, 45:].any()                                           # the unconnected hollow stays dry
    # lid lowered 60 m to 1640 m: the deep end (ground below 1639 m) stays, the rest of the pool drains
    _, wet2, broken2 = volume.pool_extent(zg, 1700.0, np.where(pool0, -60.0, np.nan), pool0, reach_cells=30)
    deep = zg[0] < 1639.0
    assert wet2[0, deep].all() and not wet2[0, ~deep].any()
    assert broken2[0, pool0[0] & ~deep].all() and not broken2[0, deep].any()


def test_compose_winds_pool_current_and_kinematic_w():
    hgt = np.array([[1500.0, 1600.0]])
    z = _column_grid(hgt, nz=50, top=2200.0)
    lid = np.array([[1720.0, 1720.0]])
    wet = np.array([[True, True]])
    aloft = (np.full(z.shape, 12.0), np.zeros(z.shape), np.zeros(z.shape))
    gx, gy = np.array([[0.05, 0.05]]), np.zeros((1, 2))
    u, v, w = volume.compose_winds(z, hgt, lid, wet, aloft=aloft, pool_uv=(np.full((1, 2), 0.8), np.zeros((1, 2))),
                                   eta_rate=np.full((1, 2), 0.002), ground_grad=(gx, gy))
    pool = z < lid[None]
    assert np.allclose(u[pool], 0.8) and np.allclose(u[~pool], 12.0)
    assert w[0, 0, 0] == pytest.approx(0.8 * 0.05)                       # u . grad z_g at the bed
    top = np.max(np.where(pool[:, 0, 0])[0])
    frac = (z[top, 0, 0] - 1500.0) / (1720.0 - 1500.0)
    assert w[top, 0, 0] == pytest.approx(0.04 + frac * (0.002 - 0.04))  # linear to d(eta)/dt at the lid

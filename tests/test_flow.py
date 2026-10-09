"""brc_tools.flow against closed-form solutions."""
from __future__ import annotations

import numpy as np
import pytest

from brc_tools.flow import layer, leewaves, mountainwave, pool, seiche


def witch(x, h0, a):
    return h0 * a ** 2 / (x ** 2 + a ** 2)


# ----------------------------------------------------------------- mountainwave
def test_witch_hydrostatic_matches_analytic():
    """Hydrostatic 2-D Witch of Agnesi: eta = h0 a (a cos lz - x sin lz) / (x^2 + a^2)."""
    U, N, h0, a = 10.0, 0.01, 100.0, 10e3
    dx = 250.0
    x = (np.arange(4096) - 2048) * dx
    lw = mountainwave.linear_3d(witch(x, h0, a), dx, U, 0.0, N, hydrostatic=True, pad=4, eps=1e-7)
    lz = N / U
    for z in (0.0, np.pi / (2 * lz), np.pi / lz):
        exact = h0 * a * (a * np.cos(lz * z) - x * np.sin(lz * z)) / (x ** 2 + a ** 2)
        got = lw.eta(z)[0]
        inner = np.abs(x) < 40e3
        assert np.max(np.abs(got[inner] - exact[inner])) < 0.03 * h0


def test_witch_surface_wind_and_overturning():
    """u'(x, 0) = N h0 a x / (x^2 + a^2): max N h0 / 2 at x = a; -d(eta)/dz max = N h0 / U."""
    U, N, h0, a = 10.0, 0.01, 300.0, 10e3
    dx = 250.0
    x = (np.arange(4096) - 2048) * dx
    lw = mountainwave.linear_3d(witch(x, h0, a), dx, U, 0.0, N, hydrostatic=True, pad=4, eps=1e-7)
    u, _ = lw.uv(0.0)
    assert u[0].max() == pytest.approx(N * h0 / 2, rel=0.03)
    assert x[np.argmax(u[0])] == pytest.approx(a, rel=0.05)
    ov = max(lw.overturning(z)[0].max() for z in np.linspace(0, 3000, 61))
    assert ov == pytest.approx(N * h0 / U, rel=0.05)


def test_hydrostatic_surface_pressure_is_hilbert():
    """p'(x, 0) = rho0 U N h0 a x ... sign: high upstream, low in the lee."""
    U, N, h0, a = 10.0, 0.01, 100.0, 5e3
    dx = 100.0
    x = (np.arange(4096) - 2048) * dx
    lw = mountainwave.linear_3d(witch(x, h0, a), dx, U, 0.0, N, hydrostatic=True, pad=4, eps=1e-7)
    p = lw.p(0.0)[0]
    exact = -1.0 * U * N * h0 * a * x / (x ** 2 + a ** 2)
    inner = np.abs(x) < 30e3
    assert np.max(np.abs(p[inner] - exact[inner])) < 0.03 * U * N * h0
    assert p[np.argmin(np.abs(x + a))] > 0 > p[np.argmin(np.abs(x - a))]


def test_3d_wind_direction_follows_row_convention():
    """Rows run south to north: a northerly-bound wind (V) over a round hill gives the
    eastward-wind field transposed."""
    dx = 500.0
    y, x = np.mgrid[-32:32, -32:32] * dx
    h = 200.0 * np.exp(-(x ** 2 + y ** 2) / (2 * 3e3 ** 2))
    east = mountainwave.linear_3d(h, dx, 10.0, 0.0, 0.01, pad=2).p(0.0)
    north = mountainwave.linear_3d(h, dx, 0.0, 10.0, 0.01, pad=2).p(0.0)
    assert np.allclose(north, east.T, atol=1e-6 * np.abs(east).max() + 1e-9)
    assert east[32, 26] > 0 > east[32, 38]          # high to the west (upwind), low to the east


def test_layered_uniform_matches_linear_3d():
    """One layer, no jump: the layered solver is the non-hydrostatic 2-D solution."""
    U, N, h0, a = 10.0, 0.01, 50.0, 2e3
    dx = 100.0
    x = (np.arange(1024) - 512) * dx
    h = witch(x, h0, a)
    z = np.arange(0.0, 3001.0, 100.0)
    lay = mountainwave.layered_2d(h, dx, U, [mountainwave.Layer(np.inf, N)], z, pad=4, eps=1e-5)
    lw = mountainwave.linear_3d(h, dx, U, 0.0, N, hydrostatic=False, pad=4, eps=1e-5)
    for iz in (0, 10, 25):
        assert np.max(np.abs(lay.eta[iz] - lw.eta(z[iz])[0])) < 0.02 * h0
    assert np.max(np.abs(lay.u[0] - lw.uv(0.0)[0][0])) < 0.03 * N * h0


def test_layered_traps_waves_at_predicted_wavelength():
    """Scorer two-layer atmosphere: the lee wave train has the mode-1 wavelength."""
    U, N1, N2, H = 10.0, 0.02, 0.005, 1500.0
    assert leewaves.scorer_trapping(N1, N2, U, H) > 1
    lam = leewaves.trapped_wavelengths(U, N1, N2, H)[0]
    dx = 100.0
    x = (np.arange(2048) - 300) * dx
    h = witch(x, 50.0, 1000.0)
    z = np.array([0.0, 750.0])
    lay = mountainwave.layered_2d(h, dx, U, [mountainwave.Layer(H, N1), mountainwave.Layer(np.inf, N2)], z, pad=4)
    w = lay.w[1]
    lee = (x > 15e3) & (x < 120e3)
    spec = np.abs(np.fft.rfft(w[lee] * np.hanning(lee.sum())))
    freq = np.fft.rfftfreq(lee.sum(), d=dx)
    lam_obs = 1.0 / freq[np.argmax(spec[1:]) + 1]
    assert lam_obs == pytest.approx(lam, rel=0.08)


# ----------------------------------------------------------------- layer
def test_critical_height_limits():
    assert layer.critical_height(1.0) == pytest.approx(0.0)
    assert layer.critical_height(0.0) == pytest.approx(1.0)
    assert layer.regime(0.3, 0.1) == "subcritical"
    assert layer.regime(0.3, 0.9) == "controlled"
    assert layer.regime(2.0, 0.1) == "supercritical"
    assert layer.regime(2.0, 0.5) == "two states"


def test_controlled_flow_is_critical_at_crest_and_conserves():
    F0, M = 0.5, 0.5
    s = layer.controlled_flow(F0, M)
    q = s.u_up * s.d_up
    E = 0.5 * s.u_up ** 2 + s.d_up
    assert E - M == pytest.approx(1.5 * q ** (2 / 3), rel=1e-6)          # critical at the crest
    assert s.F_lee > 1 and s.d_up > 1 and s.bore_speed > 0
    assert 0.5 * s.u_lee ** 2 + s.d_lee == pytest.approx(E, rel=1e-6)     # same energy at the foot
    # bore: mass and momentum
    c = s.bore_speed
    assert (s.u_up + c) * s.d_up == pytest.approx(F0 + c, rel=1e-6)
    assert (s.u_up + c) ** 2 * s.d_up + s.d_up ** 2 / 2 == pytest.approx((F0 + c) ** 2 + 0.5, rel=1e-6)


def test_controlled_flow_at_threshold_has_no_bore():
    F0 = 0.4
    s = layer.controlled_flow(F0, float(layer.critical_height(F0)) + 1e-9)
    assert s.d_up == pytest.approx(1.0, abs=1e-3)


# ----------------------------------------------------------------- leewaves
def test_vosper_mode_exists_only_below_unit_froude():
    H, U = 1000.0, 10.0
    l2H = 0.5
    N2 = l2H * U / H
    for Fi, expect in ((0.6, True), (1.3, False)):
        gp = U ** 2 / (Fi ** 2 * H)
        jump = gp * 285.0 / 9.81
        lam = leewaves.trapped_wavelengths(U, 0.0, N2, H, jump)
        assert (lam.size > 0) == expect == leewaves.vosper_trapping(Fi, l2H)


def test_scorer_criterion_matches_root_finder():
    U, H = 10.0, 1000.0
    for N1, N2 in ((0.02, 0.005), (0.006, 0.005)):
        has = leewaves.trapped_wavelengths(U, N1, N2, H).size > 0
        assert has == (leewaves.scorer_trapping(N1, N2, U, H) > 1)


# ----------------------------------------------------------------- seiche, pool
def test_rectangular_pool_matches_merian():
    L, W, H, gp, dx = 20e3, 6e3, 200.0, 0.2, 250.0
    depth = np.full((int(W / dx), int(L / dx)), H)
    periods, shapes = seiche.basin_modes(depth, dx, gp, n_modes=2)
    assert periods[0] == pytest.approx(seiche.merian_period(L, H, gp), rel=0.01)
    s = shapes[0]
    assert np.sign(s[3, 1]) == -np.sign(s[3, -2])       # mode 1: the ends move in opposition


def test_open_ended_pool_matches_merian():
    L, W, H, gp, dx = 20e3, 6e3, 200.0, 0.2, 250.0
    depth = np.full((int(W / dx), int(L / dx) + 1), H)
    held = np.zeros_like(depth, dtype=bool)
    held[:, -1] = True                                   # the east end opens onto a big pool
    periods, _ = seiche.basin_modes(depth, dx, gp, n_modes=2, open_mask=held)
    assert periods[0] == pytest.approx(seiche.merian_period(L + dx / 2, H, gp, ends="open"), rel=0.02)


def test_soft_boundary_limits():
    dx = 100.0
    x = (np.arange(1024) - 512) * dx
    h = witch(x, 100.0, 2e3)
    stiff = pool.soft_boundary_2d(h, dx, 10.0, 0.01, gprime=100.0)
    soft = pool.soft_boundary_2d(h, dx, 10.0, 0.01, gprime=1e-3)
    assert np.allclose(stiff["zeta"], h, atol=1.5)
    assert np.ptp(soft["zeta"]) < 2.0                 # flat but for the mean level (k = 0)
    assert pool.interaction_number(10.0, 0.01, 0.1) == pytest.approx(1.0)
    assert pool.interface_displacement(20.0, 0.1) == pytest.approx(-200.0)


# ----------------------------------------------------------------- horizon (terrain.skyview)
def test_horizon_angles_and_shadow_behind_a_west_wall():
    from brc_tools.terrain.skyview import horizon_angles, in_shadow, sky_view
    res = 100.0
    z = np.zeros((40, 60))
    z[:, :10] = 500.0                                 # a wall 500 m high along the west edge
    az, ang = horizon_angles(z, res, n_az=36, max_km=6.0)
    col = 20                                          # 1000 m east of the wall's face (cell 9 -> 20 is 11 cells)
    expect = np.degrees(np.arctan(500.0 / (11 * res)))
    assert ang[27, 20, col] == pytest.approx(expect, abs=0.5)    # az 270 = due west
    assert ang[9, 20, col] == pytest.approx(0.0, abs=1e-6)       # az 90: flat to the east
    assert in_shadow(az, ang, 270.0, expect - 2.0)[20, col]
    assert not in_shadow(az, ang, 270.0, expect + 2.0)[20, col]
    assert not in_shadow(az, ang, 90.0, 1.0)[20, col]
    svf = sky_view(z, res, n_az=16, max_km=6.0)
    assert svf[20, col] < svf[20, -1] <= 1.0

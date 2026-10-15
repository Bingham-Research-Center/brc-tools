import numpy as np
import pytest

from brc_tools.flow import mountainwave as mw
from brc_tools.flow.profile import along_wind, brunt_vaisala, layer_stack, two_layer_fit


def hill(nx=96, ny=64, dx=250.0, h0=100.0, a=1500.0, b=4000.0):
    x = (np.arange(nx) - nx / 2) * dx
    y = (np.arange(ny) - ny / 2) * dx
    X, Y = np.meshgrid(x, y)
    return h0 / (1.0 + (X / a) ** 2 + (Y / b) ** 2) ** 1.5


def test_layered_3d_one_layer_matches_linear_3d():
    h = hill()
    dx, U, V, N = 250.0, 10.0, 3.0, 0.012
    zs = np.array([0.0, 300.0, 900.0])
    eps = 1e-5
    lw = mw.linear_3d(h, dx, U, V, N, pad=3, eps=eps)
    ref = lw.planes(zs, ("eta", "u", "v", "w"), dtype=np.float64)
    got = mw.layered_3d(h, dx, U, V, [mw.Layer(np.inf, N)], zs, pad=3, eps=eps, dtype=np.float64)
    for name in ("eta", "u", "v", "w"):
        scale = np.abs(ref[name]).max()
        assert np.abs(got[name] - ref[name]).max() < 1e-6 * scale, name


def test_layered_3d_reduces_to_layered_2d_along_a_long_ridge():
    nx, ny, dx = 128, 192, 200.0
    x = (np.arange(nx) - nx / 2) * dx
    y = (np.arange(ny) - ny / 2) * dx
    ridge = 150.0 / (1.0 + (x / 1200.0) ** 2)
    across = np.exp(-(y / 15000.0) ** 8)                # flat-topped: the middle rows see a 2-D ridge
    h = ridge[None, :] * across[:, None]
    U = 8.0
    layers = [mw.Layer(1200.0, 0.015), mw.Layer(np.inf, 0.006, jump=3.0)]
    zs = np.array([0.0, 400.0, 1000.0])
    eps = 2.0 * U / (nx * 4 * dx)
    two = mw.layered_2d(ridge, dx, U, layers, zs, pad=4, eps=eps)
    three = mw.layered_3d(h, dx, U, 0.0, layers, zs, pad=4, eps=eps, dtype=np.float64)
    mid = ny // 2
    # u' is the least 2-D of the three: the flow also goes round the ridge's ends, and the
    # 3-D solver damps u' with the complex sigma (as linear_3d) where the 2-D one uses U k
    for name, ref, tol in (("w", two.w, 0.03), ("eta", two.eta, 0.03), ("u", two.u, 0.12)):
        got = three[name][:, mid, :]
        assert np.abs(got - ref).max() < tol * np.abs(ref).max(), name
    assert np.abs(three["v"][:, mid, :]).max() < 0.05 * np.abs(three["u"]).max()


def test_layered_3d_single_precision_sweep_agrees():
    h = hill()
    zs = np.array([0.0, 300.0, 900.0])
    layers = [mw.Layer(800.0, 0.012), mw.Layer(np.inf, 0.006, jump=3.0)]
    a = mw.layered_3d(h, 250.0, 10.0, 3.0, layers, zs, pad=3, dtype=np.float64)
    b = mw.layered_3d(h, 250.0, 10.0, 3.0, layers, zs, pad=3, dtype=np.float64, r_dtype=np.complex64)
    for name in ("eta", "u", "v", "w"):
        assert np.abs(a[name] - b[name]).max() < 1e-4 * np.abs(a[name]).max(), name


def test_layered_3d_windowed_output_and_rejections():
    h = hill(nx=48, ny=32)
    zs = np.array([0.0, 200.0])
    out = mw.layered_3d(h, 250.0, 10.0, 0.0, [mw.Layer(np.inf, 0.01)], zs, pad=2,
                        window=(slice(4, 20), slice(8, 40)), fields=("w",))
    assert out["w"].shape == (2, 16, 32) and set(out) == {"w"}
    with pytest.raises(ValueError):
        mw.layered_3d(h[0], 250.0, 10.0, 0.0, [mw.Layer(np.inf, 0.01)], zs)
    with pytest.raises(ValueError):
        mw.layered_3d(h, 250.0, 10.0, 0.0, [mw.Layer(np.inf, 0.01)], zs, fields=("p",))


def test_along_wind_is_the_speed_for_a_wind_from_that_direction():
    s, d = 12.0, 40.0
    u, v = -s * np.sin(np.radians(d)), -s * np.cos(np.radians(d))
    assert abs(along_wind(u, v, d) - s) < 1e-9
    assert abs(along_wind(u, v, d + 180.0) + s) < 1e-9
    assert abs(along_wind(u, v, d + 90.0)) < 1e-9


def test_two_layer_fit_recovers_a_synthetic_profile():
    z = np.arange(0.0, 4001.0, 50.0)
    n1, n2, zi, jump, th0 = 0.006, 0.012, 1525.0, 4.0, 285.0
    g = 9.81
    th = np.where(z < zi, th0 + th0 * n1 ** 2 / g * (z - zi), th0 + jump + th0 * n2 ** 2 / g * (z - zi))
    fit = two_layer_fit(z, th, z_top=4000.0)
    assert abs(fit["z_inv"] - zi) <= 25.0
    assert abs(fit["dtheta"] - jump) < 0.05
    # N is defined with the layer's own mean theta, the synthetic profile with theta0: ~2 % apart aloft
    assert abs(fit["N_below"] - n1) < 2e-4 and abs(fit["N_above"] - n2) < 3e-4
    assert fit["rms_K"] < 1e-6 and fit["rms_one_K"] > 0.3
    lays = layer_stack(fit, 500.0)
    assert lays[0].top == pytest.approx(zi - 500.0, abs=25.0) and lays[1].jump == pytest.approx(jump, abs=0.05)
    assert abs(brunt_vaisala(z, th, 2000.0, 4000.0) - n2) < 3e-4

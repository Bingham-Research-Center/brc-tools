"""Linear steady Boussinesq mountain waves.

Two solvers, both spectral:

``linear_3d``   uniform wind (U, V) and buoyancy frequency N over a terrain field h(x, y)
                (Smith 1980).  Hydrostatic or not.  Vertical displacement, w, u', v', p'
                at any height, and the overturning number -d(eta)/dz.
``layered_2d``  a transect h(x) under uniform U with N piecewise constant in height and
                potential-temperature jumps (inversions) between the layers.  Trapped lee
                waves, and the surface flow reversal under their crests (the linear proxy
                for a rotor), come out of this one: one N everywhere cannot trap.

Closure (both): small amplitude, inviscid, steady, Boussinesq, no rotation (the Rossby
number U / (f a) is ~20 for a 5 km ridge at 10 m s-1), uniform wind, so the Scorer
parameter is l = N / U.  The intrinsic frequency carries a small imaginary part,
sigma - i eps: it selects the radiating branch (energy upward, Im m >= 0) and acts as a
Rayleigh friction of time scale 1 / eps, which is what gives a trapped lee-wave train a
finite length.

Fourier relations (k, l horizontal wavenumbers, K^2 = k^2 + l^2, sigma = U k + V l,
eta-hat at the ground = h-hat):

    m^2 = K^2 (N^2 / sigma^2 - 1)          hydrostatic: K^2 N^2 / sigma^2
    eta = h-hat exp(i m z)                 w = i sigma eta
    p'  = i rho0 sigma^2 m eta / K^2       hydrostatic 2-D: rho0 U N x Hilbert(h)
    u'  = -k p' / (rho0 sigma),  v' = -l p' / (rho0 sigma)

Linear theory holds while N h / U is well below 1.  Isentropes overturn where
-d(eta)/dz reaches 1 (``overturning``): for the hydrostatic Witch of Agnesi this happens
first at N h / U = 1 in linear theory and at 0.85 in Long's exact solution (Miles &
Huppert 1969).  Report N h / U with any result.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import G, RHO0, THETA0


def _branch(m2: np.ndarray) -> np.ndarray:
    """sqrt(m2) on the branch with Im m >= 0 (radiation or decay upward)."""
    m = np.sqrt(np.asarray(m2, dtype=np.complex128))
    return np.where(m.imag < 0, -m, m)


@dataclass
class LinearWave:
    """The spectral solution of ``linear_3d``; evaluate fields with the methods below."""

    k: np.ndarray
    l: np.ndarray
    sigma: np.ndarray       # complex intrinsic frequency U k + V l - i eps
    m: np.ndarray           # complex vertical wavenumber
    h_hat: np.ndarray
    shape: tuple[int, int]  # the unpadded field shape
    rho0: float = RHO0

    def _back(self, f_hat: np.ndarray) -> np.ndarray:
        return np.fft.ifft2(f_hat).real[: self.shape[0], : self.shape[1]]

    def _eta_hat(self, z: float) -> np.ndarray:
        return self.h_hat * np.exp(1j * self.m * z)

    def _k2(self) -> np.ndarray:
        k2 = self.k ** 2 + self.l ** 2
        return np.where(k2 > 0, k2, np.inf)

    def eta(self, z: float = 0.0) -> np.ndarray:
        """Vertical displacement (m) of the streamline that is level far upstream."""
        return self._back(self._eta_hat(z))

    def w(self, z: float = 0.0) -> np.ndarray:
        return self._back(1j * self.sigma.real * self._eta_hat(z))

    def p(self, z: float = 0.0) -> np.ndarray:
        """Pressure perturbation (Pa)."""
        return self._back(1j * self.rho0 * self.sigma ** 2 * self.m * self._eta_hat(z) / self._k2())

    def uv(self, z: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
        """Horizontal wind perturbation (u', v') in m s-1."""
        q = -1j * self.m * self.sigma * self._eta_hat(z) / self._k2()
        return self._back(self.k * q), self._back(self.l * q)

    def overturning(self, z: float) -> np.ndarray:
        """-d(eta)/dz: reaches 1 where the isentropes stand vertical."""
        return -self._back(1j * self.m * self._eta_hat(z))


def linear_3d(h: np.ndarray, dx: float, U: float, V: float, N: float, *, dy: float | None = None,
              hydrostatic: bool = False, pad: int = 2, eps: float = 1e-5, rho0: float = RHO0) -> LinearWave:
    """Linear waves over ``h`` (m above a flat base).  ``h`` is ``(ny, nx)`` with x to the
    east and **rows running south to north** (flip a north-up DEM with ``h[::-1]`` and flip
    the fields back).  ``U`` eastward, ``V`` northward.  ``pad`` multiplies each dimension
    with zeros so that the periodic transform does not wrap the lee waves round to the
    windward side; taper ``h`` to zero at its edges first.  A 1-D ``h`` is a 2-D ridge,
    infinite across the wind (``V`` ignored)."""
    h = np.asarray(h, dtype=float)
    if h.ndim == 1:
        h = h[None, :]
    ny, nx = h.shape
    dy = dx if dy is None else dy
    py, px = (ny * pad if ny > 1 else 1), nx * pad
    hp = np.zeros((py, px))
    hp[:ny, :nx] = h
    k1 = 2.0 * np.pi * np.fft.fftfreq(px, d=dx)
    l1 = 2.0 * np.pi * np.fft.fftfreq(py, d=dy) if py > 1 else np.zeros(1)
    k, l = np.meshgrid(k1, l1)
    sigma = U * k + V * l - 1j * eps
    k2 = k ** 2 + l ** 2
    if hydrostatic:
        m2 = k2 * N ** 2 / sigma ** 2
    else:
        m2 = k2 * (N ** 2 / sigma ** 2 - 1.0)
    m = _branch(m2)
    h_hat = np.fft.fft2(hp)
    h_hat[k2 == 0] = 0.0
    return LinearWave(k=k, l=l, sigma=sigma, m=m, h_hat=h_hat, shape=(ny, nx), rho0=rho0)


# --------------------------------------------------------------------------- #
# layered 2-D: trapped lee waves over a transect
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Layer:
    """A layer of buoyancy frequency ``N`` (s-1) up to ``top`` (m above the base;
    ``np.inf`` for the last one).  ``jump`` is the potential-temperature jump (K) at the
    layer's BOTTOM, i.e. an inversion between it and the layer below (0 for the first)."""

    top: float
    N: float
    jump: float = 0.0


@dataclass
class LayeredWave:
    x: np.ndarray            # m along the transect (the unpadded part)
    z: np.ndarray            # m, output heights above the base
    w: np.ndarray            # (nz, nx) m s-1
    eta: np.ndarray          # (nz, nx) m, streamline displacement
    u: np.ndarray            # (nz, nx) m s-1, u'; the total wind is U + u'
    U: float

    def surface_wind(self) -> np.ndarray:
        """U + u' at the ground: negative where linear theory reverses the surface flow."""
        return self.U + self.u[0]


def layered_2d(h: np.ndarray, dx: float, U: float, layers: list[Layer], z: np.ndarray, *,
               theta0: float = THETA0, g: float = G, pad: int = 4, eps: float | None = None,
               max_step: float = 20.0) -> LayeredWave:
    """Linear non-hydrostatic waves over a transect ``h(x)`` (m) for uniform ``U`` and a
    stack of ``layers``.

    Per wavenumber the structure equation w'' + (l^2 - k^2) w = 0 is integrated as the
    log-derivative R = w'/w from the top layer (radiating) downward, exactly within each
    layer of constant l, and across each inversion with U^2 (w'_below - w'_above) = g' w,
    g' = g jump / theta0.  The amplitude is then carried upward from w(0) = i U k h-hat in
    steps of at most ``max_step`` metres.

    ``eps`` (s-1) defaults to 2 U / L, L the padded length: a trapped train then decays
    over ~L/2.  Make ``pad`` large enough that L/2 exceeds the reach of interest.
    """
    h = np.asarray(h, dtype=float)
    zs = np.asarray(z, dtype=float)
    if zs.ndim != 1 or zs[0] != 0.0 or np.any(np.diff(zs) <= 0):
        raise ValueError("z must start at 0 and increase")
    tops = np.array([lay.top for lay in layers], dtype=float)
    if not np.isinf(tops[-1]) or np.any(np.diff(tops[:-1]) <= 0) or (len(tops) > 1 and tops[0] <= 0):
        raise ValueError("layer tops must be positive, increasing, and the last inf")
    interfaces = tops[:-1]
    nx = h.size
    px = nx * pad
    hp = np.zeros(px)
    hp[:nx] = h
    k = 2.0 * np.pi * np.fft.fftfreq(px, d=dx)
    eps = 2.0 * U / (px * dx) if eps is None else eps
    sig = U * k - 1j * eps
    kk = k ** 2

    def m_of(j: int) -> np.ndarray:
        m = _branch(layers[j].N ** 2 * kk / sig ** 2 - kk)
        return np.where(np.abs(m) < 1e-12, 1e-12 + 0j, m)

    ms = [m_of(j) for j in range(len(layers))]
    zmax = max(float(zs[-1]), float(interfaces[-1]) if interfaces.size else 0.0)
    levels = np.unique(np.concatenate([zs, interfaces, np.arange(0.0, zmax, max_step), [zmax]]))
    nlev = levels.size
    seg_layer = np.searchsorted(interfaces, 0.5 * (levels[:-1] + levels[1:]), side="right")
    jump_at = {float(t): g * layers[j + 1].jump / theta0 for j, t in enumerate(interfaces) if layers[j + 1].jump}

    R_above = np.empty((nlev, px), dtype=np.complex128)
    R = 1j * ms[-1]
    for idx in range(nlev - 1, -1, -1):
        if idx < nlev - 1:
            m = ms[seg_layer[idx]]
            with np.errstate(all="ignore"):
                t = np.tan(m * (levels[idx + 1] - levels[idx]))
                R = (m * t + R) / (1.0 - (R / m) * t)
        R_above[idx] = R
        gp = jump_at.get(float(levels[idx]))
        if gp:
            R = R + gp * kk / sig ** 2

    W = np.empty((nlev, px), dtype=np.complex128)
    W[0] = 1j * (U * k) * np.fft.fft(hp)
    W[0][k == 0] = 0.0
    for idx in range(1, nlev):
        m = ms[seg_layer[idx - 1]]
        d = levels[idx] - levels[idx - 1]
        with np.errstate(all="ignore"):
            W[idx] = np.nan_to_num(W[idx - 1] * (np.cos(m * d) + R_above[idx - 1] / m * np.sin(m * d)))
    pick = np.searchsorted(levels, zs)
    Wz, Rz = W[pick], R_above[pick]
    ks = np.where(k == 0, 1.0, k)
    eta_hat = np.where(k == 0, 0.0, Wz / (1j * U * ks))
    u_hat = np.where(k == 0, 0.0, 1j * Rz * Wz / ks)   # continuity: i k u = -w'
    back = lambda a: np.fft.ifft(a, axis=1).real[:, :nx]   # noqa: E731
    return LayeredWave(x=np.arange(nx) * dx, z=zs, w=back(Wz), eta=back(eta_hat), u=back(u_hat), U=U)


def ridge_numbers(U: float, N: float, h: float, a: float) -> dict[str, float]:
    """The dimensionless set for a ridge of height ``h`` and half-width ``a``:
    ``Nh_U`` (linear below ~0.5, overturning near 0.85-1), ``Na_U`` (>> 1 hydrostatic;
    near 1 non-hydrostatic, able to shed trapped waves), and the hydrostatic vertical
    wavelength ``lambda_z_m`` = 2 pi U / N."""
    return {"Nh_U": N * h / U, "Na_U": N * a / U, "lambda_z_m": 2.0 * np.pi * U / N}

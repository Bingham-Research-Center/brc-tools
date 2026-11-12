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

    FIELDS = ("eta", "u", "v", "w", "p")

    def _back(self, f_hat: np.ndarray) -> np.ndarray:
        return np.fft.ifft2(f_hat).real[: self.shape[0], : self.shape[1]]

    def _eta_hat(self, z: float) -> np.ndarray:
        if np.ndim(z) != 0:
            # an array would broadcast against the 2-D spectrum and _back would then crop
            # the wrong axes without complaint
            raise TypeError("z must be a scalar height; use planes() for a stack of levels")
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

    def planes(self, zs, fields=("eta", "u", "v", "w"), *, window=None,
               dtype=np.float32) -> dict[str, np.ndarray]:
        """Fields on constant-height planes ``zs`` (m above the flat base), each returned as
        ``(len(zs), ny_w, nx_w)`` in the solver's row order (south to north).

        ``fields`` are names from ``FIELDS``: ``eta`` (m), ``u``/``v`` (u', v', m s-1), ``w``
        (m s-1) and ``p`` (Pa).  ``window`` is a ``(row_slice, col_slice)`` pair, in that
        same row order, cut after each inverse transform; the default keeps the whole
        field.  One ``exp(i m z)`` per level serves every field, which is what makes a
        volume affordable: the cost is one inverse transform per field per level."""
        unknown = set(fields) - set(self.FIELDS)
        if unknown:
            raise ValueError(f"unknown fields {sorted(unknown)}; choose from {self.FIELDS}")
        zs = np.atleast_1d(np.asarray(zs, dtype=float))
        if zs.ndim != 1:
            raise ValueError("zs must be a 1-D sequence of heights")
        rows, cols = window if window is not None else (slice(None), slice(None))
        k2 = self._k2()
        out: dict[str, np.ndarray] = {}
        for iz, z in enumerate(zs):
            eh = self.h_hat * np.exp(1j * self.m * z)
            q = -1j * self.m * self.sigma * eh / k2 if {"u", "v"} & set(fields) else None
            for name in fields:
                if name == "eta":
                    f_hat = eh
                elif name == "w":
                    f_hat = 1j * self.sigma.real * eh
                elif name == "p":
                    f_hat = 1j * self.rho0 * self.sigma ** 2 * self.m * eh / k2
                else:
                    f_hat = (self.k if name == "u" else self.l) * q
                plane = self._back(f_hat)[rows, cols]
                if name not in out:
                    out[name] = np.empty((zs.size,) + plane.shape, dtype=dtype)
                out[name][iz] = plane
        return out


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


def layered_3d(h: np.ndarray, dx: float, U: float, V: float, layers: list[Layer], z: np.ndarray, *,
               dy: float | None = None, theta0: float = THETA0, g: float = G, pad: int = 3,
               eps: float | None = None, max_step: float = 50.0, fields=("eta", "u", "v", "w"),
               window=None, dtype=np.float32, r_dtype=np.complex128) -> dict[str, np.ndarray]:
    """``layered_2d`` over a terrain field: linear non-hydrostatic waves over ``h(x, y)``
    (m above the flat base, rows south to north as ``linear_3d``) for a uniform wind
    ``(U, V)`` and a stack of ``layers`` with inversions between them.

    Per horizontal wavenumber (k, l), K^2 = k^2 + l^2 and sigma = U k + V l - i eps, the
    vertical structure is the 2-D one with k^2 -> K^2 and U k -> sigma: in a layer of
    buoyancy frequency N, m^2 = K^2 (N^2 / sigma^2 - 1); across an inversion of reduced
    gravity g', the log-derivative R = w'/w jumps by g' K^2 / sigma^2; w(0) = i sigma h-hat.
    The horizontal perturbation is irrotational: u-hat = k q, v-hat = l q, q = -sigma R eta-hat / K^2.
    Returns ``fields`` (``eta`` m, ``u``/``v``/``w`` m s-1) on the constant heights ``z``
    (m above the base), each ``(len(z), ny_w, nx_w)`` after the optional ``window``
    ``(row_slice, col_slice)``.  ``eps`` defaults to 2 |(U, V)| / L along the shorter padded
    side, as the 2-D solver; the downward sweep keeps one ``(py, px)`` array of ``r_dtype``
    per ``max_step`` of height, which is the memory cost (complex64 halves it and lowers the
    evanescent cap below from 12 to 6)."""
    h = np.asarray(h, dtype=float)
    if h.ndim != 2:
        raise ValueError("h must be (ny, nx); layered_2d takes a transect")
    zs = np.asarray(z, dtype=float)
    if zs.ndim != 1 or zs[0] != 0.0 or np.any(np.diff(zs) <= 0):
        raise ValueError("z must start at 0 and increase")
    tops = np.array([lay.top for lay in layers], dtype=float)
    if not np.isinf(tops[-1]) or np.any(np.diff(tops[:-1]) <= 0) or (len(tops) > 1 and tops[0] <= 0):
        raise ValueError("layer tops must be positive, increasing, and the last inf")
    unknown = set(fields) - {"eta", "u", "v", "w"}
    if unknown:
        raise ValueError(f"unknown fields {sorted(unknown)}")
    interfaces = tops[:-1]
    ny, nx = h.shape
    dy = dx if dy is None else dy
    py, px = ny * pad, nx * pad
    hp = np.zeros((py, px))
    hp[:ny, :nx] = h
    k1 = 2.0 * np.pi * np.fft.fftfreq(px, d=dx)
    l1 = 2.0 * np.pi * np.fft.fftfreq(py, d=dy)
    k, l = np.meshgrid(k1, l1)
    K2 = k ** 2 + l ** 2
    speed = float(np.hypot(U, V))
    eps = 2.0 * speed / min(px * dx, py * dy) if eps is None else eps
    sig = U * k + V * l - 1j * eps
    safe_K2 = np.where(K2 > 0, K2, np.inf)

    def m_of(j: int) -> np.ndarray:
        m = _branch(layers[j].N ** 2 * K2 / sig ** 2 - K2)
        return np.where(np.abs(m) < 1e-12, 1e-12 + 0j, m)

    ms = [m_of(j) for j in range(len(layers))]
    zmax = max(float(zs[-1]), float(interfaces[-1]) if interfaces.size else 0.0)
    levels = np.unique(np.concatenate([zs, interfaces, np.arange(0.0, zmax, max_step), [zmax]]))
    nlev = levels.size
    seg_layer = np.searchsorted(interfaces, 0.5 * (levels[:-1] + levels[1:]), side="right")
    jump_at = {float(t): g * layers[j + 1].jump / theta0 for j, t in enumerate(interfaces) if layers[j + 1].jump}

    R_above = [None] * nlev
    R = 1j * ms[-1]
    for idx in range(nlev - 1, -1, -1):
        if idx < nlev - 1:
            m = ms[seg_layer[idx]]
            with np.errstate(all="ignore"):
                t = np.tan(m * (levels[idx + 1] - levels[idx]))
                R = (m * t + R) / (1.0 - (R / m) * t)
        R = np.where(np.isfinite(R), R, 1j * ms[seg_layer[min(idx, nlev - 2)]])   # tan overflowed: the decaying branch
        R_above[idx] = R.astype(r_dtype)
        gp = jump_at.get(float(levels[idx]))
        if gp:
            R = R + gp * K2 / sig ** 2

    cap = 12.0 if np.dtype(r_dtype) == np.dtype(np.complex128) else 6.0
    rows, cols = window if window is not None else (slice(None), slice(None))
    want = set(np.searchsorted(levels, zs).tolist())
    out: dict[str, np.ndarray] = {}

    def back(a: np.ndarray) -> np.ndarray:
        return np.fft.ifft2(a).real[:ny, :nx][rows, cols]

    def emit(iz: int, E: np.ndarray, Rz: np.ndarray) -> None:
        """Fields from eta-hat ``E`` at a level where the log-derivative is ``Rz``: w = i sigma eta,
        and the irrotational horizontal part u-hat = k q, v-hat = l q with q = -sigma R eta / K^2
        (R = i m in a single layer gives linear_3d's q = -i m sigma eta / K^2)."""
        q = -sig * Rz * E / safe_K2 if {"u", "v"} & set(fields) else None
        for name in fields:
            if name == "eta":
                f_hat = E
            elif name == "w":
                f_hat = 1j * sig.real * E
            else:
                f_hat = (k if name == "u" else l) * q
            plane = back(f_hat)
            if name not in out:
                out[name] = np.empty((zs.size,) + plane.shape, dtype=dtype)
            out[name][iz] = plane

    E = np.fft.fft2(hp)
    E[K2 == 0] = 0.0
    iz = 0
    if 0 in want:
        emit(iz, E, R_above[0])
        iz += 1
    for idx in range(1, nlev):
        m = ms[seg_layer[idx - 1]]
        d = levels[idx] - levels[idx - 1]
        # cos(m d) + (R / m) sin(m d) in its exponential form.  Shooting upward, the growing
        # branch exp(-i m d) carries the reflected wave, whose coefficient (1 - R / i m) is
        # exact only to roundoff: once Im(m) d exceeds ~12 (6 in single precision) that roundoff times the growth
        # outruns the field (a wavenumber across the wind, which the ground hardly forces,
        # or a short evanescent wave), so there only the decaying branch is kept.
        with np.errstate(all="ignore"):
            Rm = R_above[idx - 1] / (1j * m)
            up, down = np.exp(1j * m * d), np.exp(-1j * m * d)
            full = 0.5 * ((1.0 + Rm) * up + (1.0 - Rm) * down)
            decay = 0.5 * (1.0 + Rm) * up
            factor = np.where(m.imag * d > cap, decay, full)
            factor = np.where(np.isfinite(factor), factor, 0.0)
            E = E * factor
        if idx in want:
            emit(iz, E, R_above[idx])
            iz += 1
    return out


def ridge_numbers(U: float, N: float, h: float, a: float) -> dict[str, float]:
    """The dimensionless set for a ridge of height ``h`` and half-width ``a``:
    ``Nh_U`` (linear below ~0.5, overturning near 0.85-1), ``Na_U`` (>> 1 hydrostatic;
    near 1 non-hydrostatic, able to shed trapped waves), and the hydrostatic vertical
    wavelength ``lambda_z_m`` = 2 pi U / N."""
    return {"Nh_U": N * h / U, "Na_U": N * a / U, "lambda_z_m": 2.0 * np.pi * U / N}

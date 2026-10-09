"""Free and forced oscillations (seiches) of a cold pool.

A pool of depth H(x, y) under an inversion of reduced gravity g' is a shallow lake to
long internal waves of speed c = sqrt(g' H).  Its free modes solve

    omega^2 eta = -g' div( H grad eta )          (no flux through the shoreline)

the linear reduced-gravity shallow-water equations without rotation: the Rossby radius
c / f is ~80 km for c = 7 m s-1 at 40 N, several times any valley here (``rossby_radius``).
``basin_operator`` discretises this on a raster (five-point, face depth the mean of the two
wet neighbours, a face closed if either side is dry) and ``basin_modes`` returns the
slowest modes.  ``merian_period`` is the closed-form check for a rectangle of uniform
depth: T = 2 L / (n c) between two walls, 4 L / ((2n - 1) c) with one end open.

Forced: a pressure p' imposed on the interface from above (a wind aloft) adds -grad p' /
rho0 to the momentum equation, so with eta_f = -p' / (rho0 g') (``pool.interface_displacement``)

    du/dt = -g' grad(eta - eta_f),    d(eta)/dt = -div(H u)    =>    eta_tt = -L (eta - eta_f)

with L = -g' div(H grad) the same operator.  Each mode is a forced oscillator,

    a_n'' + 2 gamma a_n' + omega_n^2 a_n = omega_n^2 f_n(t),     f_n = <eta_f, phi_n> / <phi_n, phi_n>

(``project``, ``forced_response``): a slow change of the forcing is followed, a quick one
leaves the mode ringing.  ``lid_displacement`` adds back the part of eta_f the retained
modes cannot carry, quasi-statically (the mode-acceleration form), and ``pool_current``
returns the depth-uniform current that carries a given d(eta)/dt.  Its steady limit is the
stagnant pool of ``pool.interface_displacement``.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import G


def wave_speed(gprime: float, H) -> np.ndarray:
    return np.sqrt(gprime * np.asarray(H, dtype=float))


def merian_period(L: float, H: float, gprime: float, mode: int = 1, ends: str = "closed") -> float:
    c = float(np.sqrt(gprime * H))
    if ends == "closed":
        return 2.0 * L / (mode * c)
    if ends == "open":
        return 4.0 * L / ((2 * mode - 1) * c)
    raise ValueError("ends must be 'closed' or 'open'")


def rossby_radius(gprime: float, H: float, lat_deg: float = 40.4) -> float:
    f = 2.0 * 7.2921e-5 * np.sin(np.radians(lat_deg))
    return float(np.sqrt(gprime * H) / f)


@dataclass(frozen=True)
class BasinOperator:
    """The discrete operator L = -g' div(H grad) on one connected pool.

    ``wet`` are the unknown cells (in ``index`` order), ``held`` the cells held at
    eta = 0 (an open end), ``region`` both.  ``hx`` (ny, nx+1) and ``hy`` (ny+1, nx) are
    the depths of the open faces, 0 where a face is closed: x-face ``[j, i]`` lies between
    columns i-1 and i, y-face ``[j, i]`` between rows j-1 and j."""

    A: object
    wet: np.ndarray
    held: np.ndarray
    region: np.ndarray
    index: np.ndarray
    hx: np.ndarray
    hy: np.ndarray
    dx: float
    gprime: float

    @property
    def closed(self) -> bool:
        """No held cell: the operator has a constant null (volume) mode."""
        return not bool(self.held.any())

    @property
    def n(self) -> int:
        return int(self.wet.sum())


def basin_operator(depth: np.ndarray, dx: float, gprime: float, *, seed=None, open_mask=None) -> BasinOperator:
    """Assemble ``L`` on the connected wet region of ``depth`` (m, NaN or <= 0 dry) that
    contains ``seed`` (row, col) -- the largest one if ``seed`` is None.  ``open_mask``
    marks wet cells held at eta = 0: an open end where the pool spills into a much larger
    one (the node at Merian's open end)."""
    from scipy import ndimage, sparse

    H = np.where(np.isfinite(depth) & (depth > 0), depth, 0.0).astype(float)
    lab, nlab = ndimage.label(H > 0)
    if nlab == 0:
        raise ValueError("no wet cells")
    if seed is None:
        keep = np.argmax(np.bincount(lab.ravel())[1:]) + 1
    else:
        keep = lab[seed]
        if keep == 0:
            raise ValueError("seed is dry")
    region = lab == keep
    held = np.zeros_like(region) if open_mask is None else (np.asarray(open_mask, dtype=bool) & region)
    wet = region & ~held
    idx = -np.ones(H.shape, dtype=np.int64)
    idx[wet] = np.arange(wet.sum())
    n = int(wet.sum())
    ny, nx = H.shape
    hx = np.zeros((ny, nx + 1))
    hy = np.zeros((ny + 1, nx))
    rows, cols, vals = [], [], []
    diag = np.zeros(n)
    c0 = gprime / dx ** 2
    for dj, di in ((0, 1), (1, 0)):
        a = wet[: H.shape[0] - dj, : H.shape[1] - di]
        b = wet[dj:, di:]
        both = a & b
        ia = idx[: H.shape[0] - dj, : H.shape[1] - di][both]
        ib = idx[dj:, di:][both]
        hf = 0.5 * (H[: H.shape[0] - dj, : H.shape[1] - di][both] + H[dj:, di:][both])
        wgt = c0 * hf
        rows += [ia, ib]
        cols += [ib, ia]
        vals += [-wgt, -wgt]
        np.add.at(diag, ia, wgt)
        np.add.at(diag, ib, wgt)
        # an unknown facing a held (eta = 0) cell drains through that face: diagonal only
        lo = (slice(0, H.shape[0] - dj), slice(0, H.shape[1] - di))
        hi = (slice(dj, None), slice(di, None))
        for side, other in ((lo, hi), (hi, lo)):
            face = wet[side] & held[other]
            np.add.at(diag, idx[side][face], c0 * 0.5 * (H[side][face] + H[other][face]))
        # face depths for the currents: open between two unknowns or an unknown and a held cell
        open_face = (wet[lo] & region[hi]) | (region[lo] & wet[hi])
        depth_face = np.where(open_face, 0.5 * (H[lo] + H[hi]), 0.0)
        if di:
            hx[:, 1:nx] = depth_face
        else:
            hy[1:ny, :] = depth_face
    A = sparse.coo_matrix((np.concatenate(vals + [diag]),
                           (np.concatenate(rows + [np.arange(n)]), np.concatenate(cols + [np.arange(n)]))),
                          shape=(n, n)).tocsc()
    return BasinOperator(A=A, wet=wet, held=held, region=region, index=idx, hx=hx, hy=hy,
                         dx=float(dx), gprime=float(gprime))


def basin_modes(depth: np.ndarray, dx: float, gprime: float, n_modes: int = 6, *, seed=None, open_mask=None):
    """The ``n_modes`` slowest seiche modes of the pool ``depth`` (m, NaN or <= 0 dry).

    The pool is assembled by ``basin_operator`` (same ``seed`` and ``open_mask``).  Returns
    ``(periods_s, shapes)`` with ``shapes`` an ``(n_modes, ny, nx)`` array of interface
    displacement normalised to max |eta| = 1 and NaN outside the unknown cells.
    """
    from scipy.sparse.linalg import eigsh

    op = basin_operator(depth, dx, gprime, seed=seed, open_mask=open_mask)
    n = op.n
    diag = op.A.diagonal()
    k = min(n_modes + 1, n - 2)
    shift = -1e-3 * float(diag.max()) / max(n, 1)
    w2, vec = eigsh(op.A, k=k, sigma=shift, which="LM")
    order = np.argsort(w2)
    w2, vec = w2[order], vec[:, order]
    keep_modes = w2 > 1e-10 * float(diag.max())        # drop the constant (volume) mode, if closed
    w2, vec = w2[keep_modes][:n_modes], vec[:, keep_modes][:, :n_modes]
    periods = 2.0 * np.pi / np.sqrt(w2)
    shapes = np.full((w2.size,) + op.wet.shape, np.nan)
    for i in range(w2.size):
        v = vec[:, i] / np.max(np.abs(vec[:, i]))
        shapes[i][op.wet] = v
    return periods, shapes


def project(field: np.ndarray, shapes: np.ndarray) -> np.ndarray:
    """Coefficients f_n = <field, phi_n> / <phi_n, phi_n> over the cells where both are
    finite.  The modes of ``basin_operator`` are orthogonal in this plain (equal-area)
    inner product, so these are the modal amplitudes of ``field``."""
    field = np.asarray(field, dtype=float)
    out = np.empty(shapes.shape[0])
    for n, phi in enumerate(shapes):
        ok = np.isfinite(phi) & np.isfinite(field)
        out[n] = float(np.sum(field[ok] * phi[ok]) / np.sum(phi[ok] ** 2))
    return out


def forced_response(omega: np.ndarray, t: np.ndarray, f: np.ndarray, *, damping: float = 0.0,
                    a0: np.ndarray | None = None, adot0: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Integrate a'' + 2 gamma a' + omega^2 a = omega^2 f(t) for each mode exactly, with
    ``f`` linear between the knots ``t``.

    ``omega`` (M,) rad s-1; ``t`` (nt,) s, increasing; ``f`` (nt, M) the forcing at the
    knots; ``damping`` gamma (s-1), half the Rayleigh friction on the current, below every
    omega.  Starts from ``a0`` (default ``f[0]``, at rest in the initial forcing) and
    ``adot0`` (default 0).  Returns ``(a, adot)``, each (nt, M).  The update is the closed
    form over each interval, so there is no step-size limit: a forcing that changes within
    one interval excites the mode as a step would."""
    omega = np.asarray(omega, dtype=float)
    t = np.asarray(t, dtype=float)
    f = np.asarray(f, dtype=float).reshape(t.size, omega.size)
    gamma = float(damping)
    if np.any(np.diff(t) <= 0):
        raise ValueError("t must increase")
    if gamma < 0 or np.any(gamma >= omega):
        raise ValueError("damping must be non-negative and below every omega")
    wd = np.sqrt(omega ** 2 - gamma ** 2)
    a = np.empty_like(f)
    ad = np.empty_like(f)
    a[0] = f[0] if a0 is None else a0
    ad[0] = 0.0 if adot0 is None else adot0
    for k in range(t.size - 1):
        dt = t[k + 1] - t[k]
        s = (f[k + 1] - f[k]) / dt
        bias = 2.0 * gamma * s / omega ** 2            # the particular solution lags a ramp by this
        x0 = a[k] - f[k] + bias
        v0 = ad[k] - s
        decay = np.exp(-gamma * dt)
        c, sn = np.cos(wd * dt), np.sin(wd * dt)
        x1 = decay * (x0 * c + (v0 + gamma * x0) / wd * sn)
        v1 = decay * (v0 * c - (omega ** 2 * x0 + gamma * v0) / wd * sn)
        a[k + 1] = x1 + f[k + 1] - bias
        ad[k + 1] = v1 + s
    return a, ad


def lid_displacement(a: np.ndarray, f: np.ndarray, shapes: np.ndarray, eta_f: np.ndarray,
                     op: BasinOperator) -> np.ndarray:
    """The interface on the pool for modal amplitudes ``a`` (M,) under forcing ``eta_f``:

        eta = sum a_n phi_n + (eta_f - <eta_f> - sum f_n phi_n)

    on the unknown cells, where ``f`` are ``project(eta_f, shapes)`` and the bracket is the
    part of the forcing the retained modes cannot carry, followed quasi-statically.  The
    mean ``<eta_f>`` is removed only for a closed pool (a closed pool keeps its volume);
    held cells sit at ``eta_f``.  NaN elsewhere."""
    eta_f = np.asarray(eta_f, dtype=float)
    out = np.full(op.wet.shape, np.nan)
    resid = eta_f[op.wet] - (float(np.mean(eta_f[op.wet])) if op.closed else 0.0)
    for n, phi in enumerate(shapes):
        resid = resid + (a[n] - f[n]) * phi[op.wet]
    out[op.wet] = resid
    out[op.held] = eta_f[op.held]
    return out


def pool_current(op: BasinOperator, eta_rate: np.ndarray, *, centred: bool = True):
    """The depth-uniform current that carries ``eta_rate`` = d(eta)/dt (m s-1) on the
    unknown cells: u = g' grad chi with L chi = eta_rate, held cells at chi = 0, which
    satisfies -div(H u) = d(eta)/dt face by face.  A closed pool needs sum(eta_rate) = 0;
    one cell is pinned.  Returns cell-centred ``(u, v)`` (NaN outside the region), or the
    face values ``(ux (ny, nx+1), vy (ny+1, nx))``, positive toward increasing index, with
    ``centred=False``."""
    from scipy.sparse.linalg import spsolve

    rate = np.asarray(eta_rate, dtype=float)[op.wet]
    if op.closed:
        mean = float(rate.mean())
        if abs(mean) > 1e-6 * max(float(np.abs(rate).max()), 1e-30):
            raise ValueError("a closed pool cannot change volume: eta_rate must sum to zero")
        rate = rate - mean                                # round-off only: the modes are orthogonal to 1
        A = op.A[1:, 1:]
        chi_wet = np.concatenate([[0.0], spsolve(A.tocsc(), rate[1:])])
    else:
        chi_wet = spsolve(op.A, rate)
    chi = np.zeros(op.wet.shape)
    chi[op.wet] = chi_wet
    g, dx = op.gprime, op.dx
    ux = np.zeros_like(op.hx)
    vy = np.zeros_like(op.hy)
    ux[:, 1:-1] = np.where(op.hx[:, 1:-1] > 0, g * (chi[:, 1:] - chi[:, :-1]) / dx, 0.0)
    vy[1:-1, :] = np.where(op.hy[1:-1, :] > 0, g * (chi[1:, :] - chi[:-1, :]) / dx, 0.0)
    if not centred:
        return ux, vy
    u = np.where(op.region, 0.5 * (ux[:, :-1] + ux[:, 1:]), np.nan)
    v = np.where(op.region, 0.5 * (vy[:-1, :] + vy[1:, :]), np.nan)
    return u, v


def cap_froude(u: np.ndarray, v: np.ndarray, depth: np.ndarray, gprime: float, max_froude: float = 1.0):
    """Scale a depth-uniform current down to ``max_froude`` times the long-wave speed
    sqrt(g' depth).  Linear long-wave theory needs |u| << c; next to a shoreline, where the
    depth goes to zero, continuity asks for ever faster currents and the theory has broken
    down, so the current there is shown at the speed the theory can still speak for.
    Returns ``(u, v, capped)``."""
    c = max_froude * np.sqrt(gprime * np.clip(np.asarray(depth, dtype=float), 0.0, None))
    speed = np.hypot(u, v)
    capped = speed > c
    factor = np.where(capped, c / np.where(speed > 0, speed, 1.0), 1.0)
    return u * factor, v * factor, capped


def reduced_gravity(dtheta_k: float, theta0: float = 285.0, g: float = G) -> float:
    return g * dtheta_k / theta0

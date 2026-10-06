"""Offline kinematic trajectories from WRF output, integrated in model-index space.

Where did the air at a canyon mouth come from, and where does it go?  WRF's own
trajectory option (``traj_opt = 1``) answers only forward, online, for parcels chosen
before the run.  This module answers either way after the run, from any stream that
carries ``U, V, W, PH, PHB`` (and ``T`` for potential temperature).

Why index space.  A drainage current hugs the ground, and near the ground WRF's levels
follow the terrain.  A parcel is therefore carried as fractional grid indices
``(i, j, k)`` on the mass grid, and its vertical motion is the motion *relative to the
model levels*::

    di/dt = u m_x / dx                    dj/dt = v m_y / dy
    dk/dt = ( w - u dz/dx|k - v dz/dy|k - dz/dt|k ) / ( dz/dk )

with ``u, v`` grid-relative, ``m_x, m_y`` the map factors along each axis (equal on a
conformal projection, not on a lat-lon grid) and ``z`` the geometric height of the
levels.  Air flowing parallel to the terrain has ``dk/dt = 0`` and stays on its level
however steep the slope; integrating ``w`` in height coordinates would walk the same
parcel into the hillside.  Fields are linear in space (trilinear in index space) and in
time between frames; the step is RK4 (or RK2) with ``dt_s`` of 20 s by default.

What it is not: a dispersion model.  There is no sub-grid mixing, so a trajectory is the
path of the *resolved* flow, and its error grows with the sampling interval of the stream
(``sampling_separation`` measures that).  Parcels are held at or above the lowest mass
level and are dropped (NaN) once they leave the domain.

    ds = back_trajectories(run_dir, 2, release, t0, 6.0, stream="auxhist2", statics=wrfout)

``release`` is an ``(n, 3)`` array of ``(lat, lon, level)`` with ``level`` a mass-level
index (0 = lowest).  :func:`release_points` builds the other form, ``(i, j, k)`` grid
indices, which the drivers take only with ``release_is_index=True``; a release that falls
outside the grid raises either way, so the two cannot be confused silently.  Times are
naive UTC, as in ``wrf_output``; an aware ``t0`` is converted.  The integrator itself
(:func:`integrate`) works on plain arrays, which is what the tests use.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Sequence

import numpy as np

__all__ = [
    "Statics", "Frame", "stream_times", "read_statics", "frame_from_fields", "load_frame",
    "release_points", "integrate", "trajectories", "back_trajectories", "forward_trajectories",
    "sampling_separation",
]


# --------------------------------------------------------------------------- #
# containers
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Statics:
    """Time-invariant 2-D fields on the mass grid (from any wrfout / wrfinput)."""

    lat: np.ndarray            # (ny, nx) degrees
    lon: np.ndarray            # (ny, nx) degrees
    hgt: np.ndarray            # (ny, nx) terrain height, m
    msf: np.ndarray            # (ny, nx) map factor along x at mass points (MAPFAC_MX, else MAPFAC_M)
    dx: float                  # m
    dy: float                  # m
    # (ny, nx) map factor along y (MAPFAC_MY); None = the same as msf.  The two are equal on
    # the conformal projections (Lambert, polar, Mercator) and differ on a lat-lon grid.
    msf_y: np.ndarray | None = None

    @property
    def shape(self) -> tuple[int, int]:
        return self.lat.shape


@dataclass
class Frame:
    """One output time, already converted to index-space velocities on the mass grid."""

    time: datetime
    idot: np.ndarray           # (nz, ny, nx) grid cells per second, along i
    jdot: np.ndarray           # (nz, ny, nx) grid cells per second, along j
    kdot: np.ndarray           # (nz, ny, nx) model levels per second (dz/dt|k NOT yet removed)
    z: np.ndarray              # (nz, ny, nx) height of the mass levels, m MSL
    dzdk: np.ndarray           # (nz, ny, nx) layer thickness, m per level
    theta: np.ndarray | None = None   # (nz, ny, nx) K


# --------------------------------------------------------------------------- #
# reading
# --------------------------------------------------------------------------- #
def _stream_files(run_dir: str | Path, domain: int, stream: str) -> list[tuple[datetime, Path]]:
    """``(filename stamp, path)`` for every file of a stream, either filename convention."""
    from brc_tools.nwp.wrf_section import _parse_stamp

    prefix = f"{stream}_d{domain:02d}_"
    out = []
    for p in sorted(Path(run_dir).glob(f"{prefix}*")):
        t = _parse_stamp(p.name[len(prefix):])
        if t is not None:
            out.append((t, p))
    return sorted(out)


def _frame_times(ds, path: Path, stamp: datetime) -> list[datetime]:
    """Valid time of each frame in one open file: the filename stamp for a single frame, the
    ``Times`` variable when the file holds several."""
    n = int(ds.sizes.get("Time", 1))
    if n <= 1:
        return [stamp]
    from brc_tools.nwp.wrf_convective import _times_in

    try:
        times = _times_in(ds)
    except KeyError:
        times = []
    if len(times) != n:
        raise ValueError(f"{path.name} holds {n} frames but its Times variable gives {len(times)} readable "
                         "valid times, so its frames cannot be placed in time")
    return times


def stream_times(run_dir: str | Path, domain: int, stream: str = "wrfout") -> list[tuple[datetime, Path]]:
    """``(valid time, path)`` for every frame of a stream, either filename convention.

    ``stream`` is the file prefix before ``_d0N_``: ``wrfout``, ``auxhist2``, ...  An
    auxiliary stream usually packs several frames per file (``frames_per_auxhist2``), so the
    filenames alone under-report its times: a file that holds several frames is opened and
    listed once per frame, at that frame's time from ``Times``, and :func:`load_frame`
    picks the frame by its time.  A one-frame file keeps the time in its name.  A time that
    two files both hold (a restart writes a new file starting at a time the old one already
    has) is listed once, from the first file by name.
    """
    from brc_tools.nwp import wrf_output as wo

    out: list[tuple[datetime, Path]] = []
    for stamp, p in _stream_files(run_dir, domain, stream):
        ds = wo.open_wrfout(p)
        try:
            out.extend((t, p) for t in _frame_times(ds, p, stamp))
        finally:
            ds.close()
    unique: list[tuple[datetime, Path]] = []
    for t, p in sorted(out):
        if not unique or unique[-1][0] != t:
            unique.append((t, p))
    return unique


def read_statics(path: str | Path) -> Statics:
    """Latitude, longitude, terrain, map factors and grid spacing from a file that carries them.

    The map factor along x is ``MAPFAC_MX`` and along y ``MAPFAC_MY``; a file without them
    falls back to ``MAPFAC_M`` for both (identical on conformal projections), and a file
    with none to 1.
    """
    from brc_tools.nwp import wrf_output as wo

    ds = wo.open_wrfout(path)
    try:
        missing = [v for v in ("XLAT", "XLONG", "HGT") if v not in ds]
        if missing:
            raise KeyError(f"{Path(path).name} has no {missing}: pass a wrfout or wrfinput as statics")
        lat = wo.surface_field(ds, "XLAT").astype(np.float64)
        lon = wo.surface_field(ds, "XLONG").astype(np.float64)
        hgt = wo.surface_field(ds, "HGT").astype(np.float64)
        mx = next((v for v in ("MAPFAC_MX", "MAPFAC_M") if v in ds), None)
        msf = wo.surface_field(ds, mx).astype(np.float64) if mx else np.ones_like(lat)
        msf_y = wo.surface_field(ds, "MAPFAC_MY").astype(np.float64) if "MAPFAC_MY" in ds else None
        dx, dy = wo.dx_dy(ds)
    finally:
        ds.close()
    return Statics(lat=lat, lon=lon, hgt=hgt, msf=msf, dx=float(dx), dy=float(dy), msf_y=msf_y)


def frame_from_fields(time: datetime, u: np.ndarray, v: np.ndarray, w: np.ndarray, z_w: np.ndarray,
                      statics: Statics, *, theta: np.ndarray | None = None) -> Frame:
    """Index-space velocities from mass-point winds and full-level heights.

    ``u, v, w`` are (nz, ny, nx) on mass points (``u, v`` grid-relative), ``z_w`` is
    (nz + 1, ny, nx) heights of the full levels in metres.  The time derivative of the
    level heights is handled by :func:`integrate`, which sees two frames.
    """
    u = np.asarray(u, dtype=np.float32)
    v = np.asarray(v, dtype=np.float32)
    w = np.asarray(w, dtype=np.float32)
    z_w = np.asarray(z_w, dtype=np.float32)
    nz = u.shape[0]
    if z_w.shape[0] != nz + 1:
        raise ValueError(f"z_w has {z_w.shape[0]} levels for {nz} mass levels")
    z = 0.5 * (z_w[:-1] + z_w[1:])
    dzdk = z_w[1:] - z_w[:-1]
    mx = statics.msf.astype(np.float32)[np.newaxis]
    my = mx if statics.msf_y is None else statics.msf_y.astype(np.float32)[np.newaxis]
    idot = u * mx / np.float32(statics.dx)
    jdot = v * my / np.float32(statics.dy)
    dzdi = np.gradient(z, axis=2)                       # m per cell along the level
    dzdj = np.gradient(z, axis=1)
    kdot = (w - idot * dzdi - jdot * dzdj) / dzdk
    return Frame(time=time, idot=idot, jdot=jdot, kdot=kdot.astype(np.float32), z=z, dzdk=dzdk,
                 theta=None if theta is None else np.asarray(theta, dtype=np.float32))


def load_frame(path: str | Path, time: datetime, statics: Statics, *, kmax: int | None = None,
               with_theta: bool = True) -> Frame:
    """Read the frame valid at ``time`` from a 3-D stream file.  ``kmax`` keeps only the
    lowest mass levels.

    A one-frame file is read as it is; in a file that holds several frames the one whose
    ``Times`` entry is ``time`` is selected (``ValueError`` if none is).
    """
    from brc_tools.nwp import wrf_output as wo

    ds = wo.open_wrfout(path)
    try:
        frame = ds
        if int(ds.sizes.get("Time", 1)) > 1:
            times = _frame_times(ds, Path(path), time)
            if time not in times:
                raise ValueError(f"{Path(path).name} holds {len(times)} frames ({times[0]} .. {times[-1]}) "
                                 f"and none is valid at {time}")
            frame = ds.isel(Time=times.index(time))
        for name in ("U", "V", "W", "PH", "PHB"):
            if name not in frame:
                raise KeyError(f"{Path(path).name} has no {name}; a trajectory stream needs U, V, W, PH, PHB")
        u, v = wo.grid_relative_winds(frame)
        w = wo.vertical_velocity(frame)
        z_w = wo.geopotential_height_w(frame)
        theta = wo.potential_temperature(frame) if (with_theta and "T" in frame) else None
    finally:
        ds.close()
    if kmax is not None:
        u, v, w, z_w = u[:kmax], v[:kmax], w[:kmax], z_w[:kmax + 1]
        theta = None if theta is None else theta[:kmax]
    return frame_from_fields(time, u, v, w, z_w, statics, theta=theta)


# --------------------------------------------------------------------------- #
# release points
# --------------------------------------------------------------------------- #
def _fractional_index(statics: Statics, lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Fractional (i, j) of lat/lon by inverting the bilinear map around the nearest cell."""
    lat = np.atleast_1d(np.asarray(lat, dtype=np.float64))
    lon = np.atleast_1d(np.asarray(lon, dtype=np.float64))
    ny, nx = statics.shape
    coslat = np.cos(np.deg2rad(float(np.mean(statics.lat))))
    fi, fj = np.empty(lat.size), np.empty(lat.size)
    for n, (la, lo) in enumerate(zip(lat, lon)):
        d2 = (statics.lat - la) ** 2 + ((statics.lon - lo) * coslat) ** 2
        j0, i0 = np.unravel_index(int(np.argmin(d2)), d2.shape)
        j0, i0 = int(np.clip(j0, 1, ny - 2)), int(np.clip(i0, 1, nx - 2))
        # local linear map (lat, lon) ~ origin + A (di, dj)
        a = np.array([[statics.lon[j0, i0 + 1] - statics.lon[j0, i0 - 1], statics.lon[j0 + 1, i0] - statics.lon[j0 - 1, i0]],
                      [statics.lat[j0, i0 + 1] - statics.lat[j0, i0 - 1], statics.lat[j0 + 1, i0] - statics.lat[j0 - 1, i0]]]) / 2.0
        di, dj = np.linalg.solve(a, np.array([lo - statics.lon[j0, i0], la - statics.lat[j0, i0]]))
        fi[n], fj[n] = i0 + di, j0 + dj
    return fi, fj


def release_points(statics: Statics, lats: Sequence[float], lons: Sequence[float],
                   levels: Sequence[float] = (0, 1, 2, 3, 4)) -> np.ndarray:
    """``(n_sites * n_levels, 3)`` array of ``(i, j, k)`` release coordinates.

    Every site is released on each mass level in ``levels`` (0 = lowest).  A site outside
    the grid raises, because a parcel released there is a parcel nobody will see again.
    """
    fi, fj = _fractional_index(statics, lats, lons)
    bad = _outside(statics, fi, fj)
    if bad.any():
        raise ValueError(f"release site(s) outside the grid: {np.flatnonzero(bad).tolist()}")
    out = [(i, j, float(k)) for i, j in zip(fi, fj) for k in levels]
    return np.asarray(out, dtype=np.float64)


def _outside(statics: Statics, fi: np.ndarray, fj: np.ndarray) -> np.ndarray:
    """True where a fractional (i, j) lies off the mass grid (NaN is not "outside": it is no parcel)."""
    ny, nx = statics.shape
    return (fi < 0) | (fi > nx - 1) | (fj < 0) | (fj > ny - 1)


# --------------------------------------------------------------------------- #
# the integrator
# --------------------------------------------------------------------------- #
def _sample(field: np.ndarray, pos: np.ndarray) -> np.ndarray:
    """Trilinear interpolation of a (nz, ny, nx) field at (n, 3) positions (i, j, k)."""
    from scipy.ndimage import map_coordinates

    coords = np.vstack([pos[:, 2], pos[:, 1], pos[:, 0]])
    return map_coordinates(field, coords, order=1, mode="nearest", prefilter=False)


def _velocity(f0: Frame, f1: Frame, wt: float, dzdt_over_dzdk: np.ndarray | None, pos: np.ndarray) -> np.ndarray:
    """(n, 3) index velocity at ``pos``, linear in time between two frames (weight ``wt`` on f1)."""
    out = np.empty_like(pos)
    for c, name in enumerate(("idot", "jdot", "kdot")):
        a = _sample(getattr(f0, name), pos)
        b = _sample(getattr(f1, name), pos) if f1 is not f0 else a
        out[:, c] = (1.0 - wt) * a + wt * b
    if dzdt_over_dzdk is not None:
        out[:, 2] -= _sample(dzdt_over_dzdk, pos)
    return out


def integrate(frames: Sequence[Frame] | Callable[[int], Frame], release_ijk: np.ndarray, t_start: datetime,
              hours: float, *, frame_times: Sequence[datetime] | None = None, dt_s: float = 20.0,
              scheme: str = "rk4", level_motion: bool = True) -> dict[str, np.ndarray]:
    """Integrate parcels through a time-ordered sequence of frames.

    ``frames`` is a list of :class:`Frame`, or a callable ``index -> Frame`` together with
    ``frame_times`` so that only two frames are in memory at once.  ``hours`` is signed:
    negative integrates backward from ``t_start``.  Positions are recorded at ``t_start``
    and at every frame time crossed (and at the end).  Returns ``time`` and, on
    (n_times, n_parcels), ``i, j, k``, the height ``z`` (m MSL) and ``theta`` (K, NaN when
    the frames carry none).  A parcel that leaves the grid horizontally is NaN from then on.
    """
    import bisect

    if scheme not in ("rk4", "rk2"):
        raise ValueError("scheme must be 'rk4' or 'rk2'")
    if callable(frames):
        if frame_times is None:
            raise ValueError("a frame loader needs frame_times")
        get, ftimes = frames, list(frame_times)
    else:
        seq = list(frames)
        get, ftimes = seq.__getitem__, [f.time for f in seq]
    n_frames = len(ftimes)
    if n_frames < 2:
        raise ValueError("need at least two frames")
    sign = 1.0 if hours >= 0 else -1.0
    t_end = t_start + timedelta(hours=hours)
    for name, t in (("t_start", t_start), ("the end time", t_end)):
        if not (ftimes[0] <= t <= ftimes[-1]):
            raise ValueError(f"{name} {t} is outside the frames ({ftimes[0]} .. {ftimes[-1]})")
    cache: dict[int, Frame] = {}

    def frame(n: int) -> Frame:
        if n not in cache:
            for old in [m for m in cache if abs(m - n) > 1]:
                del cache[old]
            cache[n] = get(n)
        return cache[n]

    def bracket(t: datetime) -> int:
        """n0 with ftimes[n0] <= t <= ftimes[n0 + 1]; at a frame time, the interval ahead in the direction of travel."""
        if sign > 0:
            return min(bisect.bisect_right(ftimes, t) - 1, n_frames - 2)
        return max(bisect.bisect_left(ftimes, t) - 1, 0)

    pos = np.array(release_ijk, dtype=np.float64, copy=True)
    alive = np.isfinite(pos).all(axis=1)
    nz, ny, nx = frame(bracket(t_start)).idot.shape

    def clip(p: np.ndarray) -> np.ndarray:
        p[:, 2] = np.clip(p[:, 2], 0.0, nz - 1.0)
        return p

    def diagnose(f0: Frame, f1: Frame, wt: float) -> tuple[np.ndarray, np.ndarray]:
        z = np.full(pos.shape[0], np.nan)
        th = np.full(pos.shape[0], np.nan)
        if alive.any():
            p = pos[alive]
            z[alive] = (1.0 - wt) * _sample(f0.z, p) + wt * _sample(f1.z, p)
            if f0.theta is not None and f1.theta is not None:
                th[alive] = (1.0 - wt) * _sample(f0.theta, p) + wt * _sample(f1.theta, p)
        return z, th

    pos[alive] = clip(pos[alive])
    n0 = bracket(t_start)
    f0, f1 = frame(n0), frame(n0 + 1)
    z0, th0 = diagnose(f0, f1, (t_start - f0.time).total_seconds() / (f1.time - f0.time).total_seconds())
    rec_t, rec_p, rec_z, rec_th = [t_start], [pos.copy()], [z0], [th0]

    t = t_start
    while (t < t_end) if sign > 0 else (t > t_end):
        n0 = bracket(t)
        f0, f1 = frame(n0), frame(n0 + 1)
        span = (f1.time - f0.time).total_seconds()
        seg_end = min(f1.time, t_end) if sign > 0 else max(f0.time, t_end)
        seg = abs((seg_end - t).total_seconds())
        nsteps = max(int(np.ceil(seg / dt_s - 1e-9)), 1)
        h = sign * seg / nsteps
        zt = ((f1.z - f0.z) / np.float32(span) / (0.5 * (f0.dzdk + f1.dzdk))) if level_motion else None
        tau = (t - f0.time).total_seconds()

        def vel(pp: np.ndarray, at: float) -> np.ndarray:
            return _velocity(f0, f1, min(max(at / span, 0.0), 1.0), zt, clip(pp.copy()))

        for _ in range(nsteps):
            p = pos[alive]
            if p.size:
                k1 = vel(p, tau)
                if scheme == "rk2":
                    k2 = vel(p + h * k1, tau + h)
                    p = p + 0.5 * h * (k1 + k2)
                else:
                    k2 = vel(p + 0.5 * h * k1, tau + 0.5 * h)
                    k3 = vel(p + 0.5 * h * k2, tau + 0.5 * h)
                    k4 = vel(p + h * k3, tau + h)
                    p = p + h / 6.0 * (k1 + 2.0 * k2 + 2.0 * k3 + k4)
                pos[alive] = clip(p)
                out = alive & ((pos[:, 0] < 0) | (pos[:, 0] > nx - 1) | (pos[:, 1] < 0) | (pos[:, 1] > ny - 1))
                pos[out] = np.nan
                alive &= ~out
            tau += h
        t = seg_end
        z, th = diagnose(f0, f1, min(max((t - f0.time).total_seconds() / span, 0.0), 1.0))
        rec_t.append(t)
        rec_p.append(pos.copy())
        rec_z.append(z)
        rec_th.append(th)
    arr = np.stack(rec_p)
    return {"time": np.array(rec_t, dtype="datetime64[s]"), "i": arr[:, :, 0], "j": arr[:, :, 1], "k": arr[:, :, 2],
            "z": np.stack(rec_z), "theta": np.stack(rec_th)}


# --------------------------------------------------------------------------- #
# file-based drivers
# --------------------------------------------------------------------------- #
def _bilinear2d(a: np.ndarray, fi: np.ndarray, fj: np.ndarray) -> np.ndarray:
    from scipy.ndimage import map_coordinates

    good = np.isfinite(fi) & np.isfinite(fj)
    out = np.full(fi.shape, np.nan)
    if good.any():
        out[good] = map_coordinates(a, np.vstack([fj[good], fi[good]]), order=1, mode="nearest", prefilter=False)
    return out


def trajectories(run_dir: str | Path, domain: int, release: np.ndarray, t0: datetime, hours: float, *,
                 stream: str = "auxhist2", statics: Statics | str | Path | None = None, dt_s: float = 20.0,
                 every: int = 1, kmax: int | None = None, scheme: str = "rk4", release_is_index: bool = False):
    """Trajectories from the frames of one stream of one domain; returns an ``xarray.Dataset``.

    ``release`` is (n, 3): ``(lat, lon, level)``, or ``(i, j, k)`` -- what
    :func:`release_points` returns -- with ``release_is_index``.  A release off the grid
    raises (the usual sign of ``(i, j, k)`` passed without the flag), and so does one above
    the ``kmax`` levels read.  ``t0`` is naive UTC (an aware one is converted).  ``hours`` is
    signed (negative = backward from ``t0``).  ``every`` uses only every n-th frame, counted
    from the frame at ``t0`` -- the sampling experiment.  ``statics`` is a
    :class:`Statics`, or a path to a file with ``XLAT, XLONG, HGT`` (default: the first
    ``wrfout`` of the domain in ``run_dir``).  Output variables on (time, parcel):
    ``lat, lon, z_msl, z_agl, theta, i, j, k``.
    """
    import xarray as xr

    if t0.tzinfo is not None and t0.utcoffset() is not None:
        t0 = t0.astimezone(timezone.utc).replace(tzinfo=None)
    listing = stream_times(run_dir, domain, stream)
    if not listing:
        raise FileNotFoundError(f"no {stream}_d{domain:02d}_* under {run_dir}")
    if statics is None:
        wrfouts = _stream_files(run_dir, domain, "wrfout")     # by name: only the first is opened
        if not wrfouts:
            raise FileNotFoundError("no wrfout to read statics from; pass statics=")
        statics = wrfouts[0][1]
    if not isinstance(statics, Statics):
        statics = read_statics(statics)
    rel = np.asarray(release, dtype=np.float64)
    if not release_is_index:
        fi, fj = _fractional_index(statics, rel[:, 0], rel[:, 1])
        bad = _outside(statics, fi, fj)
        if bad.any():
            raise ValueError(f"release point(s) {np.flatnonzero(bad).tolist()} fall outside the grid. `release` is "
                             "read as (lat, lon, level); if it came from release_points it is already (i, j, k): "
                             "pass release_is_index=True")
        rel = np.column_stack([fi, fj, rel[:, 2]])
    else:
        bad = _outside(statics, rel[:, 0], rel[:, 1])
        if bad.any():
            ny, nx = statics.shape
            raise ValueError(f"release point(s) {np.flatnonzero(bad).tolist()} have (i, j) outside the "
                             f"{nx} x {ny} mass grid")
    if kmax is not None:
        high = np.isfinite(rel[:, 2]) & (rel[:, 2] > kmax - 1)
        if high.any():
            raise ValueError(f"release level(s) {sorted(set(rel[high, 2].tolist()))} are above the kmax={kmax} "
                             f"levels read (top mass-level index {kmax - 1}); a parcel there would be clipped "
                             "down to it silently -- raise kmax")
    t_end = t0 + timedelta(hours=hours)
    lo, hi = min(t0, t_end), max(t0, t_end)
    times = [t for t, _ in listing]
    if t0 not in times:
        raise ValueError(f"t0 {t0} is not a frame time of {stream}")
    n0 = times.index(t0)
    picked = sorted({n for n in range(n0 % every, len(listing), every)})
    picked = [n for n in picked if listing[n][0] >= lo - timedelta(seconds=1) and listing[n][0] <= hi + timedelta(seconds=1)]
    if len(picked) < 2:
        raise ValueError(f"fewer than two frames between {lo} and {hi} at every={every}")
    if listing[picked[0]][0] > lo or listing[picked[-1]][0] < hi:
        raise ValueError(f"frames at every={every} do not span {lo} .. {hi}")

    def get(n: int) -> Frame:
        t, p = listing[picked[n]]
        return load_frame(p, t, statics, kmax=kmax)

    res = integrate(get, rel, t0, hours, frame_times=[listing[n][0] for n in picked], dt_s=dt_s, scheme=scheme)
    nt, npar = res["i"].shape
    z_msl, theta = res["z"], res["theta"]
    lat = np.stack([_bilinear2d(statics.lat, res["i"][n], res["j"][n]) for n in range(nt)])
    lon = np.stack([_bilinear2d(statics.lon, res["i"][n], res["j"][n]) for n in range(nt)])
    hgt = np.stack([_bilinear2d(statics.hgt, res["i"][n], res["j"][n]) for n in range(nt)])
    ds = xr.Dataset(
        {name: (("time", "parcel"), arr) for name, arr in
         (("lat", lat), ("lon", lon), ("z_msl", z_msl), ("z_agl", z_msl - hgt), ("theta", theta),
          ("i", res["i"]), ("j", res["j"]), ("k", res["k"]))},
        coords={"time": res["time"].astype("datetime64[ns]"), "parcel": np.arange(npar)},
        attrs={"stream": stream, "domain": domain, "t0": t0.isoformat(), "hours": float(hours), "dt_s": float(dt_s),
               "scheme": scheme, "frame_interval_s": float((listing[picked[1]][0] - listing[picked[0]][0]).total_seconds()),
               "method": "kinematic, index space, linear in space and time; no sub-grid mixing"},
    )
    for name, units in (("z_msl", "m"), ("z_agl", "m"), ("theta", "K"), ("k", "mass-level index, 0 = lowest")):
        ds[name].attrs["units"] = units
    return ds


def back_trajectories(run_dir: str | Path, domain: int, release: np.ndarray, t0: datetime, hours: float, **kw):
    """Backward trajectories for ``hours`` (a positive number) ending at ``t0``."""
    return trajectories(run_dir, domain, release, t0, -abs(hours), **kw)


def forward_trajectories(run_dir: str | Path, domain: int, release: np.ndarray, t0: datetime, hours: float, **kw):
    """Forward trajectories for ``hours`` starting at ``t0``."""
    return trajectories(run_dir, domain, release, t0, abs(hours), **kw)


def sampling_separation(reference, other, statics: Statics | None = None) -> dict[str, np.ndarray]:
    """Horizontal and vertical separation of two trajectory sets at their final common time.

    Both are Datasets from :func:`trajectories` for the same release; ``other`` used a
    coarser frame interval.  Returns per-parcel ``horizontal_km`` and ``vertical_m`` (NaN
    where either parcel left the grid), which is the cost of that sampling interval.
    """
    t = np.intersect1d(reference["time"].values, other["time"].values)
    if t.size == 0:
        raise ValueError("the two trajectory sets share no output time")
    # the common time farthest from the release
    t0 = np.datetime64(reference.attrs["t0"])
    tf = t[np.argmax(np.abs(t - t0))]
    a, b = reference.sel(time=tf), other.sel(time=tf)
    coslat = np.cos(np.deg2rad(np.nanmean(a["lat"].values)))
    dy = (a["lat"].values - b["lat"].values) * 110.574
    dx = (a["lon"].values - b["lon"].values) * 111.320 * coslat
    return {"time": tf, "horizontal_km": np.hypot(dx, dy), "vertical_m": np.abs(a["z_agl"].values - b["z_agl"].values)}

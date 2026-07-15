"""Read and derive fields from WRF ``wrfout`` history files.

This is the WRF-output analogue of the Herbie-based download path: it owns the
file I/O and physics (destaggering, potential temperature, geometric height,
earth-relative winds) and hands *plain numpy* arrays to the ``visualize``
renderers, which stay dataset-agnostic (see ``visualize/grid.py``).

wrfout files are NETCDF4/HDF5, so opening needs the ``netcdf4`` engine.  WRF
``Times`` is a char array, not CF time, hence ``decode_times=False``.

Conventions (validated against the pelican2013 d03 runs):
  * ``T``  is *perturbation* potential temperature; theta = ``T`` + 300 K.
  * pressure = ``P`` + ``PB`` (Pa); geopotential height = (``PH`` + ``PHB``) / g,
    on w-levels (``bottom_top_stag``), destaggered to mass levels.
  * ``U``/``V``/``W`` are staggered on ``west_east_stag`` / ``south_north_stag`` /
    ``bottom_top_stag`` and destaggered by *dim name*.
  * horizontal winds are grid-relative; rotate to earth-relative with
    ``COSALPHA``/``SINALPHA`` for map/upper-air plots.  Cross-sections along a
    grid axis keep the grid-relative component.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

# Physical constants — g matches brc-wrf's wrf_quicklook.py for bit-parity when
# that repo migrates onto this module.
G = 9.80665
P0 = 100000.0  # reference pressure (Pa)
RCP = 0.2854  # R_d / c_p
CP = 1004.0  # J kg-1 K-1
THETA0 = 300.0  # WRF base-state offset for perturbation potential temperature
KT = 1.94384  # m s-1 -> knots

_WRFOUT_TIME_FMT = "%Y-%m-%d_%H:%M:%S"
_WRFOUT_DOMAIN_RE = re.compile(r"^wrfout_d(\d+)_")


# --------------------------------------------------------------------------- #
# open / locate
# --------------------------------------------------------------------------- #
def open_wrfout(path: str | Path):
    """Open a wrfout file as an xarray Dataset (NETCDF4/HDF5)."""
    import xarray as xr

    return xr.open_dataset(Path(path), engine="netcdf4", decode_times=False)


def wrfout_path(run_dir: str | Path, domain: int, valid_time: datetime) -> Path:
    """Return the wrfout path for a domain and valid time in a run directory."""
    return Path(run_dir) / f"wrfout_d{domain:02d}_{valid_time:{_WRFOUT_TIME_FMT}}"


def list_valid_times(run_dir: str | Path, domain: int) -> list[datetime]:
    """List the valid times available for a domain, parsed from filenames."""
    run_dir = Path(run_dir)
    prefix = f"wrfout_d{domain:02d}_"
    times: list[datetime] = []
    for p in sorted(run_dir.glob(f"{prefix}*")):
        stamp = p.name[len(prefix):]
        try:
            times.append(datetime.strptime(stamp, _WRFOUT_TIME_FMT))
        except ValueError:
            continue
    return times


def init_time(run_dir: str | Path, domain: int) -> datetime:
    """Return a run's model initialization (cycle) time for a domain.

    Prefers the ``SIMULATION_START_DATE`` global attribute of the earliest wrfout
    file — authoritative even when the first history dump is not at t0 — and falls
    back to the earliest valid time parsed from the filenames.  Forecast lead time
    is then ``valid_time - init_time`` (there is no lead offset in the filenames).
    """
    times = list_valid_times(run_dir, domain)
    if not times:
        raise FileNotFoundError(f"no wrfout_d{domain:02d}_* files under {run_dir}")
    earliest = times[0]
    try:
        ds = open_wrfout(wrfout_path(run_dir, domain, earliest))
    except (FileNotFoundError, OSError):
        return earliest
    try:
        stamp = ds.attrs.get("SIMULATION_START_DATE")
    finally:
        ds.close()
    if stamp:
        try:
            return datetime.strptime(str(stamp).strip(), _WRFOUT_TIME_FMT)
        except ValueError:
            pass
    return earliest


def latest_run_dir(parent: str | Path) -> Path:
    """Return the most recent ``run_*`` directory under ``parent``."""
    runs = sorted(Path(parent).glob("run_*"))
    if not runs:
        raise FileNotFoundError(f"no run_* directory under {parent}")
    return runs[-1]


def discover_domains(run_dir: str | Path) -> list[int]:
    """List the domain numbers present in a run directory (parsed from filenames).

    Globs ``wrfout_d0N_*`` and returns the sorted, unique domain integers so callers
    can adapt to a 2-, 3-, or 4-nest run instead of assuming a fixed count.  Uses the
    same filename convention as :func:`list_valid_times` and :func:`wrfout_path`.
    """
    run_dir = Path(run_dir)
    domains: set[int] = set()
    for p in run_dir.glob("wrfout_d*_*"):
        m = _WRFOUT_DOMAIN_RE.match(p.name)
        if m:
            domains.add(int(m.group(1)))
    return sorted(domains)


# --------------------------------------------------------------------------- #
# low-level helpers
# --------------------------------------------------------------------------- #
def _da(ds, name: str):
    """Return ``ds[name]`` with a leading ``Time`` dimension squeezed off."""
    da = ds[name]
    return da.isel(Time=0) if "Time" in da.dims else da


def destagger(da, dim: str):
    """Average adjacent values along ``dim`` and drop the ``_stag`` suffix.

    Works on the dimension *name* (not position), so it is robust to dim
    reordering.  Returns a DataArray on the unstaggered dimension.
    """
    import xarray as xr

    n = da.sizes[dim]
    avg = 0.5 * (
        da.isel({dim: slice(0, n - 1)}).data + da.isel({dim: slice(1, n)}).data
    )
    new_dim = dim.replace("_stag", "")
    dims = [new_dim if d == dim else d for d in da.dims]
    return xr.DataArray(avg, dims=dims)


# --------------------------------------------------------------------------- #
# 3-D derivations (return numpy, Time squeezed)
# --------------------------------------------------------------------------- #
def potential_temperature(ds) -> np.ndarray:
    """Full potential temperature (K): ``T`` + 300."""
    return np.asarray((_da(ds, "T") + THETA0).values)


def pressure_pa(ds) -> np.ndarray:
    """Full pressure (Pa): ``P`` + ``PB``."""
    return np.asarray((_da(ds, "P") + _da(ds, "PB")).values)


def temperature_k(ds) -> np.ndarray:
    """Air temperature (K) from theta and pressure."""
    theta = potential_temperature(ds)
    p = pressure_pa(ds)
    return theta * (p / P0) ** RCP


def geopotential_height_w(ds) -> np.ndarray:
    """Geometric height (m ASL) on w-levels (``bottom_top_stag``)."""
    return np.asarray(((_da(ds, "PH") + _da(ds, "PHB")) / G).values)


def geopotential_height_mass(ds) -> np.ndarray:
    """Geometric height (m ASL) on mass levels (destaggered w -> mass)."""
    z_w = (_da(ds, "PH") + _da(ds, "PHB")) / G
    return np.asarray(destagger(z_w, "bottom_top_stag").values)


def height_agl(ds) -> np.ndarray:
    """Height above ground (m) on mass levels."""
    return geopotential_height_mass(ds) - surface_field(ds, "HGT")[np.newaxis, :, :]


def qvapor(ds) -> np.ndarray:
    """Water-vapour mixing ratio (kg/kg) on mass levels."""
    return np.asarray(_da(ds, "QVAPOR").values)


# --------------------------------------------------------------------------- #
# winds
# --------------------------------------------------------------------------- #
def grid_relative_winds(ds) -> tuple[np.ndarray, np.ndarray]:
    """Destaggered, *grid-relative* horizontal winds (u, v) on mass points."""
    u = destagger(_da(ds, "U"), "west_east_stag").values
    v = destagger(_da(ds, "V"), "south_north_stag").values
    return np.asarray(u), np.asarray(v)


def vertical_velocity(ds) -> np.ndarray:
    """Destaggered vertical velocity ``w`` (m/s) on mass levels."""
    return np.asarray(destagger(_da(ds, "W"), "bottom_top_stag").values)


def earth_relative_winds(ds) -> tuple[np.ndarray, np.ndarray]:
    """Earth-relative winds (ue, ve) rotated from the grid via COSALPHA/SINALPHA.

    Uses the WRF convention ``ue = u*cosa - v*sina`` / ``ve = v*cosa + u*sina``.
    Defaults to identity if the rotation fields are absent.
    """
    u, v = grid_relative_winds(ds)
    cosa = surface_field(ds, "COSALPHA") if "COSALPHA" in ds else np.ones(u.shape[1:])
    sina = surface_field(ds, "SINALPHA") if "SINALPHA" in ds else np.zeros(u.shape[1:])
    cosa = cosa[np.newaxis, :, :]
    sina = sina[np.newaxis, :, :]
    ue = u * cosa - v * sina
    ve = v * cosa + u * sina
    return ue, ve


# --------------------------------------------------------------------------- #
# surface fields
# --------------------------------------------------------------------------- #
def surface_field(ds, name: str) -> np.ndarray:
    """Return a 2-D surface field with the ``Time`` dimension squeezed off."""
    return np.asarray(_da(ds, name).values)


def theta_2m(ds) -> np.ndarray:
    """2 m potential temperature (K): prefer ``TH2`` (full theta), else derive."""
    if "TH2" in ds:
        return surface_field(ds, "TH2")
    t2 = surface_field(ds, "T2")
    psfc = surface_field(ds, "PSFC")
    return t2 * (P0 / psfc) ** RCP


# --------------------------------------------------------------------------- #
# geometry / point extraction
# --------------------------------------------------------------------------- #
def dx_dy(ds) -> tuple[float, float]:
    """Grid spacing (m) from global attributes."""
    return float(ds.attrs["DX"]), float(ds.attrs["DY"])


def grid_cell_area_m2(ds) -> np.ndarray:
    """Projected mass-grid cell area (m2), including the WRF map factor.

    WRF's ``DX`` and ``DY`` are distances on the computational grid.  Physical
    cell area is therefore ``DX * DY / MAPFAC_M**2``; when ``MAPFAC_M`` is not
    present (including small synthetic fixtures), the identity map factor is
    used.
    """
    dx, dy = dx_dy(ds)
    if "MAPFAC_M" not in ds:
        shape = surface_field(ds, "XLAT").shape
        return np.full(shape, dx * dy, dtype=float)
    mapfac = surface_field(ds, "MAPFAC_M")
    return (dx * dy) / np.square(mapfac)


def grid_spacing_label(ds) -> str:
    """Human-readable grid spacing from the ``DX`` global attr (e.g. ``3 km``, ``333 m``).

    Lets a figure engine label nests from the data (``d02 (1 km)``) instead of a
    hardcoded per-case string.  ``>= 1 km`` renders in km, else rounded to whole metres.
    """
    dx = float(ds.attrs["DX"])
    if dx >= 1000.0:
        return f"{dx / 1000.0:g} km"
    return f"{round(dx):g} m"


def center_indices(ds) -> tuple[int, int]:
    """Mass-grid centre indices ``(j, i)``."""
    return ds.sizes["south_north"] // 2, ds.sizes["west_east"] // 2


def nearest_column_index(ds, lat: float, lon: float) -> tuple[int, int]:
    """Nearest mass-grid column ``(j, i)`` to a lat/lon (cKDTree on XLAT/XLONG)."""
    from scipy.spatial import cKDTree

    xlat = surface_field(ds, "XLAT")
    xlon = surface_field(ds, "XLONG")
    tree = cKDTree(np.column_stack([xlat.ravel(), xlon.ravel()]))
    _, idx = tree.query([lat, lon])
    j, i = np.unravel_index(int(idx), xlat.shape)
    return int(j), int(i)


def point_in_domain(ds, lat: float, lon: float, *, pad: float = 0.0) -> bool:
    """Whether ``(lat, lon)`` lies within the domain's XLAT/XLONG bounding box.

    :func:`nearest_column_index` always returns the closest cell — even for a point
    far outside the grid — so a focus point off the domain silently resolves to an
    edge column.  This is the explicit membership test a figure engine uses to warn
    (and skip point-dependent figures) instead of plotting that misleading edge cell.
    ``pad`` (degrees) loosens the box for near-edge tolerance.
    """
    xlat = surface_field(ds, "XLAT")
    xlon = surface_field(ds, "XLONG")
    return bool(
        (float(xlat.min()) - pad) <= lat <= (float(xlat.max()) + pad)
        and (float(xlon.min()) - pad) <= lon <= (float(xlon.max()) + pad)
    )


def _dewpoint_c(pressure_pa_col: np.ndarray, qv: np.ndarray) -> np.ndarray:
    """Dewpoint (deg C) from pressure (Pa) and mixing ratio (kg/kg), Magnus form."""
    qv = np.clip(qv, 1e-12, None)
    e = pressure_pa_col * qv / (0.622 + qv)  # vapour partial pressure (Pa)
    ln = np.log(np.clip(e / 611.2, 1e-12, None))
    return 243.5 * ln / (17.67 - ln)


# --------------------------------------------------------------------------- #
# structured extractions
# --------------------------------------------------------------------------- #
@dataclass
class WRFColumn:
    """A single model column (for profiles / skew-T / cold-pool diagnostics)."""

    lat: float
    lon: float
    label: str
    pressure_hpa: np.ndarray
    height_asl: np.ndarray
    terrain_m: float
    theta: np.ndarray
    temperature_c: np.ndarray
    dewpoint_c: np.ndarray
    u_kt: np.ndarray
    v_kt: np.ndarray


def extract_column(ds, lat: float, lon: float, *, label: str = "") -> WRFColumn:
    """Extract the nearest model column to ``(lat, lon)``.

    Slices a 2x2 block around the target column first so only a small hyperslab is
    read from disk — important when looping many files (e.g. a heat-deficit series).
    """
    j, i = nearest_column_index(ds, lat, lon)
    ny, nx = ds.sizes["south_north"], ds.sizes["west_east"]
    j0 = min(max(j, 0), ny - 2)
    i0 = min(max(i, 0), nx - 2)
    lj, li = j - j0, i - i0
    sub = ds.isel(
        south_north=slice(j0, j0 + 2),
        west_east=slice(i0, i0 + 2),
        south_north_stag=slice(j0, j0 + 3),
        west_east_stag=slice(i0, i0 + 3),
    )
    p = pressure_pa(sub)[:, lj, li]
    ue, ve = earth_relative_winds(sub)
    qv = qvapor(sub)[:, lj, li] if "QVAPOR" in sub else np.zeros_like(p)
    return WRFColumn(
        lat=float(lat),
        lon=float(lon),
        label=label,
        pressure_hpa=p / 100.0,
        height_asl=geopotential_height_mass(sub)[:, lj, li],
        terrain_m=float(surface_field(sub, "HGT")[lj, li]),
        theta=potential_temperature(sub)[:, lj, li],
        temperature_c=temperature_k(sub)[:, lj, li] - 273.15,
        dewpoint_c=_dewpoint_c(p, qv),
        u_kt=ue[:, lj, li] * KT,
        v_kt=ve[:, lj, li] * KT,
    )


@dataclass
class WRFSection:
    """A grid-axis-aligned vertical cross-section (no horizontal interpolation)."""

    orientation: str  # "EW" | "NS"
    distance_km: np.ndarray  # (n,)
    height2d: np.ndarray  # (nz, n) m ASL, terrain-following
    theta2d: np.ndarray  # (nz, n) K
    terrain1d: np.ndarray  # (n,) m ASL
    along2d: np.ndarray  # (nz, n) in-plane horizontal wind (grid-relative)
    w2d: np.ndarray  # (nz, n) m/s
    lon_line: np.ndarray  # (n,)
    lat_line: np.ndarray  # (n,)
    center_index: int
    termini: tuple[str, str]


def build_section(ds, orientation: str, *, index: int | None = None) -> WRFSection:
    """Build a cross-section through a grid row (EW) or column (NS).

    The section follows a grid axis, so the along-section horizontal wind is the
    *grid-relative* component (``U`` for EW, ``V`` for NS) — never earth-rotated.
    """
    orientation = orientation.upper()
    theta = potential_temperature(ds)
    z = geopotential_height_mass(ds)
    u, v = grid_relative_winds(ds)
    w = vertical_velocity(ds)
    hgt = surface_field(ds, "HGT")
    xlon = surface_field(ds, "XLONG")
    xlat = surface_field(ds, "XLAT")
    dx, dy = dx_dy(ds)
    jc, ic = center_indices(ds)

    if orientation == "EW":
        j = jc if index is None else index
        n = ds.sizes["west_east"]
        return WRFSection(
            orientation="EW",
            distance_km=np.arange(n) * dx / 1000.0,
            height2d=z[:, j, :],
            theta2d=theta[:, j, :],
            terrain1d=hgt[j, :],
            along2d=u[:, j, :],
            w2d=w[:, j, :],
            lon_line=xlon[j, :],
            lat_line=xlat[j, :],
            center_index=int(j),
            termini=("A", "B"),
        )
    if orientation == "NS":
        i = ic if index is None else index
        n = ds.sizes["south_north"]
        return WRFSection(
            orientation="NS",
            distance_km=np.arange(n) * dy / 1000.0,
            height2d=z[:, :, i],
            theta2d=theta[:, :, i],
            terrain1d=hgt[:, i],
            along2d=v[:, :, i],
            w2d=w[:, :, i],
            lon_line=xlon[:, i],
            lat_line=xlat[:, i],
            center_index=int(i),
            termini=("C", "D"),
        )
    raise ValueError(f"orientation must be 'EW' or 'NS', got {orientation!r}")


@dataclass
class DomainOutline:
    """The lon/lat boundary ring of a domain (for nest maps)."""

    lon_ring: np.ndarray
    lat_ring: np.ndarray
    label: str


def domain_outline(ds, *, label: str = "") -> DomainOutline:
    """Return the boundary ring (clockwise) of a domain from XLAT/XLONG edges."""
    xlat = surface_field(ds, "XLAT")
    xlon = surface_field(ds, "XLONG")
    lon_ring = np.concatenate([xlon[0, :], xlon[:, -1], xlon[-1, ::-1], xlon[::-1, 0]])
    lat_ring = np.concatenate([xlat[0, :], xlat[:, -1], xlat[-1, ::-1], xlat[::-1, 0]])
    return DomainOutline(lon_ring=lon_ring, lat_ring=lat_ring, label=label)


# --------------------------------------------------------------------------- #
# cold-pool diagnostics
# --------------------------------------------------------------------------- #
def delta_theta_crest_floor(col: WRFColumn, crest_m: float) -> float:
    """Potential-temperature difference crest-minus-floor (K); cold-pool strength."""
    theta_crest = float(np.interp(crest_m, col.height_asl, col.theta))
    return theta_crest - float(col.theta[0])


def cold_pool_heat_deficit(col: WRFColumn, crest_m: float) -> float:
    """Whiteman-style valley heat deficit (J m-2) below ``crest_m``.

    H = (c_p / g) * integral_{p_sfc}^{p_crest} (theta_crest - theta) dp
    Positive where the low layer is colder than the crest-level air.
    """
    mask = col.height_asl <= crest_m
    if mask.sum() < 2:
        return 0.0
    from scipy.integrate import trapezoid

    theta_crest = float(np.interp(crest_m, col.height_asl, col.theta))
    p = col.pressure_hpa[mask] * 100.0  # Pa
    integrand = np.clip(theta_crest - col.theta[mask], 0.0, None)
    return float(abs((CP / G) * trapezoid(integrand, p)))


@dataclass
class _DeficitKernel:
    """Shared crest-referenced deficit integrand for H, its transport F, and depth."""

    integrand: np.ndarray  # (nz, ny, nx) max(theta_crest - theta, 0), zeroed above crest
    pressure_pa: np.ndarray  # (nz, ny, nx) Pa
    height_asl: np.ndarray  # (nz, ny, nx) m ASL, mass levels
    theta_crest: np.ndarray  # (ny, nx) K, theta interpolated to crest_m per column


@dataclass
class DeficitBulkFields:
    """Bulk fields derived from one crest-referenced deficit kernel.

    ``transport_velocity`` is the deficit-weighted horizontal wind ``F/H``.
    ``froude`` is an exploratory reduced-gravity proxy based on the diagnosed
    mean deficit and layer depth; it is not a hydraulic-control diagnosis.
    """

    heat_deficit_j_m2: np.ndarray
    flux_x_w_m: np.ndarray
    flux_y_w_m: np.ndarray
    velocity_x_m_s: np.ndarray
    velocity_y_m_s: np.ndarray
    depth_m: np.ndarray
    mean_deficit_k: np.ndarray
    froude: np.ndarray
    theta_crest_k: np.ndarray


def _deficit_kernel(ds, crest_m: float) -> _DeficitKernel:
    """Crest-referenced deficit integrand, factored out so :func:`heat_deficit_field`,
    :func:`deficit_flux_field` and :func:`cold_pool_depth_field` share one convention
    (identical ``theta_crest`` interpolation, below-crest mask, and clipping)."""
    theta = potential_temperature(ds)        # (nz, ny, nx) K
    z = geopotential_height_mass(ds)         # (nz, ny, nx) m ASL
    p = pressure_pa(ds)                      # (nz, ny, nx) Pa
    nz = z.shape[0]

    below = z <= crest_m                     # (nz, ny, nx)
    # last mass level at/below the crest per column, clamped so the k+1 gather stays valid.
    k = np.clip(below.sum(axis=0) - 1, 0, nz - 2)   # (ny, nx)

    def _gather(a, idx):
        return np.take_along_axis(a, idx[np.newaxis], axis=0)[0]

    z0, z1 = _gather(z, k), _gather(z, k + 1)
    t0, t1 = _gather(theta, k), _gather(theta, k + 1)
    w = np.clip((crest_m - z0) / np.maximum(z1 - z0, 1e-6), 0.0, 1.0)
    theta_crest = t0 + w * (t1 - t0)         # (ny, nx) theta at crest height

    integrand = np.where(below, np.clip(theta_crest[np.newaxis] - theta, 0.0, None), 0.0)
    return _DeficitKernel(
        integrand=integrand, pressure_pa=p, height_asl=z, theta_crest=theta_crest
    )


def heat_deficit_field(ds, crest_m: float) -> np.ndarray:
    """Whiteman valley heat deficit (J m-2) below ``crest_m``, over the whole grid.

    The spatial (2-D) companion to :func:`cold_pool_heat_deficit`: for every column,

        H = (c_p / g) * integral_{p_sfc}^{p_crest} max(theta_crest - theta, 0) dp

    with ``theta_crest`` the potential temperature linearly interpolated to ``crest_m``
    per column and the integrand zeroed above the crest.  Returns a ``(ny, nx)`` array of
    non-negative heat deficit (positive = a low layer colder than the crest-level air, i.e.
    a trapped cold pool).  Columns whose surface already lies at/above the crest -- the
    surrounding ranges -- come back ~0.

    The crest is an approximate upper boundary: the integrand is evaluated on the model
    levels and forced to zero at the first level above the crest rather than exactly at
    ``crest_m``.  Because the integrand -> 0 as theta -> theta_crest, that error sits where
    the signal is smallest and is negligible against the pool depth.
    """
    from scipy.integrate import trapezoid

    kern = _deficit_kernel(ds, crest_m)
    # trapz over pressure (which decreases with height); abs() fixes the sign, matching the
    # single-column diagnostic.  Columns with < 2 sub-crest levels integrate to ~0.
    return np.abs((CP / G) * trapezoid(kern.integrand, x=kern.pressure_pa, axis=0))


def deficit_flux_field(
    ds, crest_m: float, *, earth_relative: bool = True
) -> tuple[np.ndarray, np.ndarray]:
    """Integrated deficit transport (W m-1): the heat-deficit analogue of IVT.

        F = (c_p / g) * integral_{p_sfc}^{p_crest} max(theta_crest - theta, 0) * u_h dp

    The wind-weighted companion of :func:`heat_deficit_field`.  Clipping the deficit at
    zero confines the transport to the diagnosed cold layer — an unclipped integral
    would be dominated by the free troposphere.  Returns ``(Fx, Fy)`` in W per metre of
    transect width: earth-relative for maps (default), grid-relative for divergence /
    along-grid sections.

    ``-div(F)`` is the horizontal flux-convergence contribution to heat-deficit
    tendency.  Combining it with finite-difference storage leaves an *unresolved*
    tendency that can include diabatic physics, the time-varying local crest reference,
    movement of the clipped layer, vertical/boundary terms, and numerical error; it is
    not by itself a diabatic-heating diagnosis.
    """
    from scipy.integrate import trapezoid

    kern = _deficit_kernel(ds, crest_m)
    u, v = earth_relative_winds(ds) if earth_relative else grid_relative_winds(ds)
    # sign-preserving (no abs, unlike H): pressure decreases with height, so the
    # leading minus integrates surface->crest; the wind components carry the sign.
    fx = -(CP / G) * trapezoid(kern.integrand * u, x=kern.pressure_pa, axis=0)
    fy = -(CP / G) * trapezoid(kern.integrand * v, x=kern.pressure_pa, axis=0)
    return fx, fy


def horizontal_flux_divergence(
    ds,
    flux_x_w_m: np.ndarray,
    flux_y_w_m: np.ndarray,
    *,
    earth_relative: bool = False,
) -> np.ndarray:
    """Horizontal divergence of a mass-grid flux field (W m-2).

    Inputs are grid-relative by default. Set ``earth_relative=True`` for eastward /
    northward components; they are rotated back to the WRF grid before applying the
    map-factor divergence.

    Uses the WRF map-factor form ``m^2 * [d(Fx/m)/dx + d(Fy/m)/dy]`` and central
    differences via ``np.gradient``.
    """
    fx = np.asarray(flux_x_w_m, dtype=float)
    fy = np.asarray(flux_y_w_m, dtype=float)
    shape = surface_field(ds, "XLAT").shape
    if fx.shape != shape or fy.shape != shape:
        raise ValueError(f"flux fields must match mass-grid shape {shape}; got {fx.shape}, {fy.shape}")
    if earth_relative:
        cosa = surface_field(ds, "COSALPHA") if "COSALPHA" in ds else np.ones(shape)
        sina = surface_field(ds, "SINALPHA") if "SINALPHA" in ds else np.zeros(shape)
        fx, fy = fx * cosa + fy * sina, fy * cosa - fx * sina
    m = surface_field(ds, "MAPFAC_M") if "MAPFAC_M" in ds else np.ones_like(fx)
    dx, dy = dx_dy(ds)
    return m * m * (np.gradient(fx / m, dx, axis=1) + np.gradient(fy / m, dy, axis=0))


def deficit_flux_divergence(ds, crest_m: float) -> np.ndarray:
    """Horizontal ``div(F)`` of the deficit transport (W m-2).

    ``-div(F)`` is the horizontal flux-convergence contribution to ``dH/dt``, not a
    closed thermodynamic tendency or a uniquely diabatic/advective partition.

    Uses grid-relative components on the mass grid; see
    :func:`horizontal_flux_divergence` for the map-factor operator.
    """
    fx, fy = deficit_flux_field(ds, crest_m, earth_relative=False)
    return horizontal_flux_divergence(ds, fx, fy)


def cold_pool_depth_field(ds, crest_m: float, *, min_deficit_k: float = 0.0) -> np.ndarray:
    """Cold-pool depth (m AGL): top of the layer colder than the crest-level air.

    Height AGL of the highest model level whose deficit exceeds ``min_deficit_k``
    (level-discretised; 0 where no level qualifies).  A byproduct of the shared
    kernel, so depth, H and F carry one crest convention.
    """
    kern = _deficit_kernel(ds, crest_m)
    pos = kern.integrand > min_deficit_k
    top = pos.shape[0] - 1 - np.argmax(pos[::-1], axis=0)   # highest True per column
    z_agl = kern.height_asl - surface_field(ds, "HGT")[np.newaxis]
    depth = np.take_along_axis(z_agl, top[np.newaxis], axis=0)[0]
    return np.where(pos.any(axis=0), depth, 0.0)


def deficit_bulk_fields(
    ds,
    crest_m: float,
    *,
    min_deficit_k: float = 0.25,
    min_heat_deficit_j_m2: float = 1.0e5,
) -> DeficitBulkFields:
    """Return H, F/H, depth, mean deficit, and an exploratory bulk Froude proxy.

    The active layer contains levels whose crest-relative potential-temperature
    deficit exceeds ``min_deficit_k``.  Transport velocity is masked where ``H`` is
    below ``min_heat_deficit_j_m2``.  The bulk Froude proxy is

    ``|F/H| / sqrt(g * mean_deficit/theta_crest * depth)``.

    It is useful for exploratory maps, but does not establish hydraulic control: the
    diagnosed layer may be disconnected, the reference is local and time varying, and
    no along-canyon control section or observed layer depth is imposed.
    """
    from scipy.integrate import trapezoid

    kern = _deficit_kernel(ds, crest_m)
    u, v = earth_relative_winds(ds)
    pressure = kern.pressure_pa

    deficit_dp = -trapezoid(kern.integrand, x=pressure, axis=0)
    heat = (CP / G) * deficit_dp
    flux_x = -(CP / G) * trapezoid(kern.integrand * u, x=pressure, axis=0)
    flux_y = -(CP / G) * trapezoid(kern.integrand * v, x=pressure, axis=0)

    valid_h = heat >= float(min_heat_deficit_j_m2)
    velocity_x = np.divide(
        flux_x, heat, out=np.full_like(heat, np.nan, dtype=float), where=valid_h
    )
    velocity_y = np.divide(
        flux_y, heat, out=np.full_like(heat, np.nan, dtype=float), where=valid_h
    )

    active = kern.integrand > float(min_deficit_k)
    active_dp = -trapezoid(active.astype(float), x=pressure, axis=0)
    active_deficit_dp = -trapezoid(
        np.where(active, kern.integrand, 0.0), x=pressure, axis=0
    )
    mean_deficit = np.divide(
        active_deficit_dp,
        active_dp,
        out=np.full_like(heat, np.nan, dtype=float),
        where=active_dp > 0.0,
    )
    pos = active
    top = pos.shape[0] - 1 - np.argmax(pos[::-1], axis=0)
    z_agl = kern.height_asl - surface_field(ds, "HGT")[np.newaxis]
    depth = np.take_along_axis(z_agl, top[np.newaxis], axis=0)[0]
    depth = np.where(pos.any(axis=0), depth, 0.0)

    speed = np.hypot(velocity_x, velocity_y)
    reduced_gravity_depth = G * mean_deficit / kern.theta_crest * depth
    wave_speed = np.sqrt(np.clip(reduced_gravity_depth, 0.0, None))
    froude = np.divide(
        speed,
        wave_speed,
        out=np.full_like(speed, np.nan, dtype=float),
        where=valid_h & np.isfinite(wave_speed) & (wave_speed > 0.0),
    )
    return DeficitBulkFields(
        heat_deficit_j_m2=heat,
        flux_x_w_m=flux_x,
        flux_y_w_m=flux_y,
        velocity_x_m_s=velocity_x,
        velocity_y_m_s=velocity_y,
        depth_m=depth,
        mean_deficit_k=mean_deficit,
        froude=froude,
        theta_crest_k=kern.theta_crest,
    )


@dataclass
class TransectFlux:
    """Signed horizontal transport through a vertical plane along a lat/lon line."""

    lats: np.ndarray  # (n,) sample latitudes along a->b
    lons: np.ndarray  # (n,) sample longitudes
    j: np.ndarray  # (n,) nearest mass-grid row per sample
    i: np.ndarray  # (n,) nearest mass-grid column per sample
    dist_m: np.ndarray  # (n,) along-transect distance from a
    f_normal: np.ndarray  # (n,) F . n_hat, W m-1
    total_w: float  # Phi = integral F . n_hat ds, W
    normal_en: tuple[float, float]  # unit normal (east, north), rightward of a->b
    label: str = ""


def integrate_flux_transect(
    ds,
    flux_x_w_m: np.ndarray,
    flux_y_w_m: np.ndarray,
    lat_a: float,
    lon_a: float,
    lat_b: float,
    lon_b: float,
    *,
    spacing_m: float | None = None,
    label: str = "",
) -> TransectFlux:
    """Integrate an earth-relative horizontal flux field across an a->b line.

    ``flux_x_w_m`` and ``flux_y_w_m`` are eastward and northward components on the
    WRF mass grid. The function samples the nearest column every ``spacing_m``
    (default: grid ``min(dx, dy)``) and integrates the normal component,
    ``Phi = integral F . n_hat ds``, with ``n_hat`` the rightward normal walking
    a->b. Flat-earth metric, fine for basin-scale (< ~100 km) transects.
    """
    from scipy.integrate import trapezoid
    from scipy.spatial import cKDTree

    # local flat-earth metres per degree (mid-latitude approximations)
    coslat = np.cos(np.deg2rad(0.5 * (lat_a + lat_b)))
    ex = (lon_b - lon_a) * 111_320.0 * coslat
    ey = (lat_b - lat_a) * 110_540.0
    length = float(np.hypot(ex, ey))
    if length == 0.0:
        raise ValueError("transect endpoints coincide")

    dx, dy = dx_dy(ds)
    spacing = spacing_m if spacing_m is not None else min(dx, dy)
    n = max(int(np.ceil(length / spacing)) + 1, 2)
    frac = np.linspace(0.0, 1.0, n)
    lats = lat_a + frac * (lat_b - lat_a)
    lons = lon_a + frac * (lon_b - lon_a)
    tx, ty = ex / length, ey / length
    nx_e, ny_n = ty, -tx  # rightward normal to the a->b direction

    # one KD-tree for all samples (nearest_column_index would rebuild it per point)
    xlat = surface_field(ds, "XLAT")
    xlon = surface_field(ds, "XLONG")
    tree = cKDTree(np.column_stack([xlat.ravel(), xlon.ravel()]))
    _, idx = tree.query(np.column_stack([lats, lons]))
    jj, ii = np.unravel_index(np.asarray(idx, dtype=int), xlat.shape)

    fx = np.asarray(flux_x_w_m)
    fy = np.asarray(flux_y_w_m)
    if fx.shape != xlat.shape or fy.shape != xlat.shape:
        raise ValueError(
            f"flux fields must match mass-grid shape {xlat.shape}; got {fx.shape}, {fy.shape}"
        )
    f_normal = fx[jj, ii] * nx_e + fy[jj, ii] * ny_n
    dist = frac * length
    return TransectFlux(
        lats=lats,
        lons=lons,
        j=jj,
        i=ii,
        dist_m=dist,
        f_normal=f_normal,
        total_w=float(trapezoid(f_normal, dist)),
        normal_en=(nx_e, ny_n),
        label=label,
    )


def transect_deficit_flux(
    ds,
    crest_m: float,
    lat_a: float,
    lon_a: float,
    lat_b: float,
    lon_b: float,
    *,
    spacing_m: float | None = None,
    label: str = "",
) -> TransectFlux:
    """Deficit transport through the vertical plane over the a->b line (W).

    Positive ``Phi`` transports cold-pool heat deficit to the walker's right.
    Use :func:`integrate_flux_transect` when a caller already has the earth-relative
    deficit-flux fields and needs several transects without recomputing the column
    integral.
    """
    fx, fy = deficit_flux_field(ds, crest_m)
    return integrate_flux_transect(
        ds,
        fx,
        fy,
        lat_a,
        lon_a,
        lat_b,
        lon_b,
        spacing_m=spacing_m,
        label=label,
    )

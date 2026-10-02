"""Fixed and profile reference temperatures for the WRF heat-deficit diagnostics.

:mod:`brc_tools.nwp.wrf_output` measures the valley heat deficit against a *crest*
reference: the potential temperature each column has at ``crest_m`` at that output
time.  That datum is local and drifts through the night, so the deficit is not
conserved under adiabatic advection and the transport ``Phi`` through a canyon
mouth depends on the reference height -- Dry Fork's September night mean was
12.8 GW at 2600 m and 19.2 GW at 3340 m (ub-wx ``drainage-canyons-gigawatts``,
CHK-REFERENCE).  This module supplies the datum a *budget* needs:

``SunsetProfile``
    theta_ref(z): one profile per night, taken from the pre-sunset sounding over
    the basin floor.  Below the mixed-layer top it is the mixed-layer maximum
    (the temperature the drainage air had before the slopes started cooling);
    above it the floor-mean profile, floored at that value and made
    non-decreasing.  The deficit measured against it is *cooling since the
    profile was taken at that height*, materially conserved under adiabatic
    motion, and the same datum brc-voxel-viz can draw an isosurface against
    (the JSON sidecar, ``docs/CROSS-REPO-SYNC.md``).

``deficit_fixed_fields``
    H (J m-2) and its transport F (W m-1) against a fixed datum -- a float or a
    ``SunsetProfile`` -- capped at ``cap_agl_m`` above ground so the free
    troposphere never enters.  Box integration in height, rho * c_p * dtheta * dz,
    so catchment sums are additive in cell mass.

``two_datum`` / ``at_two_datums``
    The error bar.  The drainage layer is only 1-3 K colder than the air it
    displaces, so a 1.2 K shift of the datum changed a canyon's export three-fold
    on the September night; every number reported against a fixed datum should
    carry its value at ``ref -/+ delta_k`` beside it.

``catchment_budget_terms``
    Per catchment and output time: production P = sum(-HFX A), storage H, export
    Phi through the catchment's line(s) at the datum and at the two shifted
    datums, and the longwave production when the run wrote the radiative
    tendency (history name ``RTHRATLW``; ``RTHRATENLW`` is the restart name).

Nothing here touches :mod:`wrf_output`, :mod:`wrf_figures` or ``visualize``; it
imports the frozen readers and adds a datum on top.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np

from brc_tools.nwp import wrf_output as wo

__all__ = [
    "METHOD_VERSION", "SIDECAR_SCHEMA", "LW_TENDENCY_VARS", "Line",
    "SunsetProfile", "sunset_profile", "sunset_profile_from_run",
    "FixedDeficitFields", "deficit_fixed_fields", "longwave_production_field",
    "two_datum", "at_two_datums", "CatchmentTerms", "catchment_budget_terms",
]

METHOD_VERSION = "sunset-profile-1"
SIDECAR_SCHEMA = 1
LW_TENDENCY_VARS = ("RTHRATLW", "RTHRATENLW")   # history name first, restart name second
_RD = 287.05

Line = tuple[tuple[float, float], tuple[float, float]]   # ((lat_a, lon_a), (lat_b, lon_b))


# --------------------------------------------------------------------------- #
# the reference profile
# --------------------------------------------------------------------------- #
@dataclass
class SunsetProfile:
    """theta_ref(z): a mixed-layer datum below the mixed-layer top, the floor-mean
    profile above it, non-decreasing with height.  All heights are metres ASL.

    ``theta_ref(z)`` interpolates linearly and clamps at both ends, so a height below
    the lowest floor terrain sees the mixed-layer value and a height above ``top_m``
    sees the topmost profile value.
    """

    z_asl_m: np.ndarray                 # (n,) strictly increasing
    theta_k: np.ndarray                 # (n,) non-decreasing
    valid_time: datetime                # UTC, tz-naive
    mixed_layer_theta_k: float
    ml_depth_m: float
    top_m: float
    floor_label: str = ""               # what the floor mask was, in words
    floor_cells: int = 0
    ml_stat: str = "max"                # how the per-column ML theta was reduced over the floor
    method_version: str = METHOD_VERSION
    run_id: str = ""
    domain: int | None = None
    source_file: str = ""
    case: str = ""
    night: str = ""                     # YYYYMMDD label used in the sidecar name
    notes: str = ""
    schema: int = field(default=SIDECAR_SCHEMA)

    def __post_init__(self):
        self.z_asl_m = np.asarray(self.z_asl_m, dtype=float)
        self.theta_k = np.asarray(self.theta_k, dtype=float)
        if self.z_asl_m.ndim != 1 or self.z_asl_m.shape != self.theta_k.shape:
            raise ValueError("z_asl_m and theta_k must be 1-D arrays of the same length")
        if self.z_asl_m.size < 2:
            raise ValueError("a profile needs at least two levels")
        if np.any(np.diff(self.z_asl_m) <= 0):
            raise ValueError("z_asl_m must be strictly increasing")
        if isinstance(self.valid_time, str):
            self.valid_time = _parse_iso(self.valid_time)
        if self.valid_time.tzinfo is not None:
            self.valid_time = self.valid_time.astimezone(timezone.utc).replace(tzinfo=None)

    # -- evaluation ------------------------------------------------------- #
    def theta_ref(self, z_asl_m) -> np.ndarray:
        """theta_ref at height(s) ``z_asl_m`` (any shape), linear, edge-clamped."""
        z = np.asarray(z_asl_m, dtype=float)
        return np.interp(z, self.z_asl_m, self.theta_k)

    def shifted(self, delta_k: float) -> SunsetProfile:
        """The same profile moved by ``delta_k`` everywhere (the error-bar datum)."""
        out = SunsetProfile(**{**asdict(self), "z_asl_m": self.z_asl_m.copy(),
                               "theta_k": self.theta_k + float(delta_k),
                               "mixed_layer_theta_k": self.mixed_layer_theta_k + float(delta_k),
                               "notes": (self.notes + f" shifted {delta_k:+.3f} K").strip()})
        return out

    # -- the sidecar ------------------------------------------------------- #
    def sidecar_name(self) -> str:
        case = self.case or "case"
        night = self.night or self.valid_time.strftime("%Y%m%d")
        return f"theta_ref_{case}_{night}.json"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["z_asl_m"] = [float(v) for v in self.z_asl_m]
        d["theta_k"] = [float(v) for v in self.theta_k]
        d["valid_time"] = self.valid_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        return d

    def to_json(self, path: str | Path | None = None, *, indent: int = 1) -> str:
        """Serialise; when ``path`` is given also write the sidecar there."""
        text = json.dumps(self.to_dict(), indent=indent)
        if path is not None:
            Path(path).write_text(text)
        return text

    @classmethod
    def from_json(cls, src: str | Path | dict) -> SunsetProfile:
        if isinstance(src, dict):
            d = dict(src)
        else:
            p = Path(src)
            d = json.loads(p.read_text() if p.exists() else str(src))
        schema = int(d.pop("schema", SIDECAR_SCHEMA))
        if schema > SIDECAR_SCHEMA:
            raise ValueError(f"sidecar schema {schema} is newer than this reader ({SIDECAR_SCHEMA})")
        d["z_asl_m"] = np.asarray(d["z_asl_m"], dtype=float)
        d["theta_k"] = np.asarray(d["theta_k"], dtype=float)
        d["valid_time"] = _parse_iso(d["valid_time"])
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known}, schema=schema)


def _parse_iso(s: str) -> datetime:
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1]
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _column_ml_theta(theta: np.ndarray, agl: np.ndarray, ml_depth_m: float) -> np.ndarray:
    """Per-column mean theta over the levels within ``ml_depth_m`` of the ground
    (the lowest level always counts), ``(ny, nx)``."""
    inside = agl <= ml_depth_m
    inside[0] = True
    w = inside.astype(float)
    return (theta * w).sum(axis=0) / w.sum(axis=0)


def sunset_profile(
    ds,
    floor_mask: np.ndarray,
    *,
    time: datetime,
    ml_depth_m: float = 500.0,
    top_m: float = 6000.0,
    dz_m: float = 25.0,
    ml_stat: str = "max",
    floor_label: str = "",
    run_id: str = "",
    case: str = "",
    night: str = "",
    domain: int | None = None,
    source_file: str = "",
) -> SunsetProfile:
    """Build the pre-sunset reference profile from one ``wrfout`` and a floor mask.

    ``floor_mask`` is ``(ny, nx)`` bool: the receiving floor whose mixed layer sets
    the datum (e.g. terrain below 1800 m inside a valley box).  ``ml_stat`` reduces
    the per-column mixed-layer theta over those columns: ``"max"`` (default; the
    warmest floor column, so a floor cell already shaded at the chosen hour cannot
    drag the datum down), ``"median"`` or ``"mean"``.  Above the mixed-layer top the
    profile is the floor-mean theta in ``dz_m`` bins of height ASL up to ``top_m``,
    floored at the mixed-layer value and made non-decreasing; gaps are interpolated.
    """
    floor = np.asarray(floor_mask, dtype=bool)
    if floor.ndim != 2 or not floor.any():
        raise ValueError("floor_mask must be a 2-D boolean mask with at least one True cell")
    theta = wo.potential_temperature(ds)
    z = wo.geopotential_height_mass(ds)
    agl = wo.height_agl(ds)
    if floor.shape != theta.shape[1:]:
        raise ValueError(f"floor_mask shape {floor.shape} != grid {theta.shape[1:]}")

    col_ml = _column_ml_theta(theta, agl, ml_depth_m)[floor]
    reducer = {"max": np.max, "median": np.median, "mean": np.mean}
    if ml_stat not in reducer:
        raise ValueError(f"ml_stat must be one of {sorted(reducer)}")
    theta_ml = float(reducer[ml_stat](col_ml))

    # floor-mean profile on a regular ASL grid from the lowest floor terrain to top_m
    hgt = wo.surface_field(ds, "HGT")
    z0 = float(np.floor(np.min(hgt[floor]) / dz_m) * dz_m)
    edges = np.arange(z0, top_m + dz_m, dz_m)
    centres = 0.5 * (edges[:-1] + edges[1:])
    zs = z[:, floor].ravel()
    ts = theta[:, floor].ravel()
    ok = (zs >= edges[0]) & (zs < edges[-1])
    idx = np.digitize(zs[ok], edges) - 1
    sums = np.bincount(idx, weights=ts[ok], minlength=centres.size)
    counts = np.bincount(idx, minlength=centres.size)
    have = counts > 0
    if have.sum() < 2:
        raise ValueError("fewer than two profile bins hold floor samples; raise top_m or dz_m")
    prof = np.interp(centres, centres[have], sums[have] / counts[have])
    prof = np.maximum(prof, theta_ml)
    prof = np.maximum.accumulate(prof)
    return SunsetProfile(
        z_asl_m=centres, theta_k=prof, valid_time=time, mixed_layer_theta_k=theta_ml,
        ml_depth_m=float(ml_depth_m), top_m=float(top_m), floor_label=floor_label,
        floor_cells=int(floor.sum()), ml_stat=ml_stat, run_id=run_id, domain=domain,
        source_file=source_file, case=case, night=night,
    )


def sunset_profile_from_run(run_dir, domain: int, time: datetime, floor_mask, **kw) -> SunsetProfile:
    """Open the wrfout for ``(domain, time)`` in ``run_dir`` and call :func:`sunset_profile`."""
    path = wo.wrfout_path(run_dir, domain, time)
    ds = wo.open_wrfout(path)
    try:
        kw.setdefault("source_file", path.name)
        kw.setdefault("domain", domain)
        return sunset_profile(ds, floor_mask, time=time, **kw)
    finally:
        ds.close()


# --------------------------------------------------------------------------- #
# deficit and transport against a fixed datum
# --------------------------------------------------------------------------- #
@dataclass
class FixedDeficitFields:
    """H and F against a fixed datum, plus the datum itself on the model levels."""

    heat_deficit_j_m2: np.ndarray       # (ny, nx)
    flux_x_w_m: np.ndarray              # (ny, nx), eastward (or grid-x) component
    flux_y_w_m: np.ndarray              # (ny, nx)
    theta_ref_k: np.ndarray | float     # (nz, ny, nx) for a profile, scalar for a float
    cap_agl_m: float


def _density(ds) -> np.ndarray:
    """Moist density when QVAPOR is present, dry otherwise (kg m-3, mass levels)."""
    if "QVAPOR" in ds:
        from brc_tools.nwp.wrf_derived import air_density
        return air_density(ds)
    return wo.pressure_pa(ds) / (_RD * wo.temperature_k(ds))


def _reference_on_levels(ref, z_mass: np.ndarray):
    if isinstance(ref, SunsetProfile):
        return ref.theta_ref(z_mass)
    return float(ref)


def _layer_weights(ds, ref, cap_agl_m: float):
    """rho * c_p * max(theta_ref - theta, 0) * dz on mass levels, zero above the cap."""
    theta = wo.potential_temperature(ds)
    z_w = wo.geopotential_height_w(ds)
    dz = z_w[1:] - z_w[:-1]
    z_mass = 0.5 * (z_w[1:] + z_w[:-1])
    agl = wo.height_agl(ds)
    theta_ref = _reference_on_levels(ref, z_mass)
    integrand = np.clip(theta_ref - theta, 0.0, None)
    integrand = np.where(agl > cap_agl_m, 0.0, integrand)
    w = _density(ds) * wo.CP * integrand * dz
    return w, theta_ref, integrand


def deficit_fixed_fields(
    ds, ref: SunsetProfile | float, *, cap_agl_m: float = 1500.0, earth_relative: bool = True
) -> FixedDeficitFields:
    """Heat deficit ``H`` (J m-2) and transport ``F`` (W m-1) against a fixed datum.

        H = sum_k rho_k c_p max(theta_ref(z_k) - theta_k, 0) dz_k      (agl_k <= cap)
        F = sum_k rho_k c_p max(theta_ref(z_k) - theta_k, 0) u_k dz_k

    ``ref`` is a :class:`SunsetProfile` (theta_ref varies with height ASL) or a float
    (one datum everywhere).  The cap keeps the free troposphere out of a datum that
    was only ever meant for the boundary layer; 1500 m AGL holds every Basin pool and
    every slope jet with margin.  Winds are earth-relative by default (for transects
    and maps); pass ``earth_relative=False`` for grid-relative divergence work.
    """
    w, theta_ref, _ = _layer_weights(ds, ref, cap_agl_m)
    u, v = wo.earth_relative_winds(ds) if earth_relative else wo.grid_relative_winds(ds)
    return FixedDeficitFields(
        heat_deficit_j_m2=w.sum(axis=0),
        flux_x_w_m=(w * u).sum(axis=0),
        flux_y_w_m=(w * v).sum(axis=0),
        theta_ref_k=theta_ref,
        cap_agl_m=float(cap_agl_m),
    )


def longwave_production_field(
    ds, ref: SunsetProfile | float, *, cap_agl_m: float = 1500.0, only_deficit_layer: bool = True
) -> np.ndarray | None:
    """Deficit production by longwave cooling of the air, W m-2, positive when cooling.

        P_LW = - sum_k rho_k c_p (dtheta/dt)_LW,k dz_k

    over the levels below the cap (and, by default, only where the column already
    holds deficit against ``ref``, so the number is deficit *production* rather than
    the radiative tendency of the whole column).  Reads ``RTHRATLW`` (the history-stream
    name written through ``iofields``) or ``RTHRATENLW`` (the restart name).  Returns
    ``None`` when the run wrote neither -- the term the two 600 m runs never had.
    """
    var = next((v for v in LW_TENDENCY_VARS if v in ds), None)
    if var is None:
        return None
    tend = np.asarray(ds[var].values)
    if tend.ndim == 4:
        tend = tend[0]
    z_w = wo.geopotential_height_w(ds)
    dz = z_w[1:] - z_w[:-1]
    agl = wo.height_agl(ds)
    keep = agl <= cap_agl_m
    if only_deficit_layer:
        _, _, integrand = _layer_weights(ds, ref, cap_agl_m)
        keep &= integrand > 0.0
    return -(np.where(keep, _density(ds) * wo.CP * tend * dz, 0.0)).sum(axis=0)


# --------------------------------------------------------------------------- #
# the error bar
# --------------------------------------------------------------------------- #
def two_datum(ref: SunsetProfile | float, delta_k: float = 0.5):
    """``(ref - delta_k, ref + delta_k)``: the two datums every fixed-reference number
    is reported at.  Works for a float or a :class:`SunsetProfile`."""
    if isinstance(ref, SunsetProfile):
        return ref.shifted(-delta_k), ref.shifted(+delta_k)
    return float(ref) - delta_k, float(ref) + delta_k


def at_two_datums(fn: Callable[[Any], Any], ref: SunsetProfile | float, *, delta_k: float = 0.5):
    """``(fn(ref - delta), fn(ref + delta))`` -- the LOW-datum result first, then the
    HIGH-datum result (not min/max of the two: a flux can change sign)."""
    lo, hi = two_datum(ref, delta_k)
    return fn(lo), fn(hi)


# --------------------------------------------------------------------------- #
# per-catchment budget terms at one time
# --------------------------------------------------------------------------- #
@dataclass
class CatchmentTerms:
    """One catchment (or box) at one output time.  Export is the sum over the
    catchment's lines of ``Phi = int F . n ds`` with the rightward normal walking
    a->b, so a line whose rightward normal points out of the catchment reports
    export as positive; a box walked clockwise reports net *import* as positive."""

    name: str
    n_cells: int
    area_m2: float
    production_w: float                 # P = sum(-HFX A), surface sensible cooling of the air
    hfx_mean_w_m2: float
    storage_j: float                    # H integrated over the catchment, at the datum
    export_w: float                     # Phi through the line(s), at the datum
    storage_lo_j: float                 # at ref - delta_k
    storage_hi_j: float                 # at ref + delta_k
    export_lo_w: float
    export_hi_w: float
    edges_w: dict[str, float]           # per-line Phi at the datum (for boxes)
    lw_production_w: float | None       # sum(P_LW A) when the tendency was written


def _lines_of(spec) -> list[Line]:
    if isinstance(spec, list):
        return list(spec)
    return [spec]


def catchment_budget_terms(
    ds,
    masks: dict[str, np.ndarray],
    lines: dict[str, Line | list[Line]],
    ref: SunsetProfile | float,
    *,
    cap_agl_m: float = 1500.0,
    delta_k: float = 0.5,
    area_m2: np.ndarray | None = None,
    exner_correct_hfx: bool = False,
) -> dict[str, CatchmentTerms]:
    """Production, storage and export per catchment at one output time.

    ``masks`` maps a name to a ``(ny, nx)`` bool mask on the WRF mass grid;
    ``lines`` maps the same names to one ``((lat_a, lon_a), (lat_b, lon_b))`` line or
    a list of them (a box's edges).  The three deficit fields (datum, datum - delta,
    datum + delta) are computed once and every transect reuses them.

    ``exner_correct_hfx`` multiplies HFX by ``(p0/psfc)^(R/cp)`` so the production is
    a theta-flux equivalent like H; off by default (a few percent at 850 hPa) to keep
    continuity with the ub-wx prototype that established the numbers.
    """
    area = np.asarray(area_m2) if area_m2 is not None else wo.grid_cell_area_m2(ds)
    if "HFX" in ds:
        hfx = wo.surface_field(ds, "HFX")
        if exner_correct_hfx:
            hfx = hfx * (wo.P0 / wo.surface_field(ds, "PSFC")) ** wo.RCP
    else:
        hfx = None
    at = deficit_fixed_fields(ds, ref, cap_agl_m=cap_agl_m)
    lo, hi = at_two_datums(lambda r: deficit_fixed_fields(ds, r, cap_agl_m=cap_agl_m), ref, delta_k=delta_k)
    lw = longwave_production_field(ds, ref, cap_agl_m=cap_agl_m)

    def export(fields, name):
        total, edges = 0.0, {}
        for k, (a, b) in enumerate(_lines_of(lines[name])):
            t = wo.integrate_flux_transect(ds, fields.flux_x_w_m, fields.flux_y_w_m,
                                           a[0], a[1], b[0], b[1], label=f"{name}:{k}")
            total += t.total_w
            edges[f"edge{k}"] = float(t.total_w)
        return float(total), edges

    out: dict[str, CatchmentTerms] = {}
    for name, m in masks.items():
        m = np.asarray(m, dtype=bool)
        if not m.any():
            continue
        e_at, edges = export(at, name) if name in lines else (float("nan"), {})
        e_lo = export(lo, name)[0] if name in lines else float("nan")
        e_hi = export(hi, name)[0] if name in lines else float("nan")
        out[name] = CatchmentTerms(
            name=name, n_cells=int(m.sum()), area_m2=float(area[m].sum()),
            production_w=float(np.sum(-hfx[m] * area[m])) if hfx is not None else float("nan"),
            hfx_mean_w_m2=float(hfx[m].mean()) if hfx is not None else float("nan"),
            storage_j=float(np.sum(at.heat_deficit_j_m2[m] * area[m])),
            export_w=e_at,
            storage_lo_j=float(np.sum(lo.heat_deficit_j_m2[m] * area[m])),
            storage_hi_j=float(np.sum(hi.heat_deficit_j_m2[m] * area[m])),
            export_lo_w=e_lo, export_hi_w=e_hi, edges_w=edges,
            lw_production_w=float(np.sum(lw[m] * area[m])) if lw is not None else None,
        )
    return out

"""Along-channel geometry: the long profile of a stream and the sections of its valley.

``long_profile`` walks a channel on the D8 graph (down to a stop mask, up the main stem
to the channel head) and returns distance, elevation, drainage area and the valley width
at chosen heights.  ``slab_sections`` gives each reach of a stem its cross-section as a
function of stage -- area, top width and wetted perimeter -- WITHOUT cutting a transect:
every cell near the stem is assigned to the stem cell its own flow path joins, the reach
("slab") is those cells, and area = flooded volume / reach length.  That is indifferent to
meanders, which is where perpendicular transects through a slot canyon go wrong.

numpy only (the D8 arrays come from ``d8``).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import d8
from .gates import channel_direction, valley_widths


@dataclass
class LongProfile:
    """A channel from downstream (index 0) to its head, with the crossing at ``i0``."""

    cells: np.ndarray                    # flat indices, downstream -> upstream
    dist_m: np.ndarray                   # along-channel distance from the reference cell (negative downstream)
    z_m: np.ndarray                      # elevation of the surface the profile was traced on
    acc_km2: np.ndarray
    i0: int                              # index of the reference cell
    widths_m: dict[float, np.ndarray] = field(default_factory=dict)   # height -> width (NaN where not sampled)

    @property
    def slope(self) -> np.ndarray:
        """Bed slope (positive where the channel falls downstream) on the profile's own spacing.
        ``dist_m`` increases upstream, so this is simply d(z)/d(dist)."""
        return np.gradient(self.z_m, self.dist_m)


def long_profile(zf: np.ndarray, grid, rcv: np.ndarray, acc: np.ndarray, cell: int, *, stop=None,
                 max_down_m: float = 150e3, head_km2: float = 5.0, heights=(), every_m: float = 450.0,
                 half_km: float = 4.0) -> LongProfile:
    """The channel through ``cell``: downstream until ``stop`` (a flat bool mask) or
    ``max_down_m``, upstream along the main stem while at least ``head_km2`` drains to it.
    ``heights`` (m above the thalweg) asks for the valley width every ``every_m`` along it."""
    nx = grid.nx
    step = d8.step_length(rcv, nx, grid.res)
    down = d8.trace_downstream(rcv, cell, stop=stop, max_steps=int(max_down_m / grid.res))
    up = d8.trace_upstream_main(rcv, acc, cell, nx, min_acc=head_km2 * 1e6 / grid.cell_area_m2)
    cells = np.concatenate([down[::-1], up[1:]])
    i0 = down.size - 1
    seg = step[cells[1:]].astype(np.float64)            # cells[k+1] is upstream of cells[k]: its step leads to cells[k]
    dist = np.concatenate([[0.0], np.cumsum(seg)])
    dist -= dist[i0]
    prof = LongProfile(cells=cells, dist_m=dist, z_m=zf.ravel()[cells].astype(np.float64),
                       acc_km2=acc[cells] * grid.cell_area_m2 / 1e6, i0=i0)
    if heights:
        every = max(int(round(every_m / grid.res)), 1)
        nstep = max(int(500 / grid.res), 3)
        ws = {float(h): np.full(cells.size, np.nan) for h in heights}
        for k in list(range(i0, -1, -every)) + list(range(i0 + every, cells.size, every)):
            direction, _, _ = channel_direction(rcv, acc, int(cells[k]), nx, nsteps=nstep)
            w, _ = valley_widths(zf, grid, int(cells[k]), direction, heights=tuple(heights), half_km=half_km)
            for h in heights:
                ws[float(h)][k] = w[float(h)]
        prof.widths_m = ws
    return prof


def gorge_index(width: np.ndarray, dist: np.ndarray, lo: float, hi: float) -> tuple[float, float, float]:
    """Narrowest width in the reach ``lo <= dist <= hi`` over the median width above it:
    small for a reservoir behind a throat, near one for a uniform conveyor.  Returns
    (index, narrowest width, its distance); NaN where the profile cannot say."""
    ok = np.isfinite(width)
    lower, upper = ok & (dist >= lo) & (dist <= hi), ok & (dist > hi)
    if not lower.any() or not upper.any():
        return float("nan"), float("nan"), float("nan")
    k = int(np.nanargmin(np.where(lower, width, np.nan)))
    return float(width[k] / np.nanmedian(width[upper])), float(width[k]), float(dist[k])


def sample_path(z: np.ndarray, grid, lat, lon) -> np.ndarray:
    """Elevations of another raster (any ``Grid``) under a path given as lat/lon vertices:
    how a model grid sees a channel traced on the true terrain."""
    j, i = grid.ji(lat, lon)
    ok = grid.inside(j, i)
    out = np.full(np.shape(j), np.nan)
    out[ok] = z[j[ok], i[ok]]
    return out


@dataclass
class SectionTable:
    """Cross-section of each reach of a stem as a function of stage (absolute elevation)."""

    s_m: np.ndarray            # (n_slab,) along-stem distance of the slab centres, upstream -> downstream
    length_m: np.ndarray       # (n_slab,) reach length
    bed_m: np.ndarray          # (n_slab,) lowest cell of the slab
    stages_m: np.ndarray       # (n_stage,)
    area_m2: np.ndarray        # (n_slab, n_stage) flooded volume / reach length
    top_m: np.ndarray          # (n_slab, n_stage) flooded plan area / reach length
    perimeter_m: np.ndarray    # (n_slab, n_stage) flooded terrain surface area / reach length


def slab_sections(z: np.ndarray, grid, rcv: np.ndarray, order: np.ndarray, starts: np.ndarray,
                  stem: np.ndarray, stages, *, slab_len_m: float = 500.0, max_reach_m: float = 2000.0) -> SectionTable:
    """Reach-averaged sections along ``stem`` (flat indices, upstream -> downstream).

    Each cell whose flow path joins the stem within ``max_reach_m`` (along its own path)
    belongs to the stem cell it joins; consecutive stem cells are grouped into slabs of
    about ``slab_len_m``.  For a pool surface at each stage the slab's flooded volume,
    plan area and terrain-surface area divided by its length are the section's area, top
    width and wetted perimeter.  ``max_reach_m`` keeps the interiors of side canyons --
    dead storage a current does not flow through -- out of the section.
    """
    nx = grid.nx
    stem = np.asarray(stem, dtype=np.int64)
    step = d8.step_length(rcv, nx, grid.res)
    lab, dist = d8.label_upstream(rcv, order, starts, stem, np.arange(stem.size, dtype=np.int32), step=step)
    on_stem = np.zeros(rcv.size, dtype=bool)
    on_stem[stem] = True
    use = (lab >= 0) & ((dist <= max_reach_m) | on_stem)
    seg = np.concatenate([step[stem[:-1]].astype(np.float64), [grid.res]])   # stem[k] -> stem[k+1]
    s_stem = np.concatenate([[0.0], np.cumsum(seg[:-1])])
    slab_of_stem = np.minimum((s_stem / slab_len_m).astype(np.int64), max(int(s_stem[-1] // slab_len_m), 0))
    n_slab = int(slab_of_stem.max()) + 1
    length = np.bincount(slab_of_stem, weights=seg, minlength=n_slab)
    s_mid = np.bincount(slab_of_stem, weights=s_stem * seg, minlength=n_slab) / np.maximum(length, 1e-9)
    idx = np.flatnonzero(use)
    slab = slab_of_stem[lab[idx]]
    zz = z.ravel()[idx].astype(np.float64)
    gy, gx = np.gradient(np.where(np.isnan(z), np.nanmean(z), z), grid.res, grid.res)
    stretch = np.sqrt(1.0 + gx.ravel()[idx] ** 2 + gy.ravel()[idx] ** 2)     # terrain area / plan area
    good = np.isfinite(zz)
    slab, zz, stretch = slab[good], zz[good], stretch[good]
    bed = np.full(n_slab, np.inf)
    np.minimum.at(bed, slab, zz)
    stages = np.atleast_1d(np.asarray(stages, dtype=np.float64))
    area = np.zeros((n_slab, stages.size))
    top = np.zeros_like(area)
    per = np.zeros_like(area)
    ca = grid.cell_area_m2
    for k, st in enumerate(stages):
        wet = zz < st
        area[:, k] = np.bincount(slab[wet], weights=(st - zz[wet]) * ca, minlength=n_slab) / length
        top[:, k] = np.bincount(slab[wet], minlength=n_slab) * ca / length
        per[:, k] = np.bincount(slab[wet], weights=stretch[wet] * ca, minlength=n_slab) / length
    return SectionTable(s_m=s_mid, length_m=length, bed_m=bed, stages_m=stages, area_m2=area, top_m=top, perimeter_m=per)

"""The basin floor at a rim height, the channels that cross into it, and what lies
behind each crossing.

The floor is defined hydrologically, not by elevation alone: the below-rim connected
component that contains the sink (Ouray for the Uinta Basin), restricted to cells
upstream of the outlet line and upstream of no cut line.  The cuts are where the floor
is open to a river corridor whose own basin the analysis grid cannot hold (the Green
above Split Mountain, the White east of Rangely); the corridor becomes a *port* rather
than a canyon.  Every knob is a caller argument -- rim height, sink, outlet, cuts,
channel threshold -- because they are analysis geometry, not facts about the place.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .d8 import label_upstream


def line_max_acc_cell(grid, acc: np.ndarray, line) -> int:
    """The cell of largest accumulation under a (lat0, lon0, lat1, lon1) line: where a
    river crosses it."""
    cells = grid.line_cells(*line)
    return int(cells[np.argmax(acc[cells])])


def point_max_acc_cell(grid, acc: np.ndarray, lat: float, lon: float, radius_m: float) -> int:
    """The cell of largest accumulation within ``radius_m`` of a point (flat index): the
    main channel at a named place, and -- since accumulation grows downstream -- its most
    downstream cell inside the radius.  ``acc`` may be flat or ``(ny, nx)``."""
    a = acc.reshape(grid.ny, grid.nx)
    j0, i0 = (int(v) for v in grid.ji(lat, lon))
    r = max(int(np.ceil(radius_m / grid.res)), 0)
    ja, jb = max(j0 - r, 0), min(j0 + r + 1, grid.ny)
    ia, ib = max(i0 - r, 0), min(i0 + r + 1, grid.nx)
    if ja >= jb or ia >= ib:
        raise ValueError(f"({lat}, {lon}) is outside the grid")
    jj, ii = np.mgrid[ja:jb, ia:ib]
    win = np.where((jj - j0) ** 2 + (ii - i0) ** 2 <= r * r, a[ja:jb, ia:ib], 0)
    k = int(np.argmax(win))
    return int((ja + k // (ib - ia)) * grid.nx + ia + k % (ib - ia))


def hydro_mask(rcv, order, starts, outlet_cell: int, cut_cells: dict[str, int]) -> np.ndarray:
    """Cells upstream of the outlet and of no cut, as a flat bool vector."""
    roots = np.array([outlet_cell] + list(cut_cells.values()), dtype=np.int32)
    lab = label_upstream(rcv, order, starts, roots, np.arange(roots.size, dtype=np.int32))
    return lab == 0


def basin_floor(zf: np.ndarray, rim_m: float, sink_ji, hydro: np.ndarray) -> np.ndarray:
    """Below-rim connected component containing the sink, within the hydrological mask."""
    from scipy import ndimage

    below = (zf < rim_m) & hydro.reshape(zf.shape)
    below[np.isnan(zf)] = False
    lab, _ = ndimage.label(below, structure=np.ones((3, 3), dtype=int))
    sink_lab = lab[tuple(int(v) for v in sink_ji)]
    if sink_lab == 0:
        raise RuntimeError("the sink cell is not below the rim, or outside the hydrological mask")
    return lab == sink_lab


def rim_crossings(floor: np.ndarray, rcv: np.ndarray) -> np.ndarray:
    """Flat indices of cells outside the floor whose receiver is inside it."""
    ff = floor.ravel()
    return np.flatnonzero(~ff & ff[rcv])


def elevation_bins(zf: np.ndarray, dz: float = 50.0) -> np.ndarray:
    lo = np.floor(np.nanmin(zf) / dz) * dz
    return np.arange(lo, np.nanmax(zf) + 2 * dz, dz)


@dataclass
class Hypsometry:
    """Per-label area, area per elevation bin, and terrain statistics."""

    area_m2: np.ndarray        # (nlab,)
    hyps_m2: np.ndarray        # (nlab, nbins-1) area per zbin
    zbins: np.ndarray          # (nbins,) bin edges, m
    z_mean_m: np.ndarray
    z_max_m: np.ndarray
    slope_mean_deg: np.ndarray
    steep_fraction: np.ndarray  # fraction of cells steeper than ``steep_deg``
    n_labels: int


def aggregate(lab: np.ndarray, nlab: int, cell_area: float, zf: np.ndarray, slope: np.ndarray,
              zbins: np.ndarray, *, steep_deg: float = 3.0) -> Hypsometry:
    """Area, hypsometry, mean/max elevation and slope statistics per label (``nlab`` may be
    0: a rim no channel crosses gives empty arrays)."""
    m = lab >= 0
    ll = lab[m]
    zz = zf.ravel()[m]
    ss = slope.ravel()[m]
    counts = np.maximum(np.bincount(ll, minlength=nlab), 1)
    area = np.bincount(ll, minlength=nlab) * cell_area
    zb = np.clip(np.digitize(zz, zbins) - 1, 0, len(zbins) - 2)
    nb = len(zbins) - 1
    hyps = np.bincount(ll * nb + zb, minlength=nlab * nb).reshape(nlab, nb) * cell_area     # not -1: nlab may be 0
    zmean = np.bincount(ll, weights=zz, minlength=nlab) / counts
    zmax = np.zeros(nlab, dtype=np.float32)
    np.maximum.at(zmax, ll, zz)
    smean = np.bincount(ll, weights=ss, minlength=nlab) / counts
    steep = np.bincount(ll, weights=(ss > steep_deg), minlength=nlab) / counts
    return Hypsometry(area_m2=area, hyps_m2=hyps, zbins=zbins, z_mean_m=zmean, z_max_m=zmax,
                      slope_mean_deg=smean, steep_fraction=steep, n_labels=nlab)


def flow_length(lab: np.ndarray, dist: np.ndarray, nlab: int) -> np.ndarray:
    """Longest along-flow distance to the root per label (m)."""
    out = np.zeros(nlab, dtype=np.float32)
    m = lab >= 0
    np.maximum.at(out, lab[m], dist[m])
    return out


def touches_edge_or_nodata(lab: np.ndarray, nlab: int, dem: np.ndarray, *, margin: int = 3) -> np.ndarray:
    """Per label: does the catchment reach the array edge or a nodata cell?  Such a
    catchment is truncated -- its real extent continues outside the grid."""
    from scipy import ndimage

    ny, nx = dem.shape
    edge = np.zeros((ny, nx), dtype=bool)
    edge |= ndimage.binary_dilation(np.isnan(dem), iterations=margin)
    edge[:margin, :] = edge[-margin:, :] = edge[:, :margin] = edge[:, -margin:] = True
    le = lab[edge.ravel()]
    le = le[le >= 0]
    return np.bincount(le, minlength=nlab) > 0


def floor_leak_fraction(lab: np.ndarray, floor: np.ndarray, nlab: int, cell_area: float,
                        area_m2: np.ndarray) -> np.ndarray:
    """Fraction of each label's area that lies on the floor -- a guard, not a filter.

    With the floor of ``basin_floor`` and the labels of ``d8.label_upstream`` on the same
    receivers it is identically zero: a floor cell's D8 path runs downhill, so it stays
    below the rim, upstream of the outlet and 8-connected to the floor -- inside the floor
    -- all the way to the outlet, and never passes a crossing, which lies outside it.  It
    is kept (and the pipeline still writes it) to catch a floor or labelling made some
    other way; a nonzero value means the two do not belong together."""
    lf = lab[floor.ravel()]
    return np.bincount(lf[lf >= 0], minlength=nlab) * cell_area / np.maximum(area_m2, cell_area)


def match_labels(lab_ref: np.ndarray, n_ref: int, lab_other: np.ndarray, n_other: int) -> dict[str, np.ndarray]:
    """Match catchments of one labelling to another on the SAME grid by overlap.

    ``lab_ref`` and ``lab_other`` are label rasters (or flat vectors) with -1 for "no
    catchment"; put a coarser labelling on the reference grid first with
    ``dem.regrid_nearest``.  For every reference label the best partner is the one sharing
    the most cells.  Returns, per reference label: ``partner`` (-1 if none), ``iou``
    (intersection over union), ``covered`` (fraction of the reference catchment inside
    its partner) and ``area_ratio`` (partner cells / reference cells).

    Counting how many mouths a coarse grid "finds" says little: two crossings a kilometre
    apart are one mouth or two depending on the rim contour.  Overlap says whether the
    catchment behind a known mouth still exists as one unit.
    """
    a, b = np.asarray(lab_ref).ravel(), np.asarray(lab_other).ravel()
    both = (a >= 0) & (b >= 0)
    pair = a[both].astype(np.int64) * n_other + b[both]
    cnt = np.bincount(pair, minlength=n_ref * n_other).reshape(n_ref, n_other)
    size_a = np.bincount(a[a >= 0], minlength=n_ref).astype(np.float64)
    size_b = np.bincount(b[b >= 0], minlength=n_other).astype(np.float64)
    partner = cnt.argmax(axis=1)
    inter = cnt[np.arange(n_ref), partner].astype(np.float64)
    union = size_a + size_b[partner] - inter
    none = inter == 0
    with np.errstate(divide="ignore", invalid="ignore"):
        out = {"partner": np.where(none, -1, partner).astype(np.int32),
               "iou": np.where(none, 0.0, inter / union),
               "covered": np.where(size_a > 0, inter / size_a, 0.0),
               "area_ratio": np.where(none | (size_a == 0), 0.0, size_b[partner] / size_a)}
    return out


def unique_names(primary, *qualifiers, fallback=None) -> list[str]:
    """Names that are unique, built from a preferred name and successive qualifiers.

    ``primary`` is the best name per item (e.g. the mapped stream at a mouth); each
    ``qualifiers`` sequence is tried in turn for the items whose name is still shared
    (e.g. the HUC12 unit, then the HUC10 unit): the qualifier is appended in brackets
    when it differs from the name and separates the group.  Whatever is still shared
    after that gets ``fallback`` (default: a running letter) appended.  An empty primary
    takes the first non-empty qualifier as its name.  Keying a join on a watershed-unit
    name silently merges every catchment inside the unit; key on IDs, and use this only
    for what a reader sees.
    """
    n = len(primary)
    names = []
    for k in range(n):
        nm = (primary[k] or "").strip()
        if not nm:
            nm = next(((q[k] or "").strip() for q in qualifiers if (q[k] or "").strip()), "")
        names.append(nm or "unnamed")

    def groups(vals):
        g = {}
        for k, v in enumerate(vals):
            g.setdefault(v, []).append(k)
        return [idx for idx in g.values() if len(idx) > 1]

    for q in qualifiers:
        for idx in groups(names):
            quals = [(q[k] or "").strip() for k in idx]
            if len(set(quals)) > 1:                       # the qualifier separates at least some of them
                for k, qq in zip(idx, quals):
                    if qq and qq != names[k]:
                        names[k] = f"{names[k]} [{qq}]"
    for idx in groups(names):
        for m, k in enumerate(idx):
            tag = fallback[k] if fallback is not None else chr(ord("a") + m) if m < 26 else str(m + 1)
            names[k] = f"{names[k]} ({tag})"
    return names


def slug(name: str) -> str:
    """A lookups.toml-style key: lower case, runs of other characters to one underscore."""
    out, prev = [], "_"
    for ch in name.lower():
        c = ch if ch.isalnum() else "_"
        if not (c == "_" and prev == "_"):
            out.append(c)
        prev = c
    return "".join(out).strip("_")


def area_above(hyps: np.ndarray, zbins: np.ndarray, z: float) -> np.ndarray:
    """Area (m2) per label in bins whose lower edge is at or above ``z``."""
    k = np.searchsorted(zbins, z, side="left")
    return hyps[:, k:].sum(axis=1)


def supply_curve(hyps: np.ndarray, zbins: np.ndarray, s_w_m2: float, *, step: int = 1):
    """Pool-control supply curve: ``(z, Phi(z))`` with ``Phi(z) = S * area above z`` in W,
    summed over the labels in ``hyps`` (pass one row for a single catchment)."""
    h = np.atleast_2d(hyps).sum(axis=0)
    zs = zbins[:-1:step]
    phi = np.array([s_w_m2 * h[k:].sum() for k in range(0, len(zbins) - 1, step)])
    return zs, phi

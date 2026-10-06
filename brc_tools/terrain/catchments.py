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
    """Area, hypsometry, mean/max elevation and slope statistics per label."""
    m = lab >= 0
    ll = lab[m]
    zz = zf.ravel()[m]
    ss = slope.ravel()[m]
    counts = np.maximum(np.bincount(ll, minlength=nlab), 1)
    area = np.bincount(ll, minlength=nlab) * cell_area
    zb = np.clip(np.digitize(zz, zbins) - 1, 0, len(zbins) - 2)
    hyps = np.bincount(ll * (len(zbins) - 1) + zb, minlength=nlab * (len(zbins) - 1)).reshape(nlab, -1) * cell_area
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
    """Fraction of each label's area that lies on the floor.  A rim crossing whose
    catchment contains floor cells is an outflow artefact of the floor's shape, not a
    canyon; callers drop labels above a small threshold (1 % in the ub-wx prototype)."""
    lf = lab[floor.ravel()]
    return np.bincount(lf[lf >= 0], minlength=nlab) * cell_area / np.maximum(area_m2, cell_area)


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

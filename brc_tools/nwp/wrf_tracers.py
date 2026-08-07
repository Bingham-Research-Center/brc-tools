"""Passive-tracer source attribution for a run seeded with ``tracer_opt``.

WRF's ``tracer_test1`` package (``tracer_opt = 2``) carries eight inert scalars
``tr17_1..tr17_8``.  Seeded over named source regions in ``wrfinput`` before
``wrf.exe``, they answer the one question no Eulerian field can: **where did this
air come from?**  A cold pool of a given depth and temperature can be built by
slope drainage, by a basin's own air merely being displaced, or by a long-fetch
inflow, and theta, wind and TKE look the same in all three.

The whole module is about the ratio, not the amount.  A tracer's absolute
concentration is a function of how large its source patch was and how long ago
the air left it, neither of which is interesting; what is interesting is the
*share* of the tagged air at a point that carries each tag, and how that share
changes with height.  Vertical separation of the shares is a stratified pool
built from several sources; vertical uniformity is one well-mixed layer.  Those
are different physical answers and they are visible in this normalisation and in
no other.

Nothing here knows what the sources *are*.  Region names are the case's
business and live in its config; this module deals in indices.
"""
from __future__ import annotations

import re

import numpy as np

from brc_tools.nwp import wrf_output as wo

__all__ = ["TRACER_RE", "tracer_variables", "tracer_stack", "tracer_shares",
           "dominant_source", "column_spectrum", "layer_shares",
           "DEFAULT_TOTAL_FLOOR"]

#: WRF names the ``tracer_test1`` scalars ``tr17_1`` .. ``tr17_8``.
TRACER_RE = re.compile(r"^tr17_(\d+)$")

#: Below this total tagged concentration a cell is reported as *untagged* rather
#: than attributed to whichever tracer happens to be largest.
#:
#: Necessary because the normalisation is a ratio: divide 1e-12 by 4e-12 and you
#: get a confident-looking 25% share of nothing.  Most of a domain is untagged
#: air (the tracers are seeded on a handful of source patches and the run is one
#: night long), so without a floor a dominant-source figure is an argmax over
#: numerical noise everywhere outside the plume -- which paints a crisp,
#: entirely spurious pattern.
#:
#: 1e-3 is a thousandth of the unit concentration the sources are seeded at.
DEFAULT_TOTAL_FLOOR = 1.0e-3


def tracer_variables(ds) -> list[str]:
    """The ``tr17_*`` variables present, ordered by their numeric suffix.

    Ordered numerically rather than lexically so ``tr17_10`` could never sort
    between ``tr17_1`` and ``tr17_2`` and silently permute the source labels a
    caller pairs with the stack.
    """
    found = [(int(m.group(1)), name) for name in ds.variables
             if (m := TRACER_RE.match(str(name)))]
    return [name for _, name in sorted(found)]


def tracer_stack(ds, names: list[str] | None = None) -> np.ndarray:
    """``(n_tracers, nz, ny, nx)`` of the tracer fields, clipped at zero.

    Advection undershoots produce small negative concentrations.  They are
    numerical, and a negative share is not a thing, so they are clipped here --
    once, at the read -- rather than in each consumer.
    """
    names = names if names is not None else tracer_variables(ds)
    if not names:
        raise KeyError("this run wrote no tr17_* tracers (tracer_opt unset, "
                       "or the seeding step was skipped)")
    return np.stack([np.maximum(np.asarray(wo._da(ds, n).values, dtype=float), 0.0)
                     for n in names])


def tracer_shares(stack, *, floor: float = DEFAULT_TOTAL_FLOOR
                  ) -> tuple[np.ndarray, np.ndarray]:
    """``(shares, total)`` -- each tracer's fraction of the tagged air, and the sum.

    ``shares`` sums to 1 along axis 0 wherever ``total`` clears ``floor`` and is
    NaN everywhere else, so an untagged cell propagates as missing data instead
    of as a fabricated attribution.
    """
    stack = np.asarray(stack, dtype=float)
    total = stack.sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        shares = stack / total
    return np.where(total >= float(floor), shares, np.nan), total


def dominant_source(stack, *, floor: float = DEFAULT_TOTAL_FLOOR
                    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """``(index, purity, total)`` of the largest contributor at every point.

    ``index`` is the 0-based tracer index, ``-1`` where the total is below
    ``floor``.  ``purity`` is that tracer's share, so it runs from ``1/n`` (an
    n-way tie -- the air is thoroughly mixed) to 1 (a single source), and is NaN
    below the floor.

    Both are needed to read the answer.  An index alone claims a source for air
    that is 13% one tracer and 12% another; the purity is what says the claim is
    worthless, and the renderer fades it out accordingly.
    """
    shares, total = tracer_shares(stack, floor=floor)
    valid = np.isfinite(shares).all(axis=0)
    # -1 in place of the NaNs before reducing, so both the argmax and the max run
    # on a finite array.  Reducing with nanmax instead would warn on every
    # all-NaN column, and an untagged region is usually most of a domain.
    filled = np.where(valid[None], shares, -1.0)
    index = np.where(valid, np.argmax(filled, axis=0), -1)
    purity = np.where(valid, np.max(filled, axis=0), np.nan)
    return index, purity, total


def column_spectrum(stack_col, height_col, *, floor: float = DEFAULT_TOTAL_FLOOR,
                    top_m: float | None = None) -> tuple[np.ndarray, np.ndarray]:
    """``(shares, height)`` for one column -- the tiramisu, level by level.

    ``stack_col`` is ``(n_tracers, nz)`` and ``height_col`` ``(nz,)``.  Returned
    on the model's own levels: this is exactly the profile the stacked-area
    renderer draws, and resampling it onto regular heights would smear the
    layer boundaries the figure exists to show.
    """
    shares, _total = tracer_shares(stack_col, floor=floor)
    height = np.asarray(height_col, dtype=float)
    if top_m is not None:
        keep = height <= float(top_m)
        return shares[:, keep], height[keep]
    return shares, height


def layer_shares(stack_col, height_col, bounds_m, *,
                 floor: float = DEFAULT_TOTAL_FLOOR) -> np.ndarray:
    """``(n_layers, n_tracers)`` shares, averaged over depth within each layer.

    ``bounds_m`` is a sequence of layer edges in the same units as
    ``height_col`` (e.g. ``[0, 100, 300, 1000]`` for three layers).  The average
    is **concentration-weighted, then normalised** rather than a mean of shares:
    a level holding almost no tagged air should not get an equal vote with the
    level holding the plume.
    """
    stack = np.asarray(stack_col, dtype=float)
    height = np.asarray(height_col, dtype=float)
    bounds = np.asarray(bounds_m, dtype=float)
    out = np.full((len(bounds) - 1, stack.shape[0]), np.nan)
    for i in range(len(bounds) - 1):
        sel = (height >= bounds[i]) & (height < bounds[i + 1])
        if not sel.any():
            continue
        summed = stack[:, sel].sum(axis=1)
        total = summed.sum()
        if total >= float(floor):
            out[i] = summed / total
    return out

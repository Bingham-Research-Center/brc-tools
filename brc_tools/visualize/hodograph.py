"""Hodograph rendering, height-coloured, with storm motions marked.

A hodograph is the figure that shows whether a low-level vortex could have been
storm-generated: the curvature and length of the low-level trace is the ambient
shear a storm has to work with.  Kept separate from the skew-T because a case
usually wants several hodographs (inflow, the point of interest, a station) beside
one sounding.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

__all__ = ["plot_hodograph"]

#: Height bands (m AGL) and their colours.  Boundaries are the layers the shear
#: and helicity products are quoted over, so the trace segments line up with the
#: numbers in an annotation rather than cutting across them.
_BANDS: tuple[tuple[float, float, str, str], ...] = (
    (0.0, 1000.0, "#d62728", "0-1 km"),
    (1000.0, 3000.0, "#ff7f0e", "1-3 km"),
    (3000.0, 6000.0, "#2ca02c", "3-6 km"),
    (6000.0, 9000.0, "#1f77b4", "6-9 km"),
)


def plot_hodograph(
    u_ms,
    v_ms,
    height_agl_m,
    out_path: str | Path,
    *,
    title: str,
    max_height_m: float = 9000.0,
    storm_motion: tuple[float, float] | None = None,
    storm_motion_label: str = "Bunkers right",
    observed_motion: tuple[float, float] | None = None,
    observed_motion_label: str = "observed",
    ring_interval_ms: float = 10.0,
    annotation: str | None = None,
    figsize: tuple[float, float] = (6.4, 6.4),
    dpi: int = 300,
) -> Path:
    """Draw a height-coloured hodograph and save it.

    Parameters
    ----------
    u_ms, v_ms, height_agl_m
        The profile, in m/s and metres above ground, ascending in height.
    storm_motion, observed_motion
        ``(u, v)`` in m/s.  Marking both is the point when a storm did not move
        the way a shear-derived estimate says it should: helicity is defined
        against the motion, so the two markers show how much of a quoted SRH is
        an assumption.
    ring_interval_ms
        Spacing of the speed rings.

    Uses the repo's Helvetica-first stack via
    :func:`brc_tools.visualize.style.use_publication_style`.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from brc_tools.visualize.style import use_publication_style

    use_publication_style(dpi=dpi)

    u = np.asarray(u_ms, dtype=float)
    v = np.asarray(v_ms, dtype=float)
    z = np.asarray(height_agl_m, dtype=float)
    if not (u.shape == v.shape == z.shape):
        raise ValueError(f"u, v and height must share a shape; got {u.shape}, {v.shape}, {z.shape}")

    keep = np.isfinite(u) & np.isfinite(v) & np.isfinite(z) & (z <= max_height_m)
    if keep.sum() < 2:
        raise ValueError("need at least two finite points below max_height_m to draw a hodograph")
    u, v, z = u[keep], v[keep], z[keep]

    fig, ax = plt.subplots(figsize=figsize)

    # Speed rings first, so the trace sits on top of them.
    reach = float(np.nanmax(np.hypot(u, v)))
    limit = ring_interval_ms * np.ceil((reach * 1.15) / ring_interval_ms)
    for r in np.arange(ring_interval_ms, limit + 0.1, ring_interval_ms):
        ax.add_patch(plt.Circle((0.0, 0.0), r, fill=False, color="0.85", lw=0.6, zorder=1))
        ax.annotate(
            f"{r:.0f}", (r, 0.0), fontsize=6, color="0.55",
            ha="left", va="bottom", zorder=2,
        )
    ax.axhline(0.0, color="0.85", lw=0.6, zorder=1)
    ax.axvline(0.0, color="0.85", lw=0.6, zorder=1)

    # The trace, one coloured segment per height band.
    for lo, hi, colour, label in _BANDS:
        if lo >= max_height_m:
            continue
        band = (z >= lo) & (z <= min(hi, max_height_m))
        if band.sum() < 2:
            continue
        # Extend one point past the top so the bands join without a visible gap.
        idx = np.flatnonzero(band)
        stop = min(idx[-1] + 2, u.size)
        ax.plot(u[idx[0]:stop], v[idx[0]:stop], color=colour, lw=2.0,
                label=label, solid_capstyle="round", zorder=3)

    ax.plot(u[0], v[0], "o", ms=5, mfc="white", mec="0.2", mew=1.0, zorder=4)

    if storm_motion is not None:
        ax.plot(*storm_motion, "X", ms=9, color="0.15", zorder=5, label=storm_motion_label)
    if observed_motion is not None:
        ax.plot(*observed_motion, "P", ms=9, color="#8e44ad", zorder=5,
                label=observed_motion_label)

    ax.set_xlim(-limit, limit)
    ax.set_ylim(-limit, limit)
    ax.set_aspect("equal")
    ax.set_xlabel(r"u (m s$^{-1}$)")
    ax.set_ylabel(r"v (m s$^{-1}$)")
    ax.set_title(title)
    ax.legend(loc="upper left", fontsize=7, frameon=False)
    if annotation:
        ax.text(0.99, 0.01, annotation, transform=ax.transAxes, ha="right", va="bottom",
                fontsize=6, alpha=0.65)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return out

"""Publication figure styling for WRF / NWP analysis.

A single source of truth for fonts, DPI, and — crucially — *fixed* colour ranges
per variable, so figures across cases, domains, and forecast hours stay directly
and fairly comparable.  Rendering modules read these styles; they do not hard-code
their own limits.

Like ``grid.py`` this module keeps ``matplotlib`` a lazy import: importing the
registry (``VAR_STYLES`` etc.) does not pull in matplotlib, only
``use_publication_style`` does.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np


@dataclass(frozen=True)
class VarStyle:
    """Fixed rendering choices for one variable, shared across every figure."""

    cmap: str
    label: str
    vmin: float | None = None
    vmax: float | None = None
    levels: tuple[float, ...] | None = None
    extend: str = "both"
    diverging: bool = False


# Fixed ranges tuned for a February Uinta Basin cold-air pool and validated
# against the pelican2013 runs.  NB the full-column potential temperature reaches
# ~479 K, so the ``theta`` range below is deliberately clipped to the
# meteorologically relevant low layer — sections/profiles must never autoscale.
VAR_STYLES: dict[str, VarStyle] = {
    "theta":          VarStyle("RdYlBu_r", r"$\theta$ (K)", 270.0, 300.0),
    "theta_2m":       VarStyle("RdYlBu_r", r"$\theta_{2\,\mathrm{m}}$ (K)", 270.0, 290.0),
    "temp_2m":        VarStyle("RdYlBu_r", r"$T_{2\,\mathrm{m}}$ (K)", 250.0, 285.0),
    "temp_2m_c":      VarStyle("RdYlBu_r", r"$T_{2\,\mathrm{m}}$ ($^{\circ}$C)", -25.0, 10.0),
    "wind_speed_10m": VarStyle("YlGnBu", r"10 m wind (m s$^{-1}$)", 0.0, 15.0, extend="max"),
    "wind_speed":     VarStyle("YlGnBu", r"wind speed (m s$^{-1}$)", 0.0, 15.0, extend="max"),
    # Forecast-funnel fills (fixed per level so a panel reads the same across cases):
    # the 250 hPa jet-stream core reaches ~70 m/s; 600 hPa specific humidity 0..6 g/kg.
    "wind_speed_250":  VarStyle("YlGnBu", r"250 hPa wind (m s$^{-1}$)", 0.0, 80.0, extend="max"),
    "spec_humidity_600": VarStyle("YlGn", r"600 hPa spec. humidity (g kg$^{-1}$)",
                                  0.0, 6.0, extend="max"),
    # Classic 500 hPa chart: absolute vorticity shaded (10^-5 s^-1).  Mid-latitude f is
    # ~9-11, so cyclonic shortwave maxima ride ~15-40; sequential warm ramp makes the
    # trough/vort-max stand out.
    "abs_vorticity_500": VarStyle("YlOrRd", r"500 hPa abs. vorticity ($10^{-5}$ s$^{-1}$)",
                                  0.0, 40.0, extend="max"),
    "snow_depth":     VarStyle("Blues", "snow depth (m)", 0.0, 0.5, extend="max"),
    "pblh":           VarStyle("YlOrRd", "PBLH (m)", 0.0, 1000.0, extend="max"),
    "tsk_minus_t2":   VarStyle("RdBu_r", r"$T_{\mathrm{skin}}-T_{2\,\mathrm{m}}$ (K)", -8.0, 8.0, diverging=True),
    "w":              VarStyle("RdBu_r", r"$w$ (m s$^{-1}$)", -0.5, 0.5, diverging=True),
    "theta_crest":    VarStyle("RdYlBu_r", r"$\theta$ (K)", 285.0, 300.0),
    "temp_adv":       VarStyle("RdBu_r", r"T adv (K h$^{-1}$)", -3.0, 3.0, diverging=True),
    # Air temperature on a mid-tropospheric pressure surface (default 600 hPa), for the
    # synoptic warm/cold-advection map.  Feb Uinta-Basin 600 hPa air is ~ -20..-2 degC.
    "temp_upper":     VarStyle("RdYlBu_r", r"$T$ ($^{\circ}$C)", -20.0, -2.0),
    # Cold-pool heat-deficit plan-view field (MJ m^-2).  Sequential, fixed 0..8 so the
    # spatial pool is directly comparable across cases and forecast hours; the pelican2013
    # control peaks near 8 MJ m^-2.
    "heat_deficit":   VarStyle("viridis", r"cold-pool heat deficit (MJ m$^{-2}$)", 0.0, 8.0, extend="max"),
    # Horizontal heat-deficit flux convergence -div(F) (deficitflux_div family). Symmetric,
    # fixed +-2 MJ m^-2 h^-1: the 111 m pelican2013 d04 run has hour-mean magnitudes
    # ~0.2-0.5 with smoothed local extremes near +-2.
    "deficit_advection": VarStyle("RdBu_r", r"horizontal $-\nabla_h\!\cdot F$ (MJ m$^{-2}$ h$^{-1}$)",
                                  -2.0, 2.0, diverging=True),
    "deficit_depth": VarStyle("cividis", "diagnosed layer depth (m AGL)",
                               0.0, 700.0, extend="max"),
    "deficit_speed": VarStyle("magma", r"deficit-weighted speed $|F|/H$ (m s$^{-1}$)",
                               0.0, 5.0, extend="max"),
    "deficit_froude": VarStyle("plasma", "exploratory bulk Froude proxy",
                                0.0, 2.0, extend="max"),
}

# Symmetric diverging limits for difference figures (case A minus case B).
DIFF_LIMITS: dict[str, float] = {  # GFS - NAM (initial-condition driven)
    "theta": 5.0,
    "temp_2m": 5.0,
    "wind_speed_10m": 4.0,
    "snow_depth": 0.2,
}
DIFF_LIMITS_FEEDBACK: dict[str, float] = {  # 2-way - 1-way (smaller signal)
    "theta": 3.0,
    "temp_2m": 3.0,
    "wind_speed_10m": 3.0,
}

# Helvetica-family first; fall back gracefully so nodes without the nice fonts
# still render (matplotlib picks the first available name).
_FONT_CHAIN = ["Nimbus Sans", "Arial", "Helvetica", "Liberation Sans", "DejaVu Sans"]


def use_publication_style(*, dpi: int = 300) -> None:
    """Apply publication rcParams (fonts, DPI, sizes).  Safe if fonts are absent."""
    import matplotlib

    existing = list(matplotlib.rcParams.get("font.sans-serif", []))
    fonts = list(dict.fromkeys(_FONT_CHAIN + existing))
    matplotlib.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": fonts,
            "mathtext.fontset": "stixsans",
            "axes.unicode_minus": True,
            "savefig.dpi": dpi,
            "figure.dpi": 150,
            "savefig.bbox": "tight",
            "savefig.pad_inches": 0.03,
            "pdf.fonttype": 42,  # editable text in vector output
            "ps.fonttype": 42,
            "font.size": 9.0,
            "axes.titlesize": 11.0,
            "axes.labelsize": 9.5,
            "xtick.labelsize": 8.0,
            "ytick.labelsize": 8.0,
            "legend.fontsize": 8.0,
            "legend.frameon": False,
            "figure.titlesize": 12.0,
            "axes.linewidth": 0.6,
            "xtick.direction": "out",
            "ytick.direction": "out",
            "image.cmap": "RdYlBu_r",
        }
    )


def get_style(var: str) -> VarStyle:
    """Return the fixed :class:`VarStyle` for a variable key (KeyError if unknown)."""
    return VAR_STYLES[var]


def resolve_style(
    var: str,
    *,
    overrides: dict[str, VarStyle] | None = None,
    autoscale: bool = False,
) -> VarStyle:
    """Resolve a variable's :class:`VarStyle`, honouring per-case overrides / autoscale.

    Fixed shared scales stay the default (so figures across cases/domains/hours remain
    directly comparable).  A case may opt into:

    * an explicit ``overrides[var]`` VarStyle (wins outright), or
    * ``autoscale=True`` — the returned style has ``vmin``/``vmax`` set to ``None``, so
      the renderers' existing data-driven path (:func:`shared_range`) fills them in.

    An override for ``var`` takes precedence over ``autoscale``.
    """
    if overrides and var in overrides:
        return overrides[var]
    base = get_style(var)
    if autoscale:
        return replace(base, vmin=None, vmax=None)
    return base


def diff_style(var: str, *, limit: float | None = None, feedback: bool = False) -> VarStyle:
    """Return a symmetric diverging style for a *difference* of ``var``."""
    base = VAR_STYLES.get(var)
    label = base.label if base is not None else var
    if limit is None:
        table = DIFF_LIMITS_FEEDBACK if feedback else DIFF_LIMITS
        limit = table.get(var, 5.0)
    lim = abs(limit)
    return VarStyle(
        cmap="RdBu_r",
        label=rf"$\Delta$ {label}",
        vmin=-lim,
        vmax=lim,
        diverging=True,
    )


def shared_range(*arrays, pct: tuple[float, float] = (1.0, 99.0)) -> tuple[float, float]:
    """Robust ``(vmin, vmax)`` across several arrays for a fair shared colorbar."""
    parts = [np.asarray(a, dtype=float).ravel() for a in arrays if a is not None]
    if not parts:
        return (0.0, 1.0)
    finite = np.concatenate(parts)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return (0.0, 1.0)
    lo, hi = (float(x) for x in np.percentile(finite, pct))
    if lo == hi:
        hi = lo + 1.0
    return (lo, hi)


def symmetric_limit(*arrays, cap: float | None = None) -> float:
    """Symmetric magnitude (for a diverging difference) from the robust 99th pct."""
    parts = [np.asarray(a, dtype=float).ravel() for a in arrays if a is not None]
    if not parts:
        return 1.0
    finite = np.concatenate(parts)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return 1.0
    mag = float(np.percentile(np.abs(finite), 99.0))
    if mag <= 0:
        mag = float(np.nanmax(np.abs(finite))) or 1.0
    if cap is not None:
        mag = min(mag, cap)
    return mag

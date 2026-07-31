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
    #: Accepted from a pelican case TOML (``wrf_figures._varstyle_from_dict``) and
    #: **read by nothing** -- no renderer builds a BoundaryNorm from it.  Kept
    #: because that constructor passes it unconditionally, so dropping the field
    #: would raise on any study style override; do not reach for it expecting
    #: discrete bands.  ``gamma`` below is the norm that is actually wired.
    levels: tuple[float, ...] | None = None
    extend: str = "both"
    diverging: bool = False
    #: Exponent for a :class:`~matplotlib.colors.PowerNorm` ramp between ``vmin``
    #: and ``vmax``.  ``None`` (the default) is the ordinary linear scale, so an
    #: entry that does not set it renders exactly as it always has.  ``gamma < 1``
    #: spends more of the colour range on low values -- the right shape for a
    #: field whose interesting signal sits just above its floor while rare cores
    #: run an order of magnitude higher.  See :func:`build_norm`.
    gamma: float | None = None


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
    # --- Cross-section wind components -----------------------------------------
    # Three different quantities that a curtain could shade, and the labels say
    # which, because they are not interchangeable and the figure is the only place
    # a reader can find out. `wind_speed_10m` covers the fourth (bare magnitude).
    #
    # The normal component is the one that needs a diverging map: it is signed by
    # construction, and a sequential ramp would render flow into the page and flow
    # out of it as the same colour. Positive is INTO THE PAGE -- for a west-to-east
    # transect that is the northerly (+v) component. See wrf_section.section_from_plane.
    "wind_normal":    VarStyle("RdBu_r",
                                r"section-normal wind (m s$^{-1}$, $+$ into page)",
                                -10.0, 10.0, diverging=True),
    "wind_along":     VarStyle("RdBu_r",
                                r"along-transect wind (m s$^{-1}$, $+$ toward B)",
                                -15.0, 15.0, diverging=True),
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
    # --- Convective diagnostics ------------------------------------------------
    # Limits set from MEASURED values on the 20251011 Ashley 600 m run and its
    # gate-A0 HRRR table, not from Plains intuition: Basin CAPE and shear ranges
    # are far narrower than a Great Plains default, and a scale that tops out at
    # 4000 J/kg renders an 800 J/kg environment as uniformly blank.
    #
    # Reflectivity keeps the 5 dBZ floor of operational products, so clear air
    # stays unpainted, and runs to 75 dBZ because this run's domain maximum
    # reached 70.6 dBZ. NB that exceeds HRRR's own 52-59 dBZ for the same event
    # and is a known mp_physics = 38 hail-core signature -- a thing to validate,
    # not a result, and a reason to compare on beam surfaces not column maxima.
    "refl_comp":      VarStyle("gist_ncar", r"composite reflectivity (dBZ)",
                                5.0, 75.0, extend="max"),
    "refl":           VarStyle("gist_ncar", r"reflectivity (dBZ)",
                                5.0, 75.0, extend="max"),
    # REFD_MAX, not REFD_COM: the maximum over the interval since the last
    # history write, so it is a swath rather than a snapshot. Same scale as
    # refl_comp on purpose -- the two are meant to be read side by side -- but a
    # separate key so the label cannot claim the wrong surface.
    "refl_comp_max":  VarStyle("gist_ncar",
                                r"max composite reflectivity, output interval (dBZ)",
                                5.0, 75.0, extend="max"),
    "refl_beam":      VarStyle("gist_ncar", r"reflectivity on beam surface (dBZ)",
                                5.0, 75.0, extend="max"),
    "echo_top":       VarStyle("viridis", r"echo top (km MSL)", 2.0, 14.0, extend="max"),
    # Updraft helicity, on a floor-to-core scale rather than a linear one.
    #
    # Three choices, none of them cosmetic. The floor is 5 because UH is near zero
    # over most of any domain and a linear ramp from 0 paints all of it a pale red
    # that reads as weak signal -- the same failure the reflectivity floor exists
    # to prevent. Below 5 is masked (see wrf_convective.MASK_AT_OR_BELOW), so clear
    # air stays unpainted. The top is 50 because the 600 m nest resolves cores an
    # order of magnitude above the ~19.5 m2 s-2 the 3 km gate-A0 HRRR table peaked
    # at, and a scale ending near that peak saturates on every real updraft.
    #
    # gamma = 0.6 is what makes the pair work: a linear 5-50 scale would spend
    # most of its colour on values a Basin storm rarely reaches and leave the
    # 5-20 band -- where the mesocyclone signal actually lives -- crushed into
    # two shades. The ramp is slow at the bottom and coarse at the top.
    "uphel_2to5km":   VarStyle("Reds", r"2-5 km updraft helicity (m$^2$ s$^{-2}$)",
                                5.0, 50.0, extend="max", gamma=0.6),
    "uphel_0to3km":   VarStyle("Reds", r"0-3 km updraft helicity (m$^2$ s$^{-2}$)",
                                5.0, 50.0, extend="max", gamma=0.6),
    # Vertical vorticity, diverging about zero: the landspout test is whether a
    # cyclonic shear line exists on the floor BEFORE the updraft arrives, so
    # anticyclonic values must stay legible rather than being clipped away.
    # Storm cores reach +-20e-3 s-1 on this run, but a boundary shear line is
    # 1-5e-3, so the range is deliberately set for the BOUNDARY and lets the core
    # saturate -- extend="both" says so on the bar. Widening to +-20 to fit the
    # core would render the feature the landspout test is about as blank.
    "vert_vorticity": VarStyle("RdBu_r", r"$\zeta$ ($10^{-3}$ s$^{-1}$)",
                                -10.0, 10.0, diverging=True),
    # 0-3 km SRH 400-824 m2 s-2 at gate A0; 0-1 km is a fraction of that.
    "srh_0to3km":     VarStyle("YlOrRd", r"0-3 km SRH (m$^2$ s$^{-2}$)",
                                0.0, 900.0, extend="max"),
    "srh_0to1km":     VarStyle("YlOrRd", r"0-1 km SRH (m$^2$ s$^{-2}$)",
                                0.0, 400.0, extend="max"),
    # MLCAPE 580-980 J/kg, MLCIN -100..-305 across the six gate-A0 cycles.
    # High-shear / low-CAPE is the regime, so these are deliberately tight.
    "cape_ml":        VarStyle("YlOrRd", r"MLCAPE (J kg$^{-1}$)", 0.0, 1200.0, extend="max"),
    "cape_mu":        VarStyle("YlOrRd", r"MUCAPE (J kg$^{-1}$)", 0.0, 1500.0, extend="max"),
    "cin_ml":         VarStyle("Purples_r", r"MLCIN (J kg$^{-1}$)", -400.0, 0.0, extend="min"),
    # Bulk shear: 0-6 km in a high-shear regime; 0-1 km scaled for the low layer.
    "shear_mag_0to6km": VarStyle("BuPu", r"0-6 km bulk shear (m s$^{-1}$)",
                                  0.0, 35.0, extend="max"),
    "shear_mag_0to1km": VarStyle("BuPu", r"0-1 km bulk shear (m s$^{-1}$)",
                                  0.0, 20.0, extend="max"),
    # 10 m wind maxima ran 15.9 -> 33.9 m/s domain-wide. This is the scale the
    # swath-width test is read on, so it must not saturate at the 15 m/s the
    # winter wind_speed_10m style uses.
    "wspd10max":      VarStyle("YlOrRd", r"max 10 m wind (m s$^{-1}$)",
                                0.0, 35.0, extend="max"),
    "hail_max":       VarStyle("PuBu", r"max hail diameter (mm)", 0.0, 50.0, extend="max"),
    "tornado_mask":   VarStyle("Greys", "AFWA tornado mask", 0.0, 1.0, extend="neither"),
    "llws":           VarStyle("YlGnBu", r"0-2 km low-level wind shear (m s$^{-1}$)",
                                0.0, 25.0, extend="max"),
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


def build_norm(st: VarStyle):
    """A :class:`~matplotlib.colors.Normalize` for ``st``, or ``None`` if linear.

    Returns ``None`` unless the style sets ``gamma``, so every existing variable
    keeps passing plain ``vmin``/``vmax`` and renders unchanged.

    Callers must pass the result as ``norm=`` **instead of** ``vmin``/``vmax``:
    matplotlib raises if given both.  :func:`norm_kwargs` does that bookkeeping.
    """
    if st.gamma is None:
        return None
    from matplotlib.colors import PowerNorm

    return PowerNorm(float(st.gamma), vmin=st.vmin, vmax=st.vmax)


def norm_kwargs(st: VarStyle) -> dict:
    """The colour-limit kwargs for a mappable: either ``norm`` or ``vmin``/``vmax``.

    One helper because the choice is exclusive and getting it wrong is a
    ``ValueError`` at render time, inside a per-figure try/except, on a compute
    node -- i.e. a figure silently missing from a sweep.
    """
    norm = build_norm(st)
    if norm is not None:
        return {"norm": norm}
    return {"vmin": st.vmin, "vmax": st.vmax}


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

"""Vertical profiles and skew-T for WRF-vs-sounding comparison.

Two figures:
  * ``plot_theta_profiles`` — potential-temperature profiles for several runs
    overlaid (the cold-pool structure comparison; needs no external obs).
  * ``plot_skewt`` — a MetPy skew-T of a model column, optionally over an observed
    sounding.

Observations are pluggable via the small :class:`SoundingSource` protocol:
model column, Wyoming archive (live or cached), and a clearly-marked placeholder
for in-basin UBWOS-2013 radiosondes the user will supply later.  Only the 12Z
time is an operational launch, so obs comparison is chiefly an initial-condition
check (which is exactly the GFS-vs-NAM IC question).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

import numpy as np


@dataclass
class Sounding:
    """A vertical sounding in plain units (hPa, m, deg C, knots).

    ``height_m`` is geopotential height (m MSL); it is optional because the skew-T
    works in pressure coordinates, but the theta(z) profile plot needs it (model
    columns and both RAOB archives supply it; a cache written before the schema
    gained the column leaves it ``None``, and the plot reconstructs hydrostatically).
    """

    pressure_hpa: np.ndarray
    temperature_c: np.ndarray
    dewpoint_c: np.ndarray
    u_kt: np.ndarray | None
    v_kt: np.ndarray | None
    source: str
    station: str
    valid_time: datetime | None = None
    height_m: np.ndarray | None = None


class SoundingSource(Protocol):
    """Anything that can return a :class:`Sounding` for a station and time."""

    def get(self, station: str, valid_time: datetime) -> Sounding | None: ...


def sounding_from_column(col, *, source: str = "WRF", station: str = "",
                         valid_time: datetime | None = None) -> Sounding:
    """Build a :class:`Sounding` from a ``wrf_output.WRFColumn``."""
    return Sounding(
        pressure_hpa=np.asarray(col.pressure_hpa),
        temperature_c=np.asarray(col.temperature_c),
        dewpoint_c=np.asarray(col.dewpoint_c),
        u_kt=None if col.u_kt is None else np.asarray(col.u_kt),
        v_kt=None if col.v_kt is None else np.asarray(col.v_kt),
        source=source,
        station=station,
        valid_time=valid_time,
        height_m=np.asarray(col.height_asl),
    )


class ModelColumnSounding:
    """Sounding source backed by a WRF column at a given lat/lon."""

    def __init__(self, ds, lat: float, lon: float, *, label: str = "WRF"):
        self._ds = ds
        self._lat = lat
        self._lon = lon
        self._label = label

    def get(self, station: str, valid_time: datetime) -> Sounding:
        from brc_tools.nwp.wrf_output import extract_column

        col = extract_column(self._ds, self._lat, self._lon, label=station)
        return sounding_from_column(col, source=self._label, station=station, valid_time=valid_time)


class LiveSounding:
    """Live sounding source via :mod:`brc_tools.api.soundings` (needs network).

    ``provider`` is ``"auto"`` (IGRA2 then Wyoming), ``"igra2"``, or ``"wyoming"``.
    The api layer owns the fetch + provider normalisation; this just wraps the
    canonical frame in a :class:`Sounding`.
    """

    def __init__(self, provider: str = "auto"):
        self._provider = provider

    def get(self, station: str, valid_time: datetime) -> Sounding | None:
        from brc_tools.api.soundings import fetch_sounding

        df = fetch_sounding(station, valid_time, provider=self._provider)
        if df is None or df.height == 0:
            return None
        return Sounding(
            pressure_hpa=df["pressure_hpa"].to_numpy(),
            temperature_c=df["temperature_c"].to_numpy(),
            dewpoint_c=df["dewpoint_c"].to_numpy(),
            u_kt=df["u_kt"].to_numpy(),
            v_kt=df["v_kt"].to_numpy(),
            source="RAOB",
            station=station,
            valid_time=valid_time,
            height_m=df["height_m"].to_numpy() if "height_m" in df.columns else None,
        )


class WyomingSounding(LiveSounding):
    """Back-compat alias: the Univ. Wyoming live source, now via the api layer."""

    def __init__(self):
        super().__init__(provider="wyoming")


class CachedWyomingSounding:
    """Offline sounding source reading a parquet cache from ``fetch_soundings.py``."""

    def __init__(self, cache_path: str | Path):
        import polars as pl

        self._df = pl.read_parquet(cache_path)

    def get(self, station: str, valid_time: datetime) -> Sounding | None:
        import polars as pl

        sub = self._df.filter(
            (pl.col("station") == station) & (pl.col("valid_time") == valid_time)
        ).sort("pressure_hpa", descending=True)
        if sub.height == 0:
            return None
        return Sounding(
            pressure_hpa=sub["pressure_hpa"].to_numpy(),
            temperature_c=sub["temperature_c"].to_numpy(),
            dewpoint_c=sub["dewpoint_c"].to_numpy(),
            u_kt=sub["u_kt"].to_numpy() if "u_kt" in sub.columns else None,
            v_kt=sub["v_kt"].to_numpy() if "v_kt" in sub.columns else None,
            source="RAOB",
            station=station,
            valid_time=valid_time,
            height_m=sub["height_m"].to_numpy() if "height_m" in sub.columns else None,
        )


# Generalised name -- the parquet cache is provider-agnostic (IGRA2 or Wyoming).
CachedSounding = CachedWyomingSounding


class PlaceholderFileSounding:
    """Hook for in-basin UBWOS-2013 (Ouray/Horsepool) soundings — user supplies data."""

    def get(self, station: str, valid_time: datetime) -> Sounding:
        raise NotImplementedError(
            "UBWOS-2013 in-basin sounding hook: supply an Ouray/Horsepool radiosonde "
            "file + parser, or convert it to the fetch_soundings parquet schema and use "
            "CachedWyomingSounding."
        )


def plot_theta_profiles(
    columns: dict[str, object],
    out_path: str | Path,
    *,
    terrain_m: float | None = None,
    crest_m: float | None = None,
    y_max_m: float | None = None,
    title: str,
    annotation: str | None = None,
    figsize: tuple[float, float] = (5.0, 7.0),
    dpi: int = 300,
) -> Path:
    """Overlay potential-temperature profiles ``theta(z)`` for several runs."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from brc_tools.visualize.timeseries import DEFAULT_RUN_STYLES

    out = Path(out_path)
    fig, ax = plt.subplots(figsize=figsize, constrained_layout=True)
    for i, (label, col) in enumerate(columns.items()):
        line_style = dict(DEFAULT_RUN_STYLES.get(i, {}))
        ax.plot(np.asarray(col.theta), np.asarray(col.height_asl), label=label, **line_style)

    if terrain_m is not None:
        ax.set_ylim(bottom=terrain_m - 100.0)
    if y_max_m is not None:
        ax.set_ylim(top=y_max_m)

    # Focus the x-axis on the plotted layer; the deep, warm column aloft
    # (theta -> ~480 K near the model top) would otherwise blow up the scale.
    top = y_max_m if y_max_m is not None else np.inf
    visible = [np.asarray(c.theta)[np.asarray(c.height_asl) <= top] for c in columns.values()]
    visible = np.concatenate([v for v in visible if v.size]) if visible else np.array([])
    if visible.size:
        ax.set_xlim(float(np.nanmin(visible)) - 1.0, float(np.nanmax(visible)) + 2.0)

    if terrain_m is not None:
        ax.axhline(terrain_m, color="0.4", lw=0.8, ls=":")
        ax.fill_between(ax.get_xlim(), terrain_m - 100.0, terrain_m, color="0.7", alpha=0.6, zorder=0)
    if crest_m is not None:
        ax.axhline(crest_m, color="k", lw=0.7, ls="--")
        ax.text(ax.get_xlim()[1], crest_m, " crest", fontsize=7, va="bottom", ha="right")

    ax.set_xlabel(r"potential temperature $\theta$ (K)")
    ax.set_ylabel("height (m MSL)")
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.legend()
    if annotation:
        ax.text(0.99, 0.01, annotation, transform=ax.transAxes, ha="right", va="bottom",
                fontsize=6, alpha=0.65)

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi)
    plt.close(fig)
    return out


def plot_skewt(
    model: Sounding,
    out_path: str | Path,
    *,
    obs: Sounding | None = None,
    title: str,
    annotation: str | None = None,
    figsize: tuple[float, float] = (7.0, 8.0),
    dpi: int = 300,
) -> Path:
    """Render a MetPy skew-T of a model sounding, optionally over an observed one."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from metpy.plots import SkewT
    from metpy.units import units

    out = Path(out_path)
    fig = plt.figure(figsize=figsize)
    skew = SkewT(fig, rotation=45)

    p = model.pressure_hpa * units.hPa
    skew.plot(p, model.temperature_c * units.degC, "tab:red", lw=1.6, label=f"{model.source} T")
    skew.plot(p, model.dewpoint_c * units.degC, "tab:green", lw=1.6, label=f"{model.source} Td")
    if model.u_kt is not None and model.v_kt is not None:
        idx = slice(None, None, max(1, len(model.pressure_hpa) // 30))
        skew.plot_barbs(p[idx], (model.u_kt * units.knots)[idx], (model.v_kt * units.knots)[idx])

    if obs is not None:
        po = obs.pressure_hpa * units.hPa
        skew.plot(po, obs.temperature_c * units.degC, "k", lw=1.4, ls="--", label=f"{obs.source} T")
        skew.plot(po, obs.dewpoint_c * units.degC, "0.4", lw=1.4, ls="--", label=f"{obs.source} Td")

    skew.plot_dry_adiabats(alpha=0.25, lw=0.6)
    skew.plot_moist_adiabats(alpha=0.2, lw=0.6)
    skew.plot_mixing_lines(alpha=0.2, lw=0.6)
    skew.ax.set_ylim(1000, 500)  # basin floor ~850 hPa up to mid-troposphere
    skew.ax.set_xlim(-40, 20)
    skew.ax.set_xlabel(r"temperature ($^{\circ}$C)")
    skew.ax.set_ylabel("pressure (hPa)")
    skew.ax.set_title(title)
    skew.ax.legend(loc="upper right", fontsize=8)
    if annotation:
        skew.ax.text(0.99, 0.01, annotation, transform=skew.ax.transAxes, ha="right",
                     va="bottom", fontsize=6, alpha=0.65)

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return out


# --------------------------------------------------------------------------- #
# theta(z) profile with wind + stability (skew-T alternative)
# --------------------------------------------------------------------------- #
_KAPPA = 0.2854      # R_d / c_p
_RD = 287.05         # J kg-1 K-1
_G = 9.80665         # m s-2


def _theta_k(snd: Sounding) -> np.ndarray:
    """Potential temperature (K) from a sounding's T (deg C) and p (hPa)."""
    t = np.asarray(snd.temperature_c, float) + 273.15
    p = np.asarray(snd.pressure_hpa, float)
    return t * (1000.0 / p) ** _KAPPA


def _hydrostatic_height(p_hpa: np.ndarray, t_c: np.ndarray, z0: float) -> np.ndarray:
    """Geopotential height (m) from p (hPa, surface->top) and T (deg C), anchored at ``z0``.

    Fallback for a sounding whose reported height is missing (e.g. a cache written
    before the schema carried ``height_m``); integrates the hypsometric equation.
    """
    p = np.asarray(p_hpa, float) * 100.0
    tk = np.asarray(t_c, float) + 273.15
    z = np.empty_like(p)
    z[0] = z0
    for k in range(1, len(p)):
        tbar = 0.5 * (tk[k] + tk[k - 1])
        z[k] = z[k - 1] + (_RD * tbar / _G) * np.log(p[k - 1] / p[k])
    return z


def _heights(snd: Sounding, z0_fallback: float) -> np.ndarray:
    """Sounding geopotential heights (m), reconstructed hydrostatically if absent."""
    if snd.height_m is not None and np.isfinite(np.asarray(snd.height_m, float)).any():
        return np.asarray(snd.height_m, float)
    return _hydrostatic_height(snd.pressure_hpa, snd.temperature_c, z0_fallback)


def _smooth(a: np.ndarray, w: int = 5) -> np.ndarray:
    """Centred running mean (odd window), edge-padded — de-noises the dθ/dz banding."""
    a = np.asarray(a, float)
    if a.size < w:
        return a
    k = np.ones(w) / w
    return np.convolve(np.pad(a, w // 2, mode="edge"), k, mode="valid")


def _stability_bands(z, theta, z_top, *, min_thick=80.0, merge_gap=120.0):
    """Contiguous ``(z0, z1, kind)`` bands from a *smoothed* profile's local dθ/dz.

    ``kind`` in {'inversion','unstable'}; stable/neutral layers are left unshaded.
    Thresholds (K/km): inversion >= 5, unstable <= -0.5.  Thin bands (< ``min_thick`` m)
    are dropped and same-kind bands within ``merge_gap`` m are merged, so the shading
    marks layers rather than every level-to-level flicker.
    """
    z = np.asarray(z, float)
    th = _smooth(np.asarray(theta, float))
    dthdz = np.diff(th) / np.maximum(np.diff(z), 1.0) * 1000.0  # K/km
    kind = np.where(dthdz >= 5.0, "inversion", np.where(dthdz <= -0.5, "unstable", ""))
    raw: list[tuple[float, float, str]] = []
    for k, zk, z1 in zip(kind, z[:-1], z[1:]):
        if not k or zk > z_top:
            continue
        z1 = min(float(z1), z_top)
        if raw and raw[-1][2] == k and zk - raw[-1][1] <= merge_gap:
            raw[-1] = (raw[-1][0], z1, k)
        else:
            raw.append((float(zk), z1, k))
    return [b for b in raw if b[1] - b[0] >= min_thick]


def _profile_barbs(ax, x, z, u, v, z_top, color):
    z, u, v = np.asarray(z, float), np.asarray(u, float), np.asarray(v, float)
    m = np.isfinite(z) & np.isfinite(u) & np.isfinite(v) & (z <= z_top)
    z, u, v = z[m], u[m], v[m]
    if z.size == 0:
        return
    targets = np.linspace(z.min(), z.max(), 14)
    idx = np.unique([int(np.abs(z - t).argmin()) for t in targets])
    ax.barbs(np.full(idx.size, x), z[idx], u[idx], v[idx],
             length=6, color=color, linewidth=0.7, zorder=5)


def plot_theta_wind_profile(
    models: dict[str, Sounding],
    out_path: str | Path,
    *,
    obs: Sounding | None = None,
    title: str,
    crest_m: float | None = None,
    y_top_m: float = 5500.0,
    annotation: str | None = None,
    figsize: tuple[float, float] = (8.2, 8.0),
    dpi: int = 300,
) -> Path:
    """Potential-temperature-with-height profile (a skew-T alternative).

    Overlays one or more model columns (``models`` maps a short label -> Sounding,
    e.g. the spin-up hours ``{"12Z": .., "13Z": ..}``) and an optional observed
    radiosonde on a θ(x)-vs-height(y) plot, with a wind-barb side panel and shaded,
    labelled static-stability bands (dotted verticals are dry adiabats = neutral;
    a curve tilting right with height is statically stable).  All winds are knots.

    The first model in ``models`` is the reference for the stability shading and the
    change-shading (filled between the first and last model curve).
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch

    from brc_tools.visualize.timeseries import DEFAULT_RUN_STYLES

    if not models:
        raise ValueError("plot_theta_wind_profile needs at least one model sounding")

    out = Path(out_path)
    labels = list(models)
    z0 = min(float(_heights(m, 0.0)[0]) for m in models.values())
    m_z = {lab: _heights(snd, z0) for lab, snd in models.items()}
    m_th = {lab: _theta_k(snd) for lab, snd in models.items()}
    primary = labels[0]

    # Manual layout (not constrained_layout): the narrow wind panel can collapse it
    # under the larger publication fonts, and with savefig bbox='tight' that blows the
    # figure width up — a fixed margin is robust.
    fig, (ax, axw) = plt.subplots(
        1, 2, figsize=figsize, sharey=True,
        gridspec_kw=dict(width_ratios=[4.2, 1.0]),
    )
    fig.subplots_adjust(left=0.09, right=0.985, top=0.90, bottom=0.075, wspace=0.06)

    band_c = {"inversion": "#d1495b", "unstable": "#4b8bbe"}
    for zb0, zb1, kind in _stability_bands(m_z[primary], m_th[primary], y_top_m):
        ax.axhspan(zb0, zb1, color=band_c[kind], alpha=0.10, zorder=0, lw=0)
    for th in np.arange(260, 360, 5):
        ax.axvline(th, color="0.6", ls=":", lw=0.6, zorder=1)

    for i, lab in enumerate(labels):
        st = DEFAULT_RUN_STYLES.get(i, {"color": "black", "ls": "-", "lw": 1.8})
        ax.plot(m_th[lab], m_z[lab], color=st["color"], ls=st.get("ls", "-"),
                lw=2.0, marker="o", ms=2.5, label=f"WRF {lab}", zorder=4)
    if len(labels) >= 2:
        zc = np.linspace(z0, y_top_m, 120)
        a = np.interp(zc, m_z[labels[0]], m_th[labels[0]])
        b = np.interp(zc, m_z[labels[-1]], m_th[labels[-1]])
        ax.fill_betweenx(zc, a, b, color="0.55", alpha=0.18, zorder=2,
                         label=f"{labels[0]}→{labels[-1]} change")
    if obs is not None:
        oz, oth = _heights(obs, z0), _theta_k(obs)
        obs_lab = f"RAOB obs {obs.valid_time:%H}Z" if obs.valid_time else "RAOB (obs)"
        ax.plot(oth, oz, color="k", lw=1.6, marker="D", ms=3.5, mfc="white",
                label=obs_lab, zorder=4)
    if crest_m is not None:
        ax.axhline(crest_m, color="k", lw=0.7, ls="--", zorder=1)
        ax.text(ax.get_xlim()[1], crest_m, " crest", fontsize=7, va="bottom", ha="right")

    # wind panel: model columns then obs, evenly spaced
    profs = [(lab, models[lab], DEFAULT_RUN_STYLES.get(i, {}).get("color", "black"))
             for i, lab in enumerate(labels)]
    if obs is not None:
        profs.append(("obs", obs, "k"))
    xs = np.linspace(0.28, 0.82, len(profs))
    for x, (lab, snd, color) in zip(xs, profs):
        _profile_barbs(axw, x, _heights(snd, z0), snd.u_kt, snd.v_kt, y_top_m, color)
    axw.set_xlim(0.15, 0.95)
    axw.set_xticks(list(xs))
    axw.set_xticklabels([lab for lab, _s, _c in profs], fontsize=8)
    axw.set_title("wind (kt)", fontsize=9)
    axw.tick_params(left=False)
    for s in ("top", "right", "left"):
        axw.spines[s].set_visible(False)

    ax.set_ylim(z0 - 50.0, y_top_m)
    vis = [m_th[lab][m_z[lab] <= y_top_m] for lab in labels]
    if obs is not None:
        vis.append(_theta_k(obs)[_heights(obs, z0) <= y_top_m])
    vis = np.concatenate([v for v in vis if v.size])
    ax.set_xlim(float(np.nanmin(vis)) - 1.5, float(np.nanmax(vis)) + 2.5)
    ax.set_xlabel(r"potential temperature  $\theta$  (K)")
    ax.set_ylabel("height (m MSL)")
    ax.set_title(title, fontsize=10)
    ax.grid(True, axis="y", alpha=0.25)

    handles, _ = ax.get_legend_handles_labels()
    handles += [Patch(fc=band_c["inversion"], alpha=0.25, label="inversion (very stable)"),
                Patch(fc=band_c["unstable"], alpha=0.25, label="unstable (dθ/dz<0)")]
    ax.legend(handles=handles, loc="lower right", fontsize=7.5, framealpha=0.9)
    ax.text(0.015, 0.985,
            "dotted verticals = dry adiabats (constant θ, neutral)\n"
            f"curve tilting right with height ⇒ statically stable\n"
            f"shaded bands = stability of the {primary} WRF column",
            transform=ax.transAxes, va="top", ha="left", fontsize=7, alpha=0.8)
    if annotation:
        ax.text(0.99, 0.985, annotation, transform=ax.transAxes, ha="right", va="top",
                fontsize=6, alpha=0.6)

    out.parent.mkdir(parents=True, exist_ok=True)
    # Force a full-figure save: the publication style sets savefig.bbox='tight', whose
    # size estimate balloons the width for this two-axes wind-panel layout. The fixed
    # subplots_adjust margins above already frame the figure, so 'standard' is right.
    with matplotlib.rc_context({"savefig.bbox": "standard"}):
        fig.savefig(out, dpi=dpi)
    plt.close(fig)
    return out

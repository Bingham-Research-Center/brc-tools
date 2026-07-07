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
    """A vertical sounding in plain units (hPa, deg C, knots)."""

    pressure_hpa: np.ndarray
    temperature_c: np.ndarray
    dewpoint_c: np.ndarray
    u_kt: np.ndarray | None
    v_kt: np.ndarray | None
    source: str
    station: str
    valid_time: datetime | None = None


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


class WyomingSounding:
    """Sounding source for the University of Wyoming archive (needs network)."""

    def get(self, station: str, valid_time: datetime) -> Sounding | None:
        try:
            from siphon.simplewebservice.wyoming import WyomingUpperAir
        except ImportError:
            return None
        try:
            df = WyomingUpperAir.request_data(valid_time, station)
        except Exception:
            return None
        return Sounding(
            pressure_hpa=df["pressure"].values,
            temperature_c=df["temperature"].values,
            dewpoint_c=df["dewpoint"].values,
            u_kt=df["u_wind"].values,
            v_kt=df["v_wind"].values,
            source="RAOB",
            station=station,
            valid_time=valid_time,
        )


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
        )


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

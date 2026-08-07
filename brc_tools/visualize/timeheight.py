"""Time-height sections: the whole night in one panel.

Every other vertical figure in this package is a snapshot -- one valid time, one
place, one cut.  A cold pool is a *process*: it starts somewhere, deepens,
sometimes gets scoured and rebuilds, and breaks up at a particular hour.  A
sweep of snapshots contains that, but only in the reader's memory of the frames
they have scrolled past, and the one question a sweep cannot answer is *when*.

The data for it is already on disk and costs nothing.  A run with a ``tslist``
writes per-station column profiles at **model-timestep cadence** (3 s on the run
this was built for, against hourly ``wrfout`` files of 900 MB each), in text
files of a few tens of megabytes.  That is a 1200x finer time axis than the
history stream, for 3% of the bytes, and it has been sitting unplotted.

Drawn on the model's own levels, with the height mesh carried per time rather
than averaged into a single axis, for the same reason the curtain renderer shades
true cells: near the ground the levels are metres apart and that is where the
answer is.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

# Private, same reasoning as visualize/tracer_origin: re-implementing the
# cell-edge helper here would let the two copies drift, and a curtain and a
# time-height panel of the same run must draw the same cells.
from brc_tools.visualize.style import norm_kwargs
from brc_tools.visualize.wrf_curtain import _edges1d

__all__ = ["FIELD_LABEL", "derive_field", "timeheight_mesh", "plot_time_height"]

#: Colourbar labels for the fields :func:`derive_field` can build from a
#: ``tslist`` profile set.  As on a curtain, the label is the *definition* of
#: what is drawn -- see ``wrf_curtain.SHADE_LABEL`` for why that matters.
FIELD_LABEL = {
    "theta": r"$\theta$ (K)",
    "theta_change": r"$\theta(t) - \theta(t_0)$ (K) at the same height",
    "theta_grad": r"$\partial\theta/\partial z$ (K per 100 m) -- $+$ is stable",
    "speed": r"wind speed (m s$^{-1}$) -- magnitude, no direction",
    "u": r"$u$ (m s$^{-1}$), $+$ eastward",
    "v": r"$v$ (m s$^{-1}$), $+$ northward",
    "w": r"$w$ (m s$^{-1}$), $+$ upward",
    "qv": r"water vapour (g kg$^{-1}$)",
}

#: Field -> the style key it is coloured by, and the profile kinds it needs.
FIELD_STYLE = {
    "theta": "theta", "theta_change": "theta_change", "theta_grad": "theta_grad",
    "speed": "wind_speed_10m", "u": "wind_along", "v": "wind_along",
    "w": "w", "qv": "qvapor",
}
FIELD_REQUIRES = {
    "theta": ("TH",), "theta_change": ("TH",), "theta_grad": ("TH", "PH"),
    "speed": ("UU", "VV"), "u": ("UU",), "v": ("VV",), "w": ("WW",),
    "qv": ("QV",),
}


def derive_field(profiles: dict, field: str) -> np.ndarray:
    """Build one ``(nt, nlev)`` field from a :func:`~brc_tools.nwp.wrf_tslist.read_ts_profiles` result.

    ``theta_change`` is differenced against the **first time in the window**, not
    against a level mean or the column below: the question a time-height panel is
    asked is how much a given height has cooled since the run started, and that
    is a difference at fixed height, taken at fixed height.
    """
    if field not in FIELD_REQUIRES:
        raise KeyError(f"unknown time-height field {field!r}; "
                       f"known: {sorted(FIELD_REQUIRES)}")
    missing = [k for k in FIELD_REQUIRES[field] if k not in profiles]
    if missing:
        raise KeyError(f"{field} needs profile kinds {', '.join(missing)}")

    if field == "theta":
        return np.asarray(profiles["TH"], dtype=float)
    if field == "theta_change":
        th = np.asarray(profiles["TH"], dtype=float)
        return th - th[0][None, :]
    if field == "theta_grad":
        th = np.asarray(profiles["TH"], dtype=float)
        z = np.asarray(profiles["PH"], dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.gradient(th, axis=1) / np.gradient(z, axis=1) * 100.0
    if field == "speed":
        return np.hypot(np.asarray(profiles["UU"], dtype=float),
                        np.asarray(profiles["VV"], dtype=float))
    if field == "qv":
        return np.asarray(profiles["QV"], dtype=float) * 1000.0
    return np.asarray(profiles[{"u": "UU", "v": "VV", "w": "WW"}[field]], dtype=float)


def timeheight_mesh(t, height) -> tuple[np.ndarray, np.ndarray]:
    """Cell-corner arrays ``(X, Y)``, each ``(nt+1, nlev+1)``, for flat shading.

    ``t`` is ``(nt,)`` (matplotlib date numbers) and ``height`` ``(nt, nlev)``.
    Explicit corners rather than ``shading="nearest"`` on the centres: the
    centre arrays are a proper curvilinear mesh -- time varies along one axis
    and height along the other -- which matplotlib cannot infer edges from, and
    it says so with a monotonicity warning before guessing.
    """
    t = np.asarray(t, dtype=float)
    z = np.asarray(height, dtype=float)
    inner = 0.5 * (z[:, 1:] + z[:, :-1])
    z_edge = np.hstack([2 * z[:, :1] - inner[:, :1], inner,
                        2 * z[:, -1:] - inner[:, -1:]])  # (nt, nlev+1)
    inner_t = 0.5 * (z_edge[1:, :] + z_edge[:-1, :])
    Y = np.vstack([2 * z_edge[:1, :] - inner_t[:1, :], inner_t,
                   2 * z_edge[-1:, :] - inner_t[-1:, :]])  # (nt+1, nlev+1)
    X = np.broadcast_to(_edges1d(t)[:, None], Y.shape)
    return np.asarray(X), Y


def plot_time_height(
    times,
    height_agl,
    field,
    out_path,
    *,
    style,
    cbar_label: str | None = None,
    title: str,
    annotation: str | None = None,
    theta=None,
    theta_interval: float = 1.0,
    wind: tuple[np.ndarray, np.ndarray] | None = None,
    barb_stride: tuple[int, int] = (12, 4),
    y_top_m: float = 2000.0,
    y_bottom_m: float = 0.0,
    local_offset_h: float | None = None,
    local_label: str = "local",
    figsize: tuple[float, float] = (12.0, 5.6),
    dpi: int = 200,
) -> Path:
    """Render a time-height section.

    ``times`` is ``(nt,)`` datetimes, ``height_agl`` and ``field`` are
    ``(nt, nlev)``.  Height is carried per time rather than collapsed to one
    axis, so the mesh is the model's own and nothing is resampled.

    ``local_offset_h`` adds a second time axis on top in local standard time.
    A diurnal figure whose only axis is UTC makes the reader do the arithmetic
    that decides whether a feature is before or after sunset, which is usually
    the point of looking.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    t = mdates.date2num(list(times))
    z = np.asarray(height_agl, dtype=float)
    f = np.asarray(field, dtype=float)
    T = np.broadcast_to(t[:, None], z.shape)

    fig, ax = plt.subplots(figsize=figsize, constrained_layout=True)
    ax.set_facecolor("0.6")
    # Flat shading on the model's own cells; "gouraud" would smooth across the
    # very level spacing that makes this figure worth drawing.
    X, Y = timeheight_mesh(t, z)
    mesh = ax.pcolormesh(X, Y, f, cmap=style.cmap, shading="flat",
                         **norm_kwargs(style))
    fig.colorbar(mesh, ax=ax, shrink=0.85, extend=style.extend,
                 label=cbar_label if cbar_label is not None else style.label)

    if theta is not None:
        th = np.asarray(theta, dtype=float)
        lo = np.floor(np.nanmin(th) / theta_interval) * theta_interval
        hi = np.ceil(np.nanmax(th) / theta_interval) * theta_interval
        cs = ax.contour(T, z, th, levels=np.arange(lo, hi + 0.1, theta_interval),
                        colors="black", linewidths=0.4, alpha=0.5)
        ax.clabel(cs, cs.levels[::2], fontsize=6, fmt="%.0f")

    if wind is not None:
        st_t, st_z = barb_stride
        u, v = (np.asarray(a, dtype=float) * 1.94384 for a in wind)
        ax.barbs(T[::st_t, ::st_z], z[::st_t, ::st_z],
                 u[::st_t, ::st_z], v[::st_t, ::st_z],
                 length=4.5, linewidth=0.35, zorder=8)

    ax.set_ylim(y_bottom_m, y_top_m)
    ax.set_xlim(t.min(), t.max())
    ax.set_ylabel("height above ground (m)")
    ax.set_xlabel("time (UTC)")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %HZ"))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=3))
    ax.set_title(title)

    if local_offset_h is not None:
        axt = ax.secondary_xaxis(
            "top",
            functions=(lambda x: x + local_offset_h / 24.0,
                       lambda x: x - local_offset_h / 24.0))
        axt.xaxis.set_major_formatter(mdates.DateFormatter("%H"))
        axt.xaxis.set_major_locator(mdates.HourLocator(interval=3))
        axt.set_xlabel(f"time ({local_label})")

    if annotation:
        ax.text(0.99, 0.02, annotation, transform=ax.transAxes, ha="right",
                va="bottom", fontsize=6, alpha=0.7,
                bbox={"facecolor": "white", "edgecolor": "none",
                      "alpha": 0.55, "pad": 1.5})

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    return out

"""Sanity quicklooks for staged WRF-input GRIB (non-fatal, best-effort).

These reopen an already-staged GRIB **without Herbie** (Herbie's ``.xarray()``
would delete the file) via cfgrib, crop to the basin, and render a PNG so a human
can eyeball snowy-Basin behaviour. They are deliberately tolerant: any failure is
logged and surfaced as an exception for the caller to swallow, never a hard stop
for the staging run.

Optional obs alignment reuses ``brc_tools.nwp.case_study.fetch_obs`` (SynopticPy)
— note that for a 2013 historical date the basin mesonet barely existed, so an
empty/None result is expected and handled gracefully.
"""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless CHPC nodes
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from brc_tools.nwp._crop import crop_to_bbox  # noqa: E402
from brc_tools.nwp.source import load_lookups  # noqa: E402

LOG = logging.getLogger(__name__)

DEFAULT_CASE = "jan2013_basin_gefs"
DEFAULT_REGION = "uinta_basin_wide"
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _figure_dir(case: str, figure_dir: str | Path | None) -> Path:
    out = Path(figure_dir) if figure_dir is not None else _REPO_ROOT / "figures" / case
    out.mkdir(parents=True, exist_ok=True)
    return out


def _region_swne(region: str) -> tuple[tuple[float, float], tuple[float, float]] | None:
    cfg = load_lookups().get("regions", {}).get(region)
    if not cfg:
        return None
    return tuple(cfg["sw"]), tuple(cfg["ne"])


def quicklook_staged_grib(
    staged_path: str | Path,
    *,
    variable_level: str,
    fxx: int = 24,
    region: str = DEFAULT_REGION,
    figure_dir: str | Path | None = None,
    case: str = DEFAULT_CASE,
) -> Path:
    """Render a basin map of one staged surface GRIB at lead time ``fxx``.

    Opens the staged file with cfgrib, selects the step nearest ``fxx`` hours,
    crops to ``region``, and saves ``<figures>/<case>/<variable_level>_f{fxx}.png``.
    Reuses :func:`brc_tools.visualize.planview.plot_planview`, falling back to a
    plain pcolormesh if that path raises.
    """
    import xarray as xr

    ds = xr.open_dataset(
        str(staged_path),
        engine="cfgrib",
        backend_kwargs={"indexpath": ""},
    )

    if "step" in ds.dims:
        ds = ds.sel(step=np.timedelta64(int(fxx), "h"), method="nearest")

    swne = _region_swne(region)
    if swne is not None:
        ds = crop_to_bbox(ds, swne[0], swne[1], "lonlat_shift_then_sel")

    data_vars = list(ds.data_vars)
    if not data_vars:
        raise ValueError(f"No data variables in {staged_path}")
    var = data_vars[0]

    # The reforecast cfgrib dataset carries the lead time as ``step`` with a scalar
    # ``time``; plot_planview wants a singleton ``time`` *dimension*. Build a clean
    # (time=1, lat, lon) field, keeping the valid time for the label.
    valid = ds["valid_time"].values if "valid_time" in ds.coords else (
        ds["time"].values if "time" in ds.coords else None
    )
    field2d = ds[var].reset_coords(drop=True)
    one_ds = field2d.to_dataset(name=var)
    if valid is not None:
        one_ds = one_ds.expand_dims(time=[np.datetime64(valid)])

    out_path = _figure_dir(case, figure_dir) / f"{variable_level}_f{int(fxx):03d}.png"
    vt_label = str(valid)[:16] if valid is not None else ""
    title = f"{variable_level}  f{int(fxx):03d}  valid {vt_label}Z  ({case})"

    try:
        from brc_tools.nwp.case_study import annotate
        from brc_tools.visualize.planview import plot_planview

        ax = plot_planview(one_ds, var, time_idx=0, title=title)
        fig = ax.get_figure()
        annotate(fig, "GEFSv12 Reforecast | WRF-input staging | BRC Tools")
        fig.savefig(out_path, dpi=150, bbox_inches="tight")
        plt.close(fig)
    except Exception as exc:  # noqa: BLE001 - cosmetic fallback
        LOG.warning("plot_planview failed (%s); using plain fallback", exc)
        _plain_map(field2d.to_dataset(name=var), var, title, out_path)

    return out_path


def _plain_map(ds, var: str, title: str, out_path: Path) -> None:
    """Minimal pcolormesh fallback with no cartopy dependency."""
    lat = np.asarray(ds["latitude"].values)
    lon = np.asarray(ds["longitude"].values)
    field = np.asarray(ds[var].values)
    fig, ax = plt.subplots(figsize=(8, 6))
    mesh = ax.pcolormesh(lon, lat, field, shading="nearest", cmap="RdYlBu_r")
    fig.colorbar(mesh, ax=ax, shrink=0.8)
    ax.set_title(title)
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    fig.text(0.99, 0.01, "GEFSv12 Reforecast | WRF-input staging | BRC Tools",
             ha="right", va="bottom", fontsize=6, style="italic", alpha=0.7)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def obs_sanity_overlay(
    *,
    case: str = DEFAULT_CASE,
    event_date: str = "2013-01-31",
    stids: tuple[str, ...] = ("KVEL",),
    variables: tuple[str, ...] = ("temp_2m",),
    figure_dir: str | Path | None = None,
) -> Path | None:
    """Opt-in, non-fatal obs time series for the event window.

    Returns the PNG path, or ``None`` if no obs were returned (expected for 2013).
    """
    from brc_tools.nwp.case_study import fetch_obs

    obs_df = fetch_obs(
        stids=list(stids),
        event_date=event_date,
        variables=list(variables),
        start_spec="{date} 12Z",
        end_spec="{next_day} 00Z",
    )
    if obs_df is None or obs_df.height == 0:
        LOG.warning("No obs returned for %s %s (expected for historical dates)", stids, event_date)
        return None

    var = variables[0]
    out_path = _figure_dir(case, figure_dir) / f"obs_{'_'.join(stids)}_{var}.png"
    fig, ax = plt.subplots(figsize=(8, 4))
    for stid in stids:
        sub = obs_df.filter(obs_df["stid"] == stid) if "stid" in obs_df.columns else obs_df
        if sub.height and var in sub.columns:
            ax.plot(sub["valid_time"].to_list(), sub[var].to_list(), marker=".", label=stid)
    ax.set_title(f"Obs {var} — {event_date} ({case})")
    ax.set_xlabel("valid time (UTC)")
    ax.set_ylabel(var)
    ax.legend()
    fig.autofmt_xdate()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path

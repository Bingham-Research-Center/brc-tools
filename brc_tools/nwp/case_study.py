"""Shared utilities for case study scripts.

Provides helpers for the common case study workflow:

1. Load waypoints from ``lookups.toml``
2. Fetch NWP surface data for multiple init times
3. Extract waypoint time series
4. Fetch observations for a waypoint group or single station
5. Run a figure pipeline with per-figure error handling

Example::

    from brc_tools.nwp.case_study import (
        load_waypoints, next_day, fetch_multi_init,
        extract_all_waypoints, fetch_obs, run_figure_pipeline, annotate,
    )
"""

from __future__ import annotations

import datetime
import traceback
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import polars as pl
import xarray as xr

from brc_tools.nwp import NWPSource
from brc_tools.nwp.derived import add_theta_e, add_wind_fields
from brc_tools.nwp.source import load_lookups


# ---------------------------------------------------------------------------
# Waypoint helpers
# ---------------------------------------------------------------------------

def load_waypoints(group: str) -> dict[str, dict]:
    """Load waypoint metadata for a named group from ``lookups.toml``.

    Parameters
    ----------
    group : str
        Waypoint group name (e.g. ``"foehn_path"``, ``"us40_dense"``).

    Returns
    -------
    dict[str, dict]
        ``{waypoint_name: {"lat": ..., "lon": ..., "elevation_m": ..., ...}}``.
    """
    lu = load_lookups()
    names = lu["waypoint_groups"][group]
    return {name: lu["waypoints"][name] for name in names}


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def next_day(date_str: str) -> str:
    """Return ``YYYY-MM-DD`` for the day after *date_str*.

    Parameters
    ----------
    date_str : str
        ISO date string (``"YYYY-MM-DD"``).

    Returns
    -------
    str
    """
    d = datetime.date.fromisoformat(date_str)
    return (d + datetime.timedelta(days=1)).isoformat()


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def fetch_multi_init(
    src: NWPSource,
    event_date: str,
    init_hours: Sequence[int],
    sfc_vars: list[str],
    fhour_map: dict[int, range | list[int]],
    *,
    region: str = "uinta_basin",
    add_derived: bool = True,
    post_process: Callable[[xr.Dataset], xr.Dataset] | None = None,
) -> dict[int, xr.Dataset]:
    """Fetch surface NWP data for multiple init hours.

    Parameters
    ----------
    src : NWPSource
        Initialised NWP source (e.g. ``NWPSource("hrrr")``).
    event_date : str
        Event date as ``"YYYY-MM-DD"``.
    init_hours : sequence of int
        Init hours to fetch (e.g. ``[12, 18]``).
    sfc_vars : list[str]
        Surface variable aliases to fetch.
    fhour_map : dict[int, range | list[int]]
        Mapping of init hour to forecast hour range.
    region : str
        Region name from ``lookups.toml`` (default ``"uinta_basin"``).
    add_derived : bool
        If ``True``, add wind speed/direction and theta-e (default ``True``).
    post_process : callable, optional
        Additional per-dataset transformation ``(ds) -> ds``, applied after
        derived fields. Use for script-specific additions like T-Td spread.

    Returns
    -------
    dict[int, xr.Dataset]
        ``{init_hour: xr.Dataset}`` with derived fields added.
    """
    datasets: dict[int, xr.Dataset] = {}
    for ih in init_hours:
        init_str = f"{event_date} {ih:02d}Z"
        fhours = fhour_map[ih]
        print(f"  Fetching {src._model_key} sfc init={init_str} "
              f"f00-f{max(fhours):02d} ...")
        ds = src.fetch(
            init_time=init_str,
            forecast_hours=fhours,
            variables=sfc_vars,
            region=region,
        )
        if add_derived:
            ds = add_wind_fields(ds)
            ds = add_theta_e(ds)
        if post_process is not None:
            ds = post_process(ds)
        datasets[ih] = ds
        print(f"    -> {ds.sizes}")
    return datasets


def extract_all_waypoints(
    src: NWPSource,
    datasets: dict[int, xr.Dataset],
    group: str,
) -> dict[int, pl.DataFrame]:
    """Extract waypoint time series from each init run.

    Parameters
    ----------
    src : NWPSource
        The NWP source used for extraction (has ``extract_at_waypoints``).
    datasets : dict[int, xr.Dataset]
        ``{init_hour: xr.Dataset}`` as returned by ``fetch_multi_init``.
    group : str
        Waypoint group name.

    Returns
    -------
    dict[int, pl.DataFrame]
        ``{init_hour: pl.DataFrame}`` with columns
        ``[waypoint, valid_time, ...data_vars]``.
    """
    wp_series: dict[int, pl.DataFrame] = {}
    for ih, ds in datasets.items():
        print(f"  Extracting waypoints ({group}) for {ih}Z run ...")
        df = src.extract_at_waypoints(ds, group=group)
        wp_series[ih] = df
    return wp_series


def fetch_obs(
    *,
    waypoint_group: str | None = None,
    stids: list[str] | None = None,
    event_date: str,
    variables: list[str],
    start_spec: str = "{date} 12Z",
    end_spec: str = "{next_day} 06Z",
) -> pl.DataFrame | None:
    """Fetch observations with error handling.

    Provide either *waypoint_group* or *stids*.

    Parameters
    ----------
    waypoint_group : str, optional
        Waypoint group name (e.g. ``"foehn_path"``).
    stids : list[str], optional
        Explicit station IDs (e.g. ``["KVEL"]``).
    event_date : str
        Event date as ``"YYYY-MM-DD"``.
    variables : list[str]
        Canonical variable aliases to fetch.
    start_spec : str
        Start time template with ``{date}`` and ``{next_day}`` placeholders.
    end_spec : str
        End time template with ``{date}`` and ``{next_day}`` placeholders.

    Returns
    -------
    pl.DataFrame or None
        Observation data, or ``None`` if the fetch failed.
    """
    from brc_tools.obs import ObsSource

    nd = next_day(event_date)
    start = start_spec.format(date=event_date, next_day=nd)
    end = end_spec.format(date=event_date, next_day=nd)

    label = waypoint_group or ",".join(stids or [])
    print(f"  Fetching obs for {label}: {start} — {end} ...")

    try:
        obs = ObsSource()
        kwargs: dict[str, Any] = {
            "start": start,
            "end": end,
            "variables": variables,
        }
        if waypoint_group:
            kwargs["waypoint_group"] = waypoint_group
        elif stids:
            kwargs["stids"] = stids

        obs_df = obs.timeseries(**kwargs)
        print(f"    -> {obs_df.shape[0]} obs rows")
        return obs_df
    except Exception as exc:
        print(f"  [WARN] Obs fetch failed: {exc}")
        return None


# ---------------------------------------------------------------------------
# Figure pipeline
# ---------------------------------------------------------------------------

def run_figure_pipeline(
    figures: list[tuple[str, Callable, tuple]],
) -> None:
    """Execute a list of figure-generating functions with per-figure error handling.

    Parameters
    ----------
    figures : list of (name, func, args) tuples
        Each entry is ``("descriptive name", callable, (arg1, arg2, ...))``.
        The callable is invoked as ``func(*args)``.
    """
    for name, func, args in figures:
        print(f"\n{name} ...")
        try:
            func(*args)
        except Exception as exc:
            print(f"  [ERROR] {name} failed: {exc}")
            traceback.print_exc()


def annotate(fig: plt.Figure, text: str) -> None:
    """Add small italic attribution text to the bottom-right of *fig*.

    Parameters
    ----------
    fig : matplotlib.figure.Figure
        The figure to annotate.
    text : str
        Attribution text (e.g. ``"HRRR | Case Study | BRC Tools"``).
    """
    fig.text(
        0.99, 0.01, text, fontsize=6, ha="right", va="bottom",
        fontstyle="italic", color="gray",
    )

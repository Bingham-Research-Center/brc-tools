"""Model/observation temporal alignment and unit harmonisation.

Provides tools for pairing NWP waypoint extractions with Synoptic
observations in time and converting both to common units so that
verification metrics can be computed directly.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import polars as pl

from brc_tools.nwp.source import load_lookups

logger = logging.getLogger(__name__)

# Unit conversion functions keyed by (from_unit, to_unit).
_UNIT_CONVERTERS: dict[tuple[str, str], callable] = {
    ("K", "C"): lambda x: x - 273.15,
    ("C", "K"): lambda x: x + 273.15,
    ("Pa", "hPa"): lambda x: x / 100.0,
    ("hPa", "Pa"): lambda x: x * 100.0,
    ("mm", "m"): lambda x: x / 1000.0,
    ("m", "mm"): lambda x: x * 1000.0,
}


def harmonize_units(
    nwp_df: pl.DataFrame,
    obs_df: pl.DataFrame,
    variables: Sequence[str],
    *,
    target: str = "obs",
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Convert NWP and obs DataFrames to common units.

    Reads ``units`` (NWP) and ``synoptic_units`` (obs) from
    ``lookups.toml`` for each variable and applies the appropriate
    conversion so both frames share the same unit system.

    Parameters
    ----------
    nwp_df, obs_df : pl.DataFrame
        DataFrames from ``NWPSource.extract_at_waypoints()`` and
        ``ObsSource.timeseries()`` respectively.
    variables : sequence of str
        Canonical alias names to harmonise (e.g. ``["temp_2m"]``).
    target : {"obs", "nwp"}
        Which unit system to convert *to*.  ``"obs"`` (default) converts
        NWP values into observation units (e.g. K -> C for temperature).
        ``"nwp"`` converts observations into NWP units.

    Returns
    -------
    (nwp_df, obs_df) : tuple of pl.DataFrame
        Copies with converted columns.
    """
    lu = load_lookups()
    aliases = lu["aliases"]

    nwp_exprs: list[pl.Expr] = []
    obs_exprs: list[pl.Expr] = []

    for var in variables:
        alias = aliases.get(var)
        if alias is None:
            continue
        output_var = alias.get("output_var", var)
        nwp_unit = alias.get("units")
        obs_unit = alias.get("synoptic_units")

        if nwp_unit is None or obs_unit is None or nwp_unit == obs_unit:
            continue

        if target == "obs":
            conv = _UNIT_CONVERTERS.get((nwp_unit, obs_unit))
            if conv and output_var in nwp_df.columns:
                nwp_exprs.append(pl.col(output_var).map_batches(
                    lambda s, _c=conv: pl.Series(s.name, _c(s.to_numpy())),
                    return_dtype=pl.Float64,
                ))
        else:
            conv = _UNIT_CONVERTERS.get((obs_unit, nwp_unit))
            if conv and output_var in obs_df.columns:
                obs_exprs.append(pl.col(output_var).map_batches(
                    lambda s, _c=conv: pl.Series(s.name, _c(s.to_numpy())),
                    return_dtype=pl.Float64,
                ))

    if nwp_exprs:
        nwp_df = nwp_df.with_columns(nwp_exprs)
    if obs_exprs:
        obs_df = obs_df.with_columns(obs_exprs)

    return nwp_df, obs_df


def align_obs_to_nwp(
    obs_df: pl.DataFrame,
    nwp_df: pl.DataFrame,
    *,
    variables: Sequence[str] | None = None,
    tolerance_minutes: int = 30,
    strategy: str = "nearest",
    harmonize: bool = True,
) -> pl.DataFrame:
    """Temporal asof-join of observations onto NWP valid times.

    For each (waypoint, NWP valid_time) pair, the closest observation
    within *tolerance_minutes* is matched.  The result has one row per
    NWP valid time per waypoint, with suffixed columns for paired values
    (e.g. ``temp_2m_nwp``, ``temp_2m_obs``).

    Parameters
    ----------
    obs_df : pl.DataFrame
        From ``ObsSource.timeseries()``.
    nwp_df : pl.DataFrame
        From ``NWPSource.extract_at_waypoints()``.
    variables : list of str, optional
        Canonical alias names to include.  If *None*, all columns present
        in both frames (excluding ``waypoint`` and ``valid_time``) are used.
    tolerance_minutes : int
        Maximum gap (minutes) between obs and NWP valid time for a match.
    strategy : {"nearest", "backward", "forward"}
        Polars ``join_asof`` strategy.
    harmonize : bool
        If *True* (default), convert NWP units to obs units before joining
        so that paired columns are directly comparable.

    Returns
    -------
    pl.DataFrame
        Columns: ``waypoint``, ``valid_time``, then ``{var}_nwp`` and
        ``{var}_obs`` for each variable.  Rows with no obs match within
        tolerance have null obs values.
    """
    if "waypoint" not in obs_df.columns or "waypoint" not in nwp_df.columns:
        raise ValueError("Both DataFrames must have a 'waypoint' column")
    if "valid_time" not in obs_df.columns or "valid_time" not in nwp_df.columns:
        raise ValueError("Both DataFrames must have a 'valid_time' column")

    # Determine which variables to pair
    meta_cols = {"waypoint", "valid_time", "stid", "source"}
    if variables is None:
        nwp_vars = set(nwp_df.columns) - meta_cols
        obs_vars = set(obs_df.columns) - meta_cols
        variables = sorted(nwp_vars & obs_vars)
    if not variables:
        raise ValueError("No overlapping data variables found")

    # Harmonise units (NWP → obs units by default)
    if harmonize:
        nwp_df, obs_df = harmonize_units(nwp_df, obs_df, variables, target="obs")

    # Prepare NWP side: keep waypoint, valid_time, + variables, suffix _nwp
    nwp_cols = ["waypoint", "valid_time"] + [v for v in variables if v in nwp_df.columns]
    nwp_sub = nwp_df.select(nwp_cols).rename(
        {v: f"{v}_nwp" for v in variables if v in nwp_df.columns}
    )

    # Prepare obs side: keep waypoint, valid_time, + variables, suffix _obs
    obs_cols = ["waypoint", "valid_time"] + [v for v in variables if v in obs_df.columns]
    obs_sub = obs_df.select(obs_cols).rename(
        {v: f"{v}_obs" for v in variables if v in obs_df.columns}
    )

    # Ensure both are sorted by (waypoint, valid_time) for join_asof
    nwp_sub = nwp_sub.sort(["waypoint", "valid_time"])
    obs_sub = obs_sub.sort(["waypoint", "valid_time"])

    tolerance = f"{tolerance_minutes}m"

    paired = nwp_sub.join_asof(
        obs_sub,
        on="valid_time",
        by="waypoint",
        strategy=strategy,
        tolerance=tolerance,
    )

    return paired

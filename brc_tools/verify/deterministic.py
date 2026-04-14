"""Deterministic forecast verification metrics.

Scalar functions operate on numpy arrays.  ``paired_scores`` is the
high-level integration point that joins NWP and obs Polars DataFrames
and returns per-station, per-variable skill scores.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import numpy as np
import polars as pl

from brc_tools.nwp.alignment import align_obs_to_nwp

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scalar metrics (numpy)
# ---------------------------------------------------------------------------

def bias(forecast: np.ndarray, observed: np.ndarray) -> float:
    """Mean error (forecast - observed).  Positive = warm/high bias."""
    fc, ob = _clean_pair(forecast, observed)
    if len(fc) == 0:
        return np.nan
    return float(np.mean(fc - ob))


def mae(forecast: np.ndarray, observed: np.ndarray) -> float:
    """Mean absolute error."""
    fc, ob = _clean_pair(forecast, observed)
    if len(fc) == 0:
        return np.nan
    return float(np.mean(np.abs(fc - ob)))


def rmse(forecast: np.ndarray, observed: np.ndarray) -> float:
    """Root mean square error."""
    fc, ob = _clean_pair(forecast, observed)
    if len(fc) == 0:
        return np.nan
    return float(np.sqrt(np.mean((fc - ob) ** 2)))


def correlation(forecast: np.ndarray, observed: np.ndarray) -> float:
    """Pearson correlation coefficient.  Returns NaN if < 3 pairs."""
    fc, ob = _clean_pair(forecast, observed)
    if len(fc) < 3:
        return np.nan
    cc = np.corrcoef(fc, ob)
    return float(cc[0, 1])


# ---------------------------------------------------------------------------
# High-level integration
# ---------------------------------------------------------------------------

def paired_scores(
    nwp_df: pl.DataFrame,
    obs_df: pl.DataFrame,
    variables: Sequence[str],
    *,
    tolerance_minutes: int = 30,
    harmonize: bool = True,
) -> pl.DataFrame:
    """Compute per-station, per-variable verification scores.

    Joins ``nwp_df`` (from ``NWPSource.extract_at_waypoints()``) with
    ``obs_df`` (from ``ObsSource.timeseries()``) using a temporal
    asof-join, then computes deterministic scores for each
    (waypoint, variable) combination.

    Parameters
    ----------
    nwp_df, obs_df : pl.DataFrame
        Point time-series DataFrames with ``waypoint`` and
        ``valid_time`` columns.
    variables : sequence of str
        Canonical alias names to verify (e.g. ``["temp_2m", "wind_speed_10m"]``).
    tolerance_minutes : int
        Maximum gap for temporal matching (default 30 min).
    harmonize : bool
        Convert NWP units to obs units before comparison (default True).

    Returns
    -------
    pl.DataFrame
        Columns: ``waypoint``, ``variable``, ``n_obs``, ``bias``,
        ``mae``, ``rmse``, ``correlation``.
    """
    paired = align_obs_to_nwp(
        obs_df, nwp_df,
        variables=list(variables),
        tolerance_minutes=tolerance_minutes,
        harmonize=harmonize,
    )

    rows: list[dict] = []
    waypoints = paired["waypoint"].unique().sort().to_list()

    for wp in waypoints:
        wp_data = paired.filter(pl.col("waypoint") == wp)
        for var in variables:
            nwp_col = f"{var}_nwp"
            obs_col = f"{var}_obs"
            if nwp_col not in paired.columns or obs_col not in paired.columns:
                continue

            fc = wp_data[nwp_col].to_numpy().astype(float)
            ob = wp_data[obs_col].to_numpy().astype(float)

            rows.append({
                "waypoint": wp,
                "variable": var,
                "n_obs": int(np.sum(np.isfinite(fc) & np.isfinite(ob))),
                "bias": bias(fc, ob),
                "mae": mae(fc, ob),
                "rmse": rmse(fc, ob),
                "correlation": correlation(fc, ob),
            })

    return pl.DataFrame(rows)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _clean_pair(
    forecast: np.ndarray,
    observed: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Drop NaN/inf pairs and return aligned clean arrays."""
    fc = np.asarray(forecast, dtype=float).ravel()
    ob = np.asarray(observed, dtype=float).ravel()
    mask = np.isfinite(fc) & np.isfinite(ob)
    return fc[mask], ob[mask]

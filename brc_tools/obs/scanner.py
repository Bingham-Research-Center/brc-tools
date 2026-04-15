"""Scan station observations to identify and rank candidate weather events.

Provides a generic ``scan_events`` loop that queries ObsSource month-by-month,
partitions into daily windows, evaluates each day against a user-supplied
criteria function, and returns a ranked list of candidate events.

Pre-built criteria functions:

- ``detect_wind_ramp`` — sustained late-day westerly wind increase
- ``detect_foehn`` — foehn event: warming + drying + westerly wind ramp

Example::

    from brc_tools.obs.scanner import scan_events, detect_wind_ramp

    candidates = scan_events(
        stid="KVEL",
        variables=["wind_speed_10m", "wind_dir_10m"],
        months=(3, 4, 5),
        year=2025,
        criteria_fn=detect_wind_ramp,
        rank_key="wind_increase",
    )
"""

from __future__ import annotations

import datetime
import time
from collections.abc import Callable, Sequence
from typing import Any

import numpy as np
import polars as pl


# ---------------------------------------------------------------------------
# Generic scan loop
# ---------------------------------------------------------------------------

def scan_events(
    stid: str,
    variables: list[str],
    months: Sequence[int],
    year: int,
    criteria_fn: Callable[[pl.DataFrame, datetime.date], dict | None],
    *,
    rank_key: str = "score",
    rank_descending: bool = True,
    courtesy_pause: float = 0.5,
) -> list[dict[str, Any]]:
    """Scan a station's observations for events matching *criteria_fn*.

    Parameters
    ----------
    stid : str
        Synoptic station ID (e.g. ``"KVEL"``).
    variables : list[str]
        Canonical alias names to fetch (e.g. ``["wind_speed_10m", "wind_dir_10m"]``).
    months : sequence of int
        Calendar months to scan (e.g. ``(3, 4, 5)`` for March–May).
    year : int
        Year to scan.
    criteria_fn : callable
        ``(day_df: pl.DataFrame, date: datetime.date) -> dict | None``.
        Called once per calendar day with that day's obs rows. Return a dict
        containing at least the *rank_key* field if the day qualifies, or
        ``None`` to skip.
    rank_key : str
        Dict key used for sorting results (default ``"score"``).
    rank_descending : bool
        Sort highest-first when ``True`` (default).
    courtesy_pause : float
        Seconds to sleep between monthly API calls.

    Returns
    -------
    list[dict]
        Candidate events sorted by *rank_key*.
    """
    from brc_tools.obs import ObsSource

    obs = ObsSource()
    candidates: list[dict[str, Any]] = []

    for month in months:
        start = f"{year}-{month:02d}-01 00Z"
        if month == 12:
            end = f"{year + 1}-01-01 00Z"
        else:
            end = f"{year}-{month + 1:02d}-01 00Z"

        print(f"  Querying {stid} {year}-{month:02d} ...")
        try:
            df = obs.timeseries(
                stids=[stid],
                start=start,
                end=end,
                variables=variables,
            )
        except Exception as exc:
            print(f"    Failed: {exc}")
            continue
        time.sleep(courtesy_pause)

        if df.is_empty():
            print("    No data returned")
            continue

        print(f"    {df.shape[0]} rows returned")

        # Partition into calendar days and evaluate each
        df = df.with_columns(pl.col("valid_time").cast(pl.Date).alias("date"))
        for date_val in df["date"].unique().sort().to_list():
            day_df = df.filter(pl.col("date") == date_val).sort("valid_time")
            result = criteria_fn(day_df, date_val)
            if result is not None:
                candidates.append(result)

    candidates.sort(key=lambda c: c.get(rank_key, 0), reverse=rank_descending)
    return candidates


# ---------------------------------------------------------------------------
# Pre-built criteria functions
# ---------------------------------------------------------------------------

def detect_wind_ramp(
    day_df: pl.DataFrame,
    date_val: datetime.date,
    *,
    window_start_utc: int = 22,
    window_hours: int = 8,
    westerly_range: tuple[float, float] = (225.0, 315.0),
    min_consec_westerly: int = 3,
    min_peak_speed_ms: float = 8.0,
    min_increase_ms: float = 5.0,
    baseline_hours: int = 2,
) -> dict[str, Any] | None:
    """Detect a late-day westerly wind ramp event.

    Criteria (all must be met):
      - Westerly wind (225-315 deg) for >= *min_consec_westerly* consecutive hours
      - Wind speed increase >= *min_increase_ms* (peak minus baseline)
      - Peak sustained wind >= *min_peak_speed_ms*

    Parameters
    ----------
    day_df : pl.DataFrame
        Single-day obs with ``valid_time``, ``wind_speed_10m``, ``wind_dir_10m``.
    date_val : datetime.date
        The calendar date being evaluated.
    window_start_utc : int
        UTC hour the evaluation window starts (default 22).
    window_hours : int
        Duration of the evaluation window in hours (default 8).
    westerly_range : tuple[float, float]
        Wind direction range defining "westerly" (default 225-315 deg).
    min_consec_westerly : int
        Minimum consecutive hours of westerly wind (default 3).
    min_peak_speed_ms : float
        Minimum peak wind speed in m/s (default 8.0).
    min_increase_ms : float
        Minimum wind speed increase from baseline in m/s (default 5.0).
    baseline_hours : int
        Number of leading observations to average for baseline (default 2).

    Returns
    -------
    dict or None
        Event descriptor with keys: ``date``, ``peak_speed_ms``, ``peak_speed_kt``,
        ``wind_increase``, ``baseline_ms``, ``peak_time_utc``, ``consec_westerly_hrs``.
        Returns ``None`` if the day does not qualify.
    """
    d = _normalise_date(date_val)

    win_start = datetime.datetime(d.year, d.month, d.day, window_start_utc, 0)
    win_end = win_start + datetime.timedelta(hours=window_hours)

    window = day_df.filter(
        (pl.col("valid_time") >= win_start) & (pl.col("valid_time") <= win_end)
    )

    if window.shape[0] < 4:
        return None

    window = window.drop_nulls(subset=["wind_speed_10m", "wind_dir_10m"])
    if window.shape[0] < 4:
        return None

    speeds = window["wind_speed_10m"].to_list()
    dirs_ = window["wind_dir_10m"].to_list()

    # Count consecutive westerly hours
    max_consec = _max_consecutive_in_range(dirs_, westerly_range)
    if max_consec < min_consec_westerly:
        return None

    peak_speed = max(speeds)
    if peak_speed < min_peak_speed_ms:
        return None

    # Wind increase: peak minus baseline (average of first N values)
    n_bl = min(baseline_hours, len(speeds))
    baseline = float(np.mean(speeds[:n_bl])) if n_bl >= 1 else speeds[0]
    increase = peak_speed - baseline
    if increase < min_increase_ms:
        return None

    peak_idx = speeds.index(peak_speed)
    peak_time = window["valid_time"].to_list()[peak_idx]

    return {
        "date": str(d),
        "peak_speed_ms": round(peak_speed, 1),
        "peak_speed_kt": round(peak_speed * 1.94384, 1),
        "wind_increase": round(increase, 1),
        "baseline_ms": round(baseline, 1),
        "peak_time_utc": str(peak_time),
        "consec_westerly_hrs": max_consec,
    }


def detect_foehn(
    day_df: pl.DataFrame,
    date_val: datetime.date,
    *,
    window_start_utc: int = 20,
    window_hours: int = 10,
    westerly_range: tuple[float, float] = (225.0, 315.0),
    min_consec_westerly: int = 3,
    min_peak_speed_ms: float = 7.0,
    min_wind_increase_ms: float = 4.0,
    min_temp_increase_C: float = 2.0,
    min_dewpt_decrease_C: float = 2.0,
    max_post_peak_drop_C: float = 6.0,
    baseline_hours: int = 3,
) -> dict[str, Any] | None:
    """Detect a foehn event: warming + drying + westerly wind ramp.

    Criteria (all must be met):
      - Westerly wind for >= *min_consec_westerly* consecutive hours
      - Wind speed increase >= *min_wind_increase_ms*
      - Temperature increase >= *min_temp_increase_C* concurrent with wind ramp
      - Dewpoint decrease >= *min_dewpt_decrease_C* concurrent (drying)
      - No large temperature drop after peak (anti-front check)

    Parameters
    ----------
    day_df : pl.DataFrame
        Single-day obs with ``valid_time``, ``wind_speed_10m``, ``wind_dir_10m``,
        ``temp_2m``, ``dewpoint_2m``.
    date_val : datetime.date
        The calendar date being evaluated.
    window_start_utc : int
        UTC hour the evaluation window starts (default 20).
    window_hours : int
        Duration of the evaluation window in hours (default 10).
    westerly_range : tuple[float, float]
        Wind direction range defining "westerly" (default 225-315 deg).
    min_consec_westerly : int
        Minimum consecutive hours of westerly wind (default 3).
    min_peak_speed_ms : float
        Minimum peak wind speed in m/s (default 7.0).
    min_wind_increase_ms : float
        Minimum wind speed increase from baseline in m/s (default 4.0).
    min_temp_increase_C : float
        Minimum temperature increase in C concurrent with wind ramp (default 2.0).
    min_dewpt_decrease_C : float
        Minimum dewpoint decrease in C concurrent with wind ramp (default 2.0).
    max_post_peak_drop_C : float
        Maximum temperature drop after peak before event is rejected as
        likely frontal (default 6.0).
    baseline_hours : int
        Number of leading observations to average for baseline (default 3).

    Returns
    -------
    dict or None
        Event descriptor with keys: ``date``, ``foehn_score``, ``peak_speed_ms``,
        ``wind_increase``, ``temp_increase_C``, ``dewpt_decrease_C``,
        ``consec_westerly``, ``peak_time_utc``.
        Returns ``None`` if the day does not qualify.
    """
    d = _normalise_date(date_val)

    win_start = datetime.datetime(d.year, d.month, d.day, window_start_utc, 0)
    win_end = win_start + datetime.timedelta(hours=window_hours)

    window = day_df.filter(
        (pl.col("valid_time") >= win_start) & (pl.col("valid_time") <= win_end)
    )

    required = ["wind_speed_10m", "wind_dir_10m", "temp_2m", "dewpoint_2m"]
    for col in required:
        if col not in window.columns:
            return None

    window = window.drop_nulls(subset=required)
    if window.shape[0] < 5:
        return None

    speeds = window["wind_speed_10m"].to_list()
    dirs_ = window["wind_dir_10m"].to_list()
    temps = window["temp_2m"].to_list()
    dewpts = window["dewpoint_2m"].to_list()

    # -- Wind criteria: consecutive westerly hours --
    max_consec = _max_consecutive_in_range(dirs_, westerly_range)
    if max_consec < min_consec_westerly:
        return None

    # -- Wind speed increase --
    peak_speed = max(speeds)
    if peak_speed < min_peak_speed_ms:
        return None

    n_bl = min(baseline_hours, len(speeds))
    baseline_speed = float(np.nanmean(speeds[:n_bl])) if n_bl >= 1 else speeds[0]
    wind_increase = peak_speed - baseline_speed
    if wind_increase < min_wind_increase_ms:
        return None

    peak_idx = speeds.index(peak_speed)

    # -- Temperature increase concurrent with wind ramp --
    baseline_temp = float(np.nanmean(temps[:n_bl]))
    ramp_end = min(peak_idx + 3, len(temps))
    ramp_temps = temps[max(0, peak_idx - 2):ramp_end]
    peak_temp = max(ramp_temps) if ramp_temps else max(temps)
    temp_increase = peak_temp - baseline_temp
    if temp_increase < min_temp_increase_C:
        return None

    # -- Dewpoint decrease (drying) --
    baseline_dewpt = float(np.nanmean(dewpts[:n_bl]))
    ramp_dewpts = dewpts[max(0, peak_idx - 2):ramp_end]
    min_dewpt = min(ramp_dewpts) if ramp_dewpts else min(dewpts)
    dewpt_decrease = baseline_dewpt - min_dewpt
    if dewpt_decrease < min_dewpt_decrease_C:
        return None

    # -- Anti-front check: temperature should NOT drop sharply after peak --
    post_peak_temps = temps[peak_idx:]
    if len(post_peak_temps) >= 3:
        post_min = min(post_peak_temps)
        if (peak_temp - post_min) > max_post_peak_drop_C:
            return None

    # -- Composite foehn score --
    foehn_score = round(wind_increase + temp_increase + dewpt_decrease, 1)
    peak_time = window["valid_time"].to_list()[peak_idx]

    return {
        "date": str(d),
        "foehn_score": foehn_score,
        "peak_speed_ms": round(peak_speed, 1),
        "wind_increase": round(wind_increase, 1),
        "temp_increase_C": round(temp_increase, 1),
        "dewpt_decrease_C": round(dewpt_decrease, 1),
        "consec_westerly": max_consec,
        "peak_time_utc": str(peak_time),
    }


# ---------------------------------------------------------------------------
# Table printing
# ---------------------------------------------------------------------------

def print_candidate_table(
    candidates: list[dict[str, Any]],
    columns: list[tuple[str, str, int]] | None = None,
    max_rows: int = 15,
) -> None:
    """Print a formatted table of ranked candidate events.

    Parameters
    ----------
    candidates : list[dict]
        Ranked event dicts (as returned by ``scan_events``).
    columns : list of (key, header, width) tuples, optional
        Column definitions. If ``None``, auto-detects from the first
        candidate's keys.
    max_rows : int
        Maximum rows to display (default 15).
    """
    if not candidates:
        print("\n  No qualifying events found.")
        return

    if columns is None:
        columns = _auto_columns(candidates[0])

    # Header
    header = f"  {'Rank':<5}"
    for _key, label, width in columns:
        header += f" {label:<{width}}"
    print(f"\n{header}")
    print("  " + "-" * (len(header) - 2))

    # Rows
    for i, c in enumerate(candidates[:max_rows], 1):
        row = f"  {i:<5}"
        for key, _label, width in columns:
            val = c.get(key, "")
            row += f" {str(val):<{width}}"
        print(row)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalise_date(date_val: Any) -> datetime.date:
    """Coerce various date representations to ``datetime.date``."""
    if isinstance(date_val, datetime.date) and not isinstance(date_val, datetime.datetime):
        return date_val
    if hasattr(date_val, "date"):
        return date_val.date()
    return date_val


def _max_consecutive_in_range(
    values: list[float],
    value_range: tuple[float, float],
) -> int:
    """Count the longest consecutive run of values within *value_range*."""
    lo, hi = value_range
    max_run = 0
    current = 0
    for v in values:
        if lo <= v <= hi:
            current += 1
            max_run = max(max_run, current)
        else:
            current = 0
    return max_run


def _auto_columns(sample: dict) -> list[tuple[str, str, int]]:
    """Generate column specs from a sample candidate dict."""
    cols = []
    for key in sample:
        label = key.replace("_", " ").title()
        width = max(len(label), len(str(sample[key]))) + 2
        cols.append((key, label, width))
    return cols

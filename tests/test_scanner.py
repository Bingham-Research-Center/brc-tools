"""Tests for brc_tools.obs.scanner criteria functions."""

import datetime

import numpy as np
import polars as pl
import pytest

from brc_tools.obs.scanner import (
    _max_consecutive_in_range,
    detect_foehn,
    detect_wind_ramp,
)


# ---------------------------------------------------------------------------
# Helpers to build synthetic daily DataFrames
# ---------------------------------------------------------------------------

def _make_hourly_df(
    date: datetime.date,
    start_hour: int,
    n_hours: int,
    wind_speed: list[float],
    wind_dir: list[float],
    temp: list[float] | None = None,
    dewpoint: list[float] | None = None,
) -> pl.DataFrame:
    """Build a synthetic obs DataFrame for one day."""
    times = [
        datetime.datetime(date.year, date.month, date.day, start_hour, 0)
        + datetime.timedelta(hours=i)
        for i in range(n_hours)
    ]
    data = {
        "valid_time": times,
        "wind_speed_10m": wind_speed[:n_hours],
        "wind_dir_10m": wind_dir[:n_hours],
    }
    if temp is not None:
        data["temp_2m"] = temp[:n_hours]
    if dewpoint is not None:
        data["dewpoint_2m"] = dewpoint[:n_hours]
    return pl.DataFrame(data)


# ---------------------------------------------------------------------------
# _max_consecutive_in_range
# ---------------------------------------------------------------------------

class TestMaxConsecutive:
    def test_all_in_range(self):
        assert _max_consecutive_in_range([250, 260, 270, 280], (225, 315)) == 4

    def test_none_in_range(self):
        assert _max_consecutive_in_range([100, 120, 140], (225, 315)) == 0

    def test_broken_run(self):
        # Two runs of 2, broken by 180
        assert _max_consecutive_in_range([250, 260, 180, 270, 280], (225, 315)) == 2

    def test_empty(self):
        assert _max_consecutive_in_range([], (225, 315)) == 0


# ---------------------------------------------------------------------------
# detect_wind_ramp
# ---------------------------------------------------------------------------

class TestDetectWindRamp:
    DATE = datetime.date(2025, 4, 10)

    def test_qualifying_event(self):
        """Strong westerly ramp starting within the 22Z window."""
        df = _make_hourly_df(
            self.DATE, start_hour=22, n_hours=8,
            wind_speed=[4.0, 4.0, 6.0, 8.0, 10.0, 12.0, 11.0, 10.0],
            wind_dir=[270, 270, 270, 270, 270, 270, 270, 270],
        )
        result = detect_wind_ramp(df, self.DATE)
        assert result is not None
        assert result["date"] == str(self.DATE)
        assert result["peak_speed_ms"] == 12.0
        assert result["wind_increase"] == 8.0  # 12 - mean(4,4)
        assert result["consec_westerly_hrs"] == 8

    def test_too_slow(self):
        """Peak speed below threshold → None."""
        df = _make_hourly_df(
            self.DATE, start_hour=20, n_hours=10,
            wind_speed=[2.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 6.0, 5.0, 4.0],
            wind_dir=[270] * 10,
        )
        result = detect_wind_ramp(df, self.DATE)
        assert result is None

    def test_not_westerly(self):
        """Strong winds but from the east → None."""
        df = _make_hourly_df(
            self.DATE, start_hour=20, n_hours=10,
            wind_speed=[4.0, 4.0, 6.0, 8.0, 10.0, 12.0, 11.0, 10.0, 9.0, 8.0],
            wind_dir=[90] * 10,  # easterly
        )
        result = detect_wind_ramp(df, self.DATE)
        assert result is None

    def test_insufficient_increase(self):
        """Westerly but no meaningful ramp → None."""
        df = _make_hourly_df(
            self.DATE, start_hour=20, n_hours=10,
            wind_speed=[8.0, 8.5, 9.0, 9.5, 10.0, 10.0, 9.5, 9.0, 8.5, 8.0],
            wind_dir=[270] * 10,
        )
        result = detect_wind_ramp(df, self.DATE)
        assert result is None

    def test_too_few_rows(self):
        """Fewer than 4 obs → None."""
        df = _make_hourly_df(
            self.DATE, start_hour=22, n_hours=3,
            wind_speed=[4.0, 8.0, 12.0],
            wind_dir=[270, 270, 270],
        )
        result = detect_wind_ramp(df, self.DATE)
        assert result is None

    def test_custom_thresholds(self):
        """Custom thresholds can relax criteria."""
        df = _make_hourly_df(
            self.DATE, start_hour=22, n_hours=8,
            wind_speed=[3.0, 3.0, 4.0, 5.0, 6.0, 7.0, 6.5, 6.0],
            wind_dir=[270] * 8,
        )
        # Default thresholds → None (peak 7 < 8, increase 4 < 5)
        assert detect_wind_ramp(df, self.DATE) is None
        # Relaxed → passes
        result = detect_wind_ramp(
            df, self.DATE,
            min_peak_speed_ms=6.0,
            min_increase_ms=3.0,
        )
        assert result is not None


# ---------------------------------------------------------------------------
# detect_foehn
# ---------------------------------------------------------------------------

class TestDetectFoehn:
    DATE = datetime.date(2025, 6, 15)

    def test_qualifying_foehn(self):
        """Classic foehn: westerly ramp + warming + drying."""
        n = 12
        df = _make_hourly_df(
            self.DATE, start_hour=18, n_hours=n,
            wind_speed=[3.0, 3.0, 3.0, 5.0, 7.0, 9.0, 11.0, 10.0, 9.0, 8.0, 7.0, 6.0],
            wind_dir=[180, 180, 270, 270, 270, 270, 270, 270, 270, 270, 180, 180],
            temp=[15.0, 15.0, 15.0, 16.0, 17.5, 19.0, 20.0, 19.5, 19.0, 18.5, 18.0, 17.5],
            dewpoint=[8.0, 8.0, 8.0, 7.0, 5.5, 4.0, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5],
        )
        result = detect_foehn(df, self.DATE)
        assert result is not None
        assert result["date"] == str(self.DATE)
        assert result["foehn_score"] > 0
        assert result["temp_increase_C"] >= 2.0
        assert result["dewpt_decrease_C"] >= 2.0

    def test_no_warming(self):
        """Strong westerly + drying but no warming → None."""
        n = 10
        df = _make_hourly_df(
            self.DATE, start_hour=18, n_hours=n,
            wind_speed=[3.0, 3.0, 3.0, 5.0, 7.0, 9.0, 11.0, 10.0, 9.0, 8.0],
            wind_dir=[270] * n,
            temp=[15.0, 15.0, 15.0, 15.0, 15.0, 15.0, 15.0, 15.0, 15.0, 15.0],
            dewpoint=[8.0, 8.0, 8.0, 6.0, 4.0, 2.0, 1.0, 1.5, 2.0, 2.5],
        )
        result = detect_foehn(df, self.DATE)
        assert result is None

    def test_no_drying(self):
        """Strong westerly + warming but no drying → None."""
        n = 10
        df = _make_hourly_df(
            self.DATE, start_hour=18, n_hours=n,
            wind_speed=[3.0, 3.0, 3.0, 5.0, 7.0, 9.0, 11.0, 10.0, 9.0, 8.0],
            wind_dir=[270] * n,
            temp=[15.0, 15.0, 15.0, 16.0, 17.5, 19.0, 20.0, 19.5, 19.0, 18.5],
            dewpoint=[8.0, 8.0, 8.0, 8.0, 8.0, 8.0, 8.0, 8.0, 8.0, 8.0],
        )
        result = detect_foehn(df, self.DATE)
        assert result is None

    def test_anti_front_check(self):
        """Warming + drying but followed by sharp cooling → frontal, rejected."""
        n = 12
        df = _make_hourly_df(
            self.DATE, start_hour=18, n_hours=n,
            wind_speed=[3.0, 3.0, 3.0, 5.0, 7.0, 9.0, 11.0, 10.0, 9.0, 8.0, 7.0, 6.0],
            wind_dir=[180, 180, 270, 270, 270, 270, 270, 270, 270, 270, 180, 180],
            temp=[15.0, 15.0, 15.0, 16.0, 17.5, 19.0, 20.0, 18.0, 14.0, 11.0, 10.0, 9.0],
            dewpoint=[8.0, 8.0, 8.0, 7.0, 5.5, 4.0, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5],
        )
        result = detect_foehn(df, self.DATE)
        # Post-peak drop is 20 - 9 = 11 > 6 → rejected
        assert result is None

    def test_missing_columns(self):
        """Missing temp/dewpoint columns → None."""
        df = _make_hourly_df(
            self.DATE, start_hour=18, n_hours=10,
            wind_speed=[3.0] * 10,
            wind_dir=[270] * 10,
        )
        result = detect_foehn(df, self.DATE)
        assert result is None

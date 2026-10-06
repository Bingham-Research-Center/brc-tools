"""Sun times and night windows (``brc_tools.utils.solar``)."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from brc_tools.utils.solar import nights, solar_position, sun_times

VERNAL = (40.455, -109.53)


def test_noon_sun_is_overhead_at_the_equator_on_the_equinox():
    elev, _ = solar_position(datetime(2025, 3, 20, 12, 7), 0.0, 0.0)
    assert elev > 89.0


def test_azimuth_runs_east_to_west_through_south_in_the_northern_winter():
    _, az_morning = solar_position(datetime(2025, 1, 27, 16, 0), *VERNAL)   # 09 MST
    elev_noon, az_noon = solar_position(datetime(2025, 1, 27, 19, 30), *VERNAL)
    _, az_evening = solar_position(datetime(2025, 1, 27, 23, 0), *VERNAL)   # 16 MST
    assert 90 < az_morning < 180 < az_evening < 270
    assert abs(az_noon - 180) < 5
    assert 29 < elev_noon < 32            # 90 - 40.455 - 18.5 deg declination


def test_sun_times_are_on_the_utc_day_asked_for():
    rise, set_ = sun_times(date(2025, 1, 27), *VERNAL)
    # the sunset found on UTC 27 Jan is the evening of LOCAL 26 Jan (17:30 MST)
    assert abs((set_ - datetime(2025, 1, 27, 0, 30)).total_seconds()) <= 60
    assert abs((rise - datetime(2025, 1, 27, 14, 32)).total_seconds()) <= 60


def test_nights_pair_each_sunset_with_the_first_sunrise_after_it():
    out = nights(date(2025, 1, 26), date(2025, 1, 27), *VERNAL)
    assert [label for label, _, _ in out] == ["2025-01-26", "2025-01-27"]
    (_, ss1, sr1), (_, ss2, sr2) = out
    assert abs((ss1 - datetime(2025, 1, 27, 0, 30)).total_seconds()) <= 60
    assert abs((sr1 - datetime(2025, 1, 27, 14, 32)).total_seconds()) <= 60
    assert abs((ss2 - datetime(2025, 1, 28, 0, 31)).total_seconds()) <= 60
    assert sr1 < ss2 < sr2


@pytest.mark.parametrize("day, hours", [(date(2025, 1, 26), 14.0), (date(2025, 9, 8), 11.2), (date(2025, 6, 21), 9.0),
                                        (date(2025, 11, 21), 14.3), (date(2023, 12, 25), 14.6)])
def test_no_38_hour_nights(day, hours):
    """Regression: pairing the sunset of UTC day d with the sunrise of UTC day d + 1 made
    January and September nights 38 h long (found 2026-09-15 in a case-study table)."""
    (label, sunset, sunrise), = nights(day, day, *VERNAL)
    length = (sunrise - sunset).total_seconds() / 3600.0
    assert label == day.isoformat()
    assert length == pytest.approx(hours, abs=0.35)
    assert (sunset + timedelta(hours=-7)).date() == day        # labelled by the LOCAL date of the sunset


def test_a_window_of_days_gives_one_night_each_in_order():
    out = nights(date(2025, 1, 24), date(2025, 1, 29), *VERNAL)
    assert len(out) == 6
    for (_, ss_a, sr_a), (_, ss_b, _) in zip(out, out[1:]):
        assert ss_a < sr_a < ss_b
        assert 23.9 < (ss_b - ss_a).total_seconds() / 3600.0 < 24.1


def test_datetimes_are_read_as_their_calendar_day():
    """Regression: a datetime compared unequal to every date, so a window given as datetimes
    came back with no nights at all and a figure lost its night shading without an error."""
    as_dates = nights(date(2025, 1, 24), date(2025, 1, 29), *VERNAL)
    as_datetimes = nights(datetime(2025, 1, 24, 0), datetime(2025, 1, 29, 12), *VERNAL)
    assert as_datetimes == as_dates and len(as_datetimes) == 6

"""Sun times and night windows (``brc_tools.utils.solar``)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from brc_tools.utils.solar import nights, solar_position, sun_times

VERNAL = (40.455, -109.53)

# Sunset of each local (MST) evening 10 Nov .. 20 Dec 2025 at VERNAL and the sunrise after it,
# UTC, "MM-DD HH:MM:SS sunset  MM-DD HH:MM:SS sunrise", in pairs of nights per line. Derived
# offline with the independent ``astral`` 3.2 package (Observer(40.455, -109.53), sunset of
# local date d and sunrise of d + 1 at UTC-7); astral is not a test dependency. Note the
# sixth and seventh sunsets: both fall on UTC 16 November.
ASTRAL_NOV_DEC_2025 = """
    11-11 00:04:27 11-11 14:00:21   11-12 00:03:31 11-12 14:01:31
    11-13 00:02:37 11-13 14:02:41   11-14 00:01:45 11-14 14:03:52
    11-15 00:00:54 11-15 14:05:01   11-16 00:00:05 11-16 14:06:11
    11-16 23:59:19 11-17 14:07:21   11-17 23:58:34 11-18 14:08:30
    11-18 23:57:51 11-19 14:09:39   11-19 23:57:10 11-20 14:10:47
    11-20 23:56:31 11-21 14:11:56   11-21 23:55:55 11-22 14:13:03
    11-22 23:55:20 11-23 14:14:10   11-23 23:54:47 11-24 14:15:17
    11-24 23:54:17 11-25 14:16:23   11-25 23:53:48 11-26 14:17:28
    11-26 23:53:22 11-27 14:18:32   11-27 23:52:58 11-28 14:19:36
    11-28 23:52:37 11-29 14:20:39   11-29 23:52:17 11-30 14:21:41
    11-30 23:52:00 12-01 14:22:42   12-01 23:51:45 12-02 14:23:42
    12-02 23:51:32 12-03 14:24:41   12-03 23:51:21 12-04 14:25:39
    12-04 23:51:13 12-05 14:26:35   12-05 23:51:07 12-06 14:27:31
    12-06 23:51:03 12-07 14:28:25   12-07 23:51:02 12-08 14:29:18
    12-08 23:51:03 12-09 14:30:09   12-09 23:51:06 12-10 14:30:59
    12-10 23:51:11 12-11 14:31:47   12-11 23:51:19 12-12 14:32:34
    12-12 23:51:29 12-13 14:33:20   12-13 23:51:41 12-14 14:34:03
    12-14 23:51:55 12-15 14:34:45   12-15 23:52:12 12-16 14:35:25
    12-16 23:52:31 12-17 14:36:04   12-17 23:52:52 12-18 14:36:40
    12-18 23:53:15 12-19 14:37:15   12-19 23:53:40 12-20 14:37:47
    12-20 23:54:08 12-21 14:38:18
"""


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


def test_aware_datetimes_are_converted_to_utc():
    """Regression: the hour was read off the datetime as given, so 12:30 in Denver was taken
    as 12:30 UTC and the noon sun came out 23 degrees below the horizon."""
    noon_mst = datetime(2025, 1, 27, 12, 30, tzinfo=ZoneInfo("America/Denver"))
    as_utc = solar_position(datetime(2025, 1, 27, 19, 30), *VERNAL)
    assert solar_position(noon_mst, *VERNAL) == as_utc
    assert solar_position(datetime(2025, 1, 27, 19, 30, tzinfo=timezone.utc), *VERNAL) == as_utc
    assert as_utc[0] == pytest.approx(31.33, abs=0.05)                  # astral: 31.335


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


def test_no_night_is_lost_when_sunset_crosses_00_utc_while_getting_earlier():
    """Regression: searched per UTC day, the sunset of local 16 Nov 2025 (23:59 UTC) shared a
    UTC day with that of local 15 Nov (00:00 UTC); only the first was kept and the night of the
    16th vanished, every November. Each of 41 nights must appear once, in order, and agree with
    an independent ephemeris: the crossing is the first whole minute past the horizon (up to
    60 s late) and the two algorithms differ by up to ~20 s."""
    out = nights(date(2025, 11, 10), date(2025, 12, 20), *VERNAL)
    labels = [date.fromisoformat(label) for label, _, _ in out]
    assert labels == [date(2025, 11, 10) + timedelta(days=k) for k in range(41)]
    stamps = ASTRAL_NOV_DEC_2025.split()
    expected = [(datetime.strptime(f"2025-{stamps[k]} {stamps[k + 1]}", "%Y-%m-%d %H:%M:%S"),
                 datetime.strptime(f"2025-{stamps[k + 2]} {stamps[k + 3]}", "%Y-%m-%d %H:%M:%S"))
                for k in range(0, len(stamps), 4)]
    assert len(expected) == 41
    for (label, sunset, sunrise), (ss_ref, sr_ref) in zip(out, expected, strict=True):
        assert abs((sunset - ss_ref).total_seconds()) <= 90, label
        assert abs((sunrise - sr_ref).total_seconds()) <= 90, label
        assert (sunset + timedelta(hours=-7)).date().isoformat() == label

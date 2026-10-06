"""Sun position, sunrise/sunset and night windows (NOAA Solar Calculator algorithm, after Meeus).

UTC-naive datetimes in, UTC-naive datetimes out; the caller converts to local time at the
display boundary. A naive datetime is read as UTC; an aware one is converted to UTC first
(the arithmetic reads ``dt.hour``, so 12:30 in Denver taken at face value would be the sun
of 12:30 UTC, seven hours early). Pure stdlib, so it imports anywhere.

The function that matters for drainage work is :func:`nights`: it pairs each sunset with
the *first sunrise after it*, labelled by the local calendar date of the evening it falls
in. Pairing by UTC calendar day instead -- the sunset of UTC day *d* with the sunrise of UTC
day *d + 1* -- gives 38-hour "nights" wherever local sunset falls after 00 UTC (January and
September in Utah), which once inflated every night-mean in a case study. Searching per UTC
day at all loses a night whenever sunset crosses 00 UTC while getting *earlier* (every
November in Utah): that UTC day holds two sunsets and only the first was kept.
``tests/test_utils_solar.py`` keeps both from coming back.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone

__all__ = ["solar_position", "sun_times", "nights"]

# The sun's elevation can change no faster than its angular speed across the sky, 15 deg
# per hour = 0.25 deg per minute; a little margin covers the drift in declination.
_MAX_RATE_DEG_PER_MIN = 0.26
_COARSE_STEP_MIN = 10


def _utc_naive(dt: datetime) -> datetime:
    """``dt`` as a naive UTC datetime: aware ones converted, naive ones taken as UTC already."""
    if dt.tzinfo is not None and dt.utcoffset() is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _julian_day(dt: datetime) -> float:
    return dt.toordinal() + 1721424.5 + (dt.hour + dt.minute / 60 + dt.second / 3600) / 24.0


def solar_position(dt: datetime, lat: float, lon: float) -> tuple[float, float]:
    """``(elevation_deg, azimuth_deg)`` of the sun at a datetime; azimuth clockwise from north.

    A naive ``dt`` is UTC; an aware one is converted to UTC first.
    """
    dt = _utc_naive(dt)
    jd = _julian_day(dt)
    t = (jd - 2451545.0) / 36525.0
    mean_long = (280.46646 + t * (36000.76983 + 0.0003032 * t)) % 360
    mean_anom = 357.52911 + t * (35999.05029 - 0.0001537 * t)
    ecc = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    m_r = math.radians(mean_anom)
    centre = (math.sin(m_r) * (1.914602 - t * (0.004817 + 0.000014 * t))
              + math.sin(2 * m_r) * (0.019993 - 0.000101 * t) + math.sin(3 * m_r) * 0.000289)
    true_long = mean_long + centre
    omega = 125.04 - 1934.136 * t
    app_long = true_long - 0.00569 - 0.00478 * math.sin(math.radians(omega))
    obliq0 = 23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60) / 60
    obliq = obliq0 + 0.00256 * math.cos(math.radians(omega))
    decl = math.degrees(math.asin(math.sin(math.radians(obliq)) * math.sin(math.radians(app_long))))
    y = math.tan(math.radians(obliq / 2)) ** 2
    l0_r = math.radians(mean_long)
    eq_time = 4 * math.degrees(y * math.sin(2 * l0_r) - 2 * ecc * math.sin(m_r)
                               + 4 * ecc * y * math.sin(m_r) * math.cos(2 * l0_r)
                               - 0.5 * y * y * math.sin(4 * l0_r) - 1.25 * ecc * ecc * math.sin(2 * m_r))
    minutes = dt.hour * 60 + dt.minute + dt.second / 60
    true_solar = (minutes + eq_time + 4 * lon) % 1440
    hour_angle = true_solar / 4 - 180 if true_solar / 4 >= 0 else true_solar / 4 + 180
    lat_r, decl_r, ha_r = map(math.radians, (lat, decl, hour_angle))
    cos_zen = math.sin(lat_r) * math.sin(decl_r) + math.cos(lat_r) * math.cos(decl_r) * math.cos(ha_r)
    zen = math.degrees(math.acos(max(-1.0, min(1.0, cos_zen))))
    zen_r = math.radians(zen)
    denom = math.cos(lat_r) * math.sin(zen_r)
    if abs(denom) < 1e-12:
        return 90 - zen, 0.0
    az = math.degrees(math.acos(max(-1.0, min(1.0, (math.sin(lat_r) * math.cos(zen_r) - math.sin(decl_r)) / denom))))
    az = (az + 180) % 360 if hour_angle > 0 else (540 - az) % 360
    return 90 - zen, az


def _first_crossing(t0: datetime, minutes: int, lat: float, lon: float, elevation_deg: float, *,
                    rising: bool) -> datetime | None:
    """The first whole minute ``t0 + k`` (``1 <= k <= minutes``) at which the elevation crosses
    ``elevation_deg`` upward (``rising``) or downward, or ``None``.

    The answer is exactly that of a one-minute scan -- the crossing is the first minute on
    the far side of the threshold -- but most of the window is stepped in 10-minute blocks:
    a block whose two ends are further from the threshold, together, than the sun can travel
    in it cannot contain a crossing, so only blocks near the horizon are scanned minute by
    minute. That is what makes a year of nights take a second rather than half a minute.
    """
    def elev(k: int) -> float:
        return solar_position(t0 + timedelta(minutes=k), lat, lon)[0]

    a, e_a = 0, elev(0)
    while a < minutes:
        b = min(a + _COARSE_STEP_MIN, minutes)
        e_b = elev(b)
        if abs(e_a - elevation_deg) + abs(e_b - elevation_deg) <= _MAX_RATE_DEG_PER_MIN * (b - a):
            prev = e_a
            for k in range(a + 1, b + 1):
                e = e_b if k == b else elev(k)
                if (prev < elevation_deg <= e) if rising else (prev >= elevation_deg > e):
                    return t0 + timedelta(minutes=k)
                prev = e
        a, e_a = b, e_b
    return None


def sun_times(day: date, lat: float, lon: float, *, elevation_deg: float = -0.833) -> tuple[datetime | None, datetime | None]:
    """``(sunrise_utc, sunset_utc)`` falling on a **UTC** calendar day, to the minute.

    The first whole minute on the far side of the horizon, as a one-minute scan of the
    solar elevation would find it, so there are no refraction or polar edge cases to
    special-case; either may be ``None`` (no crossing on that UTC day). ``elevation_deg`` is
    the centre-of-disc elevation that counts as the horizon (-0.833 = upper limb with
    standard refraction). For nights, use :func:`nights`, not pairs of UTC days.
    """
    t0 = datetime(day.year, day.month, day.day)
    rise = _first_crossing(t0, 24 * 60, lat, lon, elevation_deg, rising=True)
    set_ = _first_crossing(t0, 24 * 60, lat, lon, elevation_deg, rising=False)
    return rise, set_


def nights(start: date, end: date, lat: float, lon: float, *, utc_offset_h: float = -7.0,
           elevation_deg: float = -0.833) -> list[tuple[str, datetime, datetime]]:
    """``[(label, sunset_utc, next_sunrise_utc)]``, one per night, for the local evenings
    ``start..end`` (dates, or datetimes whose calendar day is used); ``label`` is the local
    date of that evening (ISO).

    The sunset of local day *d* is the first one after local noon of *d* and before local
    noon of *d + 1*: one continuous 24-hour window per local day, so every sunset falls in
    exactly one window and no night is lost or counted twice however the sunset sits
    against 00 UTC -- provided ``utc_offset_h`` is roughly the site's solar zone, so that
    local noon is far from any sunset. An offset hours off (or a polar site whose sunset
    comes near local noon) can put two sunsets in one window and lose the second. Wherever the sun sets before local midnight (everywhere outside a
    polar summer) the label is simply the local date of the sunset. The sunrise is the
    first one after that sunset (within 48 h; none -- a polar night -- drops the night).

    ``utc_offset_h`` is the fixed local-time offset that places local noon (MST = -7 for
    Utah all year, which is solar time there, not the wall clock in summer).
    """
    out = []
    off = timedelta(hours=utc_offset_h)
    # a datetime is a date too, but it never equals one: take the calendar day of either
    d = start.date() if isinstance(start, datetime) else start
    end = end.date() if isinstance(end, datetime) else end
    while d <= end:
        # local noon of d in UTC, on whole minutes so the crossings land on the same minute
        # grid as sun_times
        noon = (datetime(d.year, d.month, d.day, 12) - off).replace(second=0, microsecond=0)
        sunset = _first_crossing(noon, 24 * 60, lat, lon, elevation_deg, rising=False)
        if sunset is not None:
            sunrise = _first_crossing(sunset, 48 * 60, lat, lon, elevation_deg, rising=True)
            if sunrise is not None:
                out.append((d.strftime("%Y-%m-%d"), sunset, sunrise))
        d += timedelta(days=1)
    return out

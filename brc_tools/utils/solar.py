"""Sun position, sunrise/sunset and night windows (NOAA Solar Calculator algorithm, after Meeus).

UTC-naive datetimes in, UTC-naive datetimes out; the caller converts to local time at the
display boundary. Pure stdlib, so it imports anywhere.

The function that matters for drainage work is :func:`nights`: it pairs each sunset with
the *first sunrise after it*, labelled by the local calendar date of the sunset. Pairing by
UTC calendar day instead -- the sunset of UTC day *d* with the sunrise of UTC day *d + 1* --
gives 38-hour "nights" wherever local sunset falls after 00 UTC (January and September in
Utah), which once inflated every night-mean in a case study. ``tests/test_utils_solar.py``
keeps that from coming back.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta

__all__ = ["solar_position", "sun_times", "nights"]


def _julian_day(dt: datetime) -> float:
    return dt.toordinal() + 1721424.5 + (dt.hour + dt.minute / 60 + dt.second / 3600) / 24.0


def solar_position(dt: datetime, lat: float, lon: float) -> tuple[float, float]:
    """``(elevation_deg, azimuth_deg)`` of the sun at a UTC datetime; azimuth clockwise from north."""
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


def sun_times(day: date, lat: float, lon: float, *, elevation_deg: float = -0.833) -> tuple[datetime | None, datetime | None]:
    """``(sunrise_utc, sunset_utc)`` falling on a **UTC** calendar day, to the minute.

    Found by scanning the solar elevation at one-minute steps, so there are no refraction or
    polar edge cases to special-case; either may be ``None`` (no crossing on that UTC day).
    ``elevation_deg`` is the centre-of-disc elevation that counts as the horizon
    (-0.833 = upper limb with standard refraction).
    """
    t0 = datetime(day.year, day.month, day.day)
    prev = None
    rise = set_ = None
    for k in range(0, 24 * 60 + 1):
        t = t0 + timedelta(minutes=k)
        el, _ = solar_position(t, lat, lon)
        if prev is not None:
            if prev < elevation_deg <= el and rise is None:
                rise = t
            if prev >= elevation_deg > el and set_ is None:
                set_ = t
        prev = el
    return rise, set_


def nights(start: date, end: date, lat: float, lon: float, *, utc_offset_h: float = -7.0,
           elevation_deg: float = -0.833) -> list[tuple[str, datetime, datetime]]:
    """``[(label, sunset_utc, next_sunrise_utc)]`` for every night whose sunset falls on the
    **local** calendar day ``start..end`` (dates, or datetimes whose calendar day is used);
    ``label`` is that local date (ISO).

    ``utc_offset_h`` is the fixed local-time offset used only to assign the label (MST = -7
    for Utah all year, which is solar time there, not the wall clock in summer). The sunset
    of local day *d* can sit on UTC day *d* or *d + 1*, so both are searched and the one
    whose local date is *d* is taken; the sunrise is the first one after that sunset.
    """
    out = []
    off = timedelta(hours=utc_offset_h)
    # a datetime is a date too, but it never equals one: take the calendar day of either
    d = start.date() if isinstance(start, datetime) else start
    end = end.date() if isinstance(end, datetime) else end
    while d <= end:
        sunset = None
        for dd in (d, d + timedelta(days=1)):
            _, s_ = sun_times(dd, lat, lon, elevation_deg=elevation_deg)
            if s_ is not None and (s_ + off).date() == d:
                sunset = s_
                break
        if sunset is not None:
            sunrise = None
            for dd in (sunset.date(), sunset.date() + timedelta(days=1)):
                r_, _ = sun_times(dd, lat, lon, elevation_deg=elevation_deg)
                if r_ is not None and r_ > sunset:
                    sunrise = r_
                    break
            if sunrise is not None:
                out.append((d.strftime("%Y-%m-%d"), sunset, sunrise))
        d += timedelta(days=1)
    return out

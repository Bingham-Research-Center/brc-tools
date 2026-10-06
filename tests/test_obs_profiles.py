"""Stations as profiles and the drainage signal at a mouth (``brc_tools.obs.profiles``)."""

from __future__ import annotations

import warnings
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from brc_tools.obs import profiles as op


def test_feet_and_standard_pressure():
    assert op.feet_to_m(5280.0) == pytest.approx(1609.344)
    assert op.standard_pressure_hpa(0.0) == pytest.approx(1013.25)
    assert op.standard_pressure_hpa(1600.0) == pytest.approx(835.2, abs=0.6)
    assert op.altimeter_to_station_pressure_hpa(1013.25, 1600.0) == pytest.approx(op.standard_pressure_hpa(1600.0))


def test_pressure_fit_recovers_a_hydrostatic_atmosphere_and_rejects_sea_level_reports():
    rng = np.random.default_rng(0)
    z = np.array([1420.0, 1500, 1610, 1700, 1850, 2100, 2400, 2800, 3200, 3600])
    p_true = 860.0 * np.exp(-(z - 1420.0) / 7600.0)
    p = p_true + rng.normal(0, 0.3, z.size)
    p[4] = 1024.0                      # a sea-level pressure filed as station pressure
    fit = op.fit_pressure_height(z, p)
    assert fit.n == z.size - 1
    assert fit.scale_height_m == pytest.approx(7600.0, rel=0.03)
    assert np.max(np.abs(op.pressure_at(z, fit) - p_true)) < 0.8
    assert fit.rms_hpa < 0.6


def test_pressure_fit_falls_back_to_the_standard_slope_with_too_few_stations():
    z = np.array([1500.0, 1600.0])
    p = op.standard_pressure_hpa(z) * 1.01
    fit = op.fit_pressure_height(z, p)
    assert fit.n == 2 and np.isnan(fit.rms_hpa)
    assert op.pressure_at(1550.0, fit) == pytest.approx(op.standard_pressure_hpa(1550.0) * 1.01, rel=2e-3)
    with pytest.warns(UserWarning, match="standard atmosphere"):
        empty = op.fit_pressure_height(z, [np.nan, np.nan])
    assert empty.n == 0
    assert op.pressure_at(2000.0, empty) == pytest.approx(op.standard_pressure_hpa(2000.0), rel=2e-3)



def test_pressure_in_pa_is_refused_not_silently_misread():
    """Regression: Synoptic gives Pa. Passed as hPa, every report failed the 3 % check, the
    fit fell back to the standard atmosphere without a word, and a heat deficit given the
    same pressures came out 27 times too large."""
    z = np.array([1420.0, 1500, 1610, 1700, 1850, 2100])
    p_hpa = 860.0 * np.exp(-(z - 1420.0) / 7600.0)
    with pytest.raises(ValueError, match="Pa"):
        op.fit_pressure_height(z, p_hpa * 100.0)
    with pytest.raises(ValueError, match="Pa"):
        op.potential_temperature(-5.0, 85000.0)
    theta = np.where(z < 2000.0, 280.0, 285.0)
    with pytest.raises(ValueError, match="Pa"):
        op.heat_deficit(z, theta, z_ref_m=2000.0, pressure_hpa=p_hpa * 100.0)
    # hPa, including a sea-level pressure filed as station pressure, is still accepted
    assert op.fit_pressure_height(z, np.r_[p_hpa[:-1], 1024.0]).n == z.size - 1
    assert op.heat_deficit(z, theta, z_ref_m=2000.0, pressure_hpa=p_hpa) is not None


def test_pressure_fit_warns_only_when_nothing_usable_is_left():
    z = np.array([1500.0, 1600.0, 1700.0])
    with pytest.warns(UserWarning, match="no usable station pressure"):
        op.fit_pressure_height(z, [1024.0, 1023.0, np.nan])           # all sea-level: all rejected
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        op.fit_pressure_height(z, op.standard_pressure_hpa(z))         # a fallback with n = 3 is quiet

def test_potential_temperature():
    assert op.potential_temperature(0.0, 1000.0) == pytest.approx(273.15)
    # a dry adiabat: T falls 9.8 K per km, theta does not
    z = np.array([1500.0, 2500.0])
    p = 850.0 * (1 - 9.8e-3 * (z - 1500.0) / 280.0) ** (1004.0 / 287.05)
    t_c = 280.0 - 9.8e-3 * (z - 1500.0) - 273.15
    theta = op.potential_temperature(t_c, p)
    assert theta[0] == pytest.approx(theta[1], abs=0.05)


def test_wind_components_and_sectors():
    u, v = op.wind_components(10.0, 270.0)
    assert u == pytest.approx(10.0) and v == pytest.approx(0.0, abs=1e-9)
    assert op.in_sector([350, 10, 180, 290, 20], 290, 20).tolist() == [True, True, False, True, True]
    assert op.in_sector([100, 250, np.nan], 150, 250).tolist() == [False, True, False]
    # a channel running toward the south-east (azimuth 121) drains with a north-westerly
    lo, hi = op.sector_from_azimuth(121.0, half_width=40.0)
    assert (lo, hi) == (261.0, 341.0)
    assert op.sector_from_azimuth(170.0, 30.0) == (320.0, 20.0)


def test_pseudo_profile_bins_by_elevation():
    z = np.array([1450.0, 1480, 1530, 1560, 2040, 2060, 2090, np.nan])
    v = np.array([270.0, 272, 274, 276, 285, 286, 287, 300])
    prof = op.pseudo_profile(z, v, bin_m=100.0)
    assert prof["z"].tolist() == [1450.0, 1550.0, 2050.0]
    assert prof["n"].tolist() == [2, 2, 3]
    assert prof["median"].tolist() == [271.0, 275.0, 286.0]
    assert op.pseudo_profile(z, v, bin_m=100.0, min_count=3)["z"].tolist() == [2050.0]


def test_pseudo_profile_keeps_a_station_on_an_exact_bin_edge():
    """Regression: the top edge was rounded up with ceil, so a highest station at an exact
    multiple of bin_m sat ON it, past the last half-open bin, and the rim station -- the
    reference level -- vanished from the profile."""
    prof = op.pseudo_profile([1450.0, 1520.0, 2100.0], [270.0, 272.0, 285.0], bin_m=100.0)
    assert prof["z"].tolist() == [1450.0, 1550.0, 2150.0]           # half-open: 2100 opens [2100, 2200)
    assert prof["n"].tolist() == [1, 1, 1] and prof["median"][-1] == 285.0
    # an explicit z_max is the excluded top of the range, as before
    assert op.pseudo_profile([1450.0, 2100.0], [270.0, 285.0], bin_m=100.0, z_max=2100.0)["z"].tolist() == [1450.0]


def test_two_layer_fit_finds_the_pool_top():
    rng = np.random.default_rng(1)
    z = np.sort(rng.uniform(1420.0, 3200.0, 60))
    z_top = 1800.0
    theta = np.where(z < z_top, 276.0 + 0.020 * (z - z_top), 276.0 + 0.004 * (z - z_top)) + rng.normal(0, 0.15, z.size)
    fit = op.two_layer_fit(z, theta)
    assert fit is not None and fit.n == 60
    assert fit.z_top_m == pytest.approx(z_top, abs=60.0)
    assert fit.lower_k_per_km == pytest.approx(20.0, rel=0.15)
    assert fit.upper_k_per_km == pytest.approx(4.0, rel=0.2)
    assert fit.deficit_k == pytest.approx(0.020 * (z_top - z.min()), rel=0.2)
    assert op.two_layer_fit(z[:4], theta[:4]) is None


def test_count_surges():
    s = np.array([0.2, 0.3, 0.2, 1.6, 2.0, 1.8, 0.4, 0.3, 0.2, 2.4, 2.5, 0.5, np.nan, 0.2, 0.3])
    assert op.count_surges(s, rise=1.0) == 2
    assert op.count_surges(np.full(20, 1.5), rise=1.0) == 0
    assert op.count_surges(np.linspace(0, 0.8, 20), rise=1.0) == 0


def _series(sunset, minutes, speed, direction):
    t = np.array([np.datetime64(sunset + timedelta(minutes=int(m)), "s") for m in minutes])
    return t, np.asarray(speed, dtype=float), np.asarray(direction, dtype=float)


def test_drainage_metrics_onset_fraction_and_along_component():
    sunset, sunrise = datetime(2025, 1, 27, 0, 30), datetime(2025, 1, 27, 14, 30)
    minutes = np.arange(-180, 14 * 60 + 1, 10)
    onset_min = 40
    speed = np.where(minutes < onset_min, 1.0, 2.0)
    direction = np.where(minutes < onset_min, 120.0, 310.0)       # up-valley, then from the north-west
    t, s, d = _series(sunset, minutes, speed, direction)
    night = op.drainage_metrics(t, s, d, (280.0, 340.0), sunset=sunset, sunrise=sunrise)
    n_night = int(((minutes >= 0) & (minutes <= 14 * 60)).sum())
    assert night.n_obs == n_night
    assert night.onset_min_after_sunset == pytest.approx(onset_min)
    assert night.fraction_down == pytest.approx((n_night - 4) / n_night)
    assert night.mean_speed == pytest.approx(2.0)
    assert night.duration_h == pytest.approx((n_night - 4) * 10 / 60.0)
    assert 1.7 < night.mean_along < 2.0
    assert night.calm_fraction == 0.0


def test_drainage_metrics_onset_before_sunset_and_calm_handling():
    sunset, sunrise = datetime(2025, 1, 27, 0, 30), datetime(2025, 1, 27, 14, 30)
    minutes = np.arange(-180, 14 * 60 + 1, 10)
    speed = np.where(minutes % 60 == 0, 0.1, 1.5)                 # one calm report an hour
    direction = np.where(minutes % 60 == 0, np.nan, 300.0)        # calm reports carry no direction
    direction = np.where(minutes < -60, 110.0, direction)
    t, s, d = _series(sunset, minutes, speed, direction)
    night = op.drainage_metrics(t, s, d, (270.0, 330.0), sunset=sunset, sunrise=sunrise, run=3)
    assert night.onset_min_after_sunset < 0                       # the shaded canyon starts early
    assert night.calm_fraction == pytest.approx(15 / 85, abs=0.01)
    assert night.fraction_down == pytest.approx(70 / 85, abs=0.01)
    assert op.drainage_metrics(t[:3], s[:3], d[:3], (270.0, 330.0), sunset=sunset, sunrise=sunrise) is None



def test_calm_reports_without_direction_add_nothing_to_the_along_component():
    """Regression: a calm with NaN direction was projected as wind FROM the north (0 deg), so
    every calm report pulled mean_along toward a northerly."""
    sunset, sunrise = datetime(2025, 1, 27, 0, 30), datetime(2025, 1, 27, 14, 30)
    minutes = np.arange(0, 14 * 60 + 1, 10)
    calm = minutes % 20 == 0
    speed = np.where(calm, 0.25, 2.0)
    direction = np.where(calm, np.nan, 90.0)          # moving air blows straight across a N-S valley
    t, s, d = _series(sunset, minutes, speed, direction)
    night = op.drainage_metrics(t, s, d, (150.0, 210.0), sunset=sunset, sunrise=sunrise)
    assert night.calm_fraction == pytest.approx(calm.mean())
    assert night.mean_along == pytest.approx(0.0, abs=1e-12)      # was -0.25 * calm fraction


def test_aware_times_are_read_as_utc_once_and_quietly():
    """Regression: aware datetimes went to numpy one by one, a UserWarning per element."""
    sunset, sunrise = datetime(2025, 1, 27, 0, 30), datetime(2025, 1, 27, 14, 30)
    minutes = np.arange(-180, 14 * 60 + 1, 10)
    speed = np.where(minutes < 40, 1.0, 2.0)
    direction = np.where(minutes < 40, 120.0, 310.0)
    t, s, d = _series(sunset, minutes, speed, direction)
    naive = op.drainage_metrics(t, s, d, (280.0, 340.0), sunset=sunset, sunrise=sunrise)
    denver = ZoneInfo("America/Denver")
    as_utc = [sunset.replace(tzinfo=timezone.utc) + timedelta(minutes=int(m)) for m in minutes]
    aware = [x.astimezone(denver) for x in as_utc]
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        got = op.drainage_metrics(aware, s, d, (280.0, 340.0), sunset=sunset.replace(tzinfo=timezone.utc).astimezone(denver),
                                  sunrise=sunrise.replace(tzinfo=timezone.utc))
        cooled = op.nightly_cooling(aware, np.linspace(0.0, -10.0, minutes.size), sunset=aware[18], sunrise=as_utc[-1])
    assert got == naive
    assert cooled is not None and cooled["cooling_k"] > 0

def test_nightly_cooling():
    sunset, sunrise = datetime(2025, 1, 27, 0, 30), datetime(2025, 1, 27, 14, 30)
    minutes = np.arange(-120, 15 * 60, 10)
    temp = np.where(minutes < 0, -2.0, -2.0 - 13.0 * (1 - np.exp(-np.maximum(minutes, 0) / 240.0)))
    t, x, _ = _series(sunset, minutes, temp, temp)
    out = op.nightly_cooling(t, x, sunset=sunset, sunrise=sunrise)
    assert out["t_sunset_c"] == pytest.approx(-2.3, abs=0.4)
    assert out["cooling_k"] == pytest.approx(out["t_sunset_c"] - out["t_min_c"])
    assert out["cooling_k"] > 11.0 and out["t_min_h"] > 13.0
    assert op.nightly_cooling(t[:5], x[:5], sunset=sunset, sunrise=sunrise) is None


def test_heat_deficit_of_a_linear_pool_and_its_pressure_head():
    z = np.arange(1500.0, 3001.0, 50.0)
    theta = np.where(z < 2500.0, 290.0 - 0.010 * (2500.0 - z), 290.0 + 0.003 * (z - 2500.0))   # 10 K deficit over 1000 m
    out = op.heat_deficit(z, theta, z_ref_m=2500.0)
    assert out.theta_ref_k == pytest.approx(290.0) and out.max_deficit_k == pytest.approx(10.0)
    assert out.z_bottom_m == 1500.0 and out.z_ref_m == 2500.0
    # c_p * rho * (mean deficit 5 K) * 1000 m, with the density of cold air at 1.5-2.5 km (about 1.06 kg m-3)
    assert 4.8e6 < out.j_per_m2 < 5.6e6
    zf = np.linspace(1500.0, 2500.0, 4001)
    thf = 290.0 - 0.010 * (2500.0 - zf)
    pf = op.standard_pressure_hpa(zf)
    rho = pf * 100.0 / (287.05 * thf * (pf / 1000.0) ** (287.05 / 1004.0))
    fine = 1004.0 * float(np.sum(0.5 * (rho[1:] * (290.0 - thf[1:]) + rho[:-1] * (290.0 - thf[:-1])) * np.diff(zf)))
    assert out.j_per_m2 == pytest.approx(fine, rel=0.002)
    assert out.head_pa == pytest.approx(9.80665 * out.j_per_m2 / (1004.0 * 284.0), rel=0.03)
    # air warmer than the reference inside the layer adds nothing; a coarser profile agrees
    warm = theta.copy()
    warm[z < 1700.0] = 295.0
    assert op.heat_deficit(z, warm, z_ref_m=2500.0).j_per_m2 < out.j_per_m2
    coarse = op.heat_deficit(z[::4], theta[::4], z_ref_m=2500.0)
    assert coarse.j_per_m2 == pytest.approx(out.j_per_m2, rel=0.02)
    # the reported pressure changes the density only
    with_p = op.heat_deficit(z, theta, z_ref_m=2500.0, pressure_hpa=op.standard_pressure_hpa(z) * 1.01)
    assert with_p.j_per_m2 == pytest.approx(out.j_per_m2 * 1.01, rel=0.005)
    assert op.heat_deficit(z, theta, z_ref_m=3500.0) is None          # the profile stops short
    assert op.heat_deficit(z[:1], theta[:1], z_ref_m=1400.0) is None


def test_theta_plane_fit_separates_stratification_from_tilt():
    rng = np.random.default_rng(7)
    n = 60
    z = rng.uniform(1450.0, 2000.0, n)
    x, y = rng.uniform(-70.0, 70.0, n), rng.uniform(-40.0, 40.0, n)
    theta = 270.0 + 0.015 * (z - 1500.0) - 0.02 * x + 0.01 * y        # colder to the east and to the south
    fit = op.theta_plane_fit(z, x, y, theta + rng.normal(0.0, 0.05, n))
    assert fit.n == n and fit.rms_k < 0.1
    assert fit.k_per_km == pytest.approx(15.0, abs=0.3)
    assert fit.dtheta_dx_k_per_100km == pytest.approx(-2.0, abs=0.1) and fit.dtheta_dy_k_per_100km == pytest.approx(1.0, abs=0.1)
    assert fit.grad_k_per_100km == pytest.approx(2.236, abs=0.1)
    assert fit.cold_toward_deg == pytest.approx(116.6, abs=3.0)      # toward the east-south-east
    assert fit.slope_m_per_100km == pytest.approx(149.0, abs=8.0)
    assert op.theta_plane_fit(z[:5], x[:5], y[:5], theta[:5]) is None
    assert op.theta_plane_fit(z, x, y, 300.0 - 0.01 * z) is None     # theta falling with height is not a pool


def test_wind_constancy():
    steady = op.wind_constancy(np.full(40, 2.0), np.full(40, 300.0))
    assert steady["constancy"] == pytest.approx(1.0) and steady["vector_dir"] == pytest.approx(300.0)
    assert steady["vector_speed"] == pytest.approx(2.0) and steady["calm_fraction"] == 0.0
    flip = op.wind_constancy(np.full(40, 2.0), np.where(np.arange(40) % 2 == 0, 90.0, 270.0))
    assert flip["constancy"] == pytest.approx(0.0, abs=1e-9) and flip["scalar_speed"] == pytest.approx(2.0)
    speed = np.r_[np.full(10, 0.1), np.full(30, 1.5)]
    direction = np.r_[np.full(10, np.nan), np.full(30, 350.0)]
    mixed = op.wind_constancy(speed, direction)
    assert mixed["calm_fraction"] == pytest.approx(0.25) and mixed["constancy"] == pytest.approx(1.0)
    assert mixed["vector_dir"] == pytest.approx(350.0) and mixed["scalar_speed"] == pytest.approx((1.0 + 45.0) / 40.0)
    calm = op.wind_constancy(np.full(5, 0.1), np.full(5, np.nan))
    assert np.isnan(calm["constancy"]) and calm["calm_fraction"] == 1.0
    assert op.wind_constancy(np.array([np.nan]), np.array([10.0])) is None

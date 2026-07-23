"""Derived meteorological quantities for NWP and observation data.

All functions accept xarray DataArrays or numpy arrays and return
the same type, preserving dimensions and coordinates where applicable.
"""

from __future__ import annotations

import numpy as np
import xarray as xr  # noqa: F401 (used in type hints and add_* functions)

# ---------------------------------------------------------------------------
# Unit conversions
# ---------------------------------------------------------------------------

def temp_K_to_C(temp_K):
    """Convert temperature from Kelvin to Celsius."""
    return temp_K - 273.15


def temp_C_to_K(temp_C):
    """Convert temperature from Celsius to Kelvin."""
    return temp_C + 273.15


def pa_to_hpa(pa):
    """Convert pressure from Pa to hPa (millibars)."""
    return pa / 100.0


def hpa_to_pa(hpa):
    """Convert pressure from hPa (millibars) to Pa."""
    return hpa * 100.0


# ---------------------------------------------------------------------------
# Wind
# ---------------------------------------------------------------------------

def wind_speed(u, v):
    """Compute wind speed from U and V components (m/s)."""
    return np.sqrt(u ** 2 + v ** 2)


def wind_direction(u, v):
    """Compute meteorological wind direction from U and V components.

    Returns direction in degrees (0 = N, 90 = E, 180 = S, 270 = W),
    i.e., the direction the wind is blowing FROM.
    """
    return (270 - np.degrees(np.arctan2(v, u))) % 360


def wind_components(speed, direction_deg):
    """Decompose wind speed and meteorological direction into U, V.

    Parameters
    ----------
    speed : array-like
        Wind speed (m/s).
    direction_deg : array-like
        Meteorological direction (degrees, 0 = N, 90 = E).

    Returns
    -------
    u, v : same type as input
        Zonal (east) and meridional (north) components.
    """
    rad = np.radians(direction_deg)
    u = -speed * np.sin(rad)
    v = -speed * np.cos(rad)
    return u, v


KT_PER_MS = 1.94384


def headwind_kt(u_ms, v_ms, runway_heading_deg):
    """Headwind component along a runway heading, in knots.

    Positive = opposing the aircraft (conventional aviation sign).

    Parameters
    ----------
    u_ms, v_ms : array-like
        Eastward and northward wind components (m/s).
    runway_heading_deg : float or array-like
        Runway heading in degrees true (0 = N, 90 = E).
    """
    theta = np.radians(np.asarray(runway_heading_deg))
    u = np.asarray(u_ms)
    v = np.asarray(v_ms)
    return -(u * np.sin(theta) + v * np.cos(theta)) * KT_PER_MS


def crosswind_kt(u_ms, v_ms, runway_heading_deg):
    """Crosswind component across a runway heading, in knots.

    Positive = from the right of the aircraft (conventional aviation sign).

    Parameters
    ----------
    u_ms, v_ms : array-like
        Eastward and northward wind components (m/s).
    runway_heading_deg : float or array-like
        Runway heading in degrees true (0 = N, 90 = E).
    """
    theta = np.radians(np.asarray(runway_heading_deg))
    u = np.asarray(u_ms)
    v = np.asarray(v_ms)
    return (v * np.sin(theta) - u * np.cos(theta)) * KT_PER_MS


# ---------------------------------------------------------------------------
# Thermodynamic quantities
# ---------------------------------------------------------------------------

def potential_temperature(temp_K, pressure_hPa):
    """Compute potential temperature (theta).

    Parameters
    ----------
    temp_K : array-like
        Temperature in Kelvin.
    pressure_hPa : array-like or float
        Pressure in hPa.

    Returns
    -------
    theta : same type as temp_K
        Potential temperature in Kelvin.
    """
    return temp_K * (1000.0 / pressure_hPa) ** 0.2854


def saturation_vapor_pressure(temp_K):
    """Saturation vapour pressure (Pa) via Bolton (1980) Eq. 10.

    Parameters
    ----------
    temp_K : array-like
        Temperature in Kelvin.

    Returns
    -------
    es : same type
        Saturation vapour pressure in Pa.
    """
    temp_C = temp_K - 273.15
    return 611.2 * np.exp(17.67 * temp_C / (temp_C + 243.5))


def mixing_ratio(vapor_pressure_Pa, pressure_Pa):
    """Mixing ratio (kg/kg) from vapour pressure and total pressure."""
    return 0.622 * vapor_pressure_Pa / (pressure_Pa - vapor_pressure_Pa)


def theta_e(temp_K, dewpoint_K, pressure_hPa):
    """Equivalent potential temperature via Bolton (1980).

    Uses the closed-form approximation (Bolton Eq. 43) which is accurate
    to within 0.3 K for typical tropospheric conditions.

    Parameters
    ----------
    temp_K : array-like
        Temperature in Kelvin.
    dewpoint_K : array-like
        Dewpoint temperature in Kelvin.
    pressure_hPa : array-like or float
        Pressure in hPa.

    Returns
    -------
    theta_e : same type as temp_K
        Equivalent potential temperature in Kelvin.
    """
    pressure_Pa = pressure_hPa * 100.0
    e = saturation_vapor_pressure(dewpoint_K)
    r = mixing_ratio(e, pressure_Pa)

    # Lifting condensation level temperature in K (Bolton Eq. 15)
    t_lcl = (1.0 / (1.0 / (dewpoint_K - 56.0) + np.log(temp_K / dewpoint_K) / 800.0)) + 56.0

    # Bolton Eq. 43
    theta_dl = temp_K * (1000.0 / pressure_hPa) ** (0.2854 * (1.0 - 0.28 * r))
    result = theta_dl * np.exp((3.376 / t_lcl - 0.00254) * r * 1000.0 * (1.0 + 0.81 * r))
    return result


def relative_humidity(temp_K, dewpoint_K):
    """Relative humidity (0-100 %) from temperature and dewpoint.

    Parameters
    ----------
    temp_K : array-like
        Temperature in Kelvin.
    dewpoint_K : array-like
        Dewpoint temperature in Kelvin.

    Returns
    -------
    rh : same type
        Relative humidity in percent (0-100).
    """
    es = saturation_vapor_pressure(temp_K)
    e = saturation_vapor_pressure(dewpoint_K)
    return 100.0 * e / es


# ---------------------------------------------------------------------------
# Convenience: add derived fields to an xarray Dataset
# ---------------------------------------------------------------------------

def add_wind_fields(ds: xr.Dataset) -> xr.Dataset:
    """Add wind_speed_10m and wind_dir_10m to a Dataset containing U/V."""
    if "wind_u_10m" in ds and "wind_v_10m" in ds:
        ds["wind_speed_10m"] = wind_speed(ds["wind_u_10m"], ds["wind_v_10m"])
        ds["wind_dir_10m"] = wind_direction(ds["wind_u_10m"], ds["wind_v_10m"])
    return ds


def horizontal_gradient_magnitude(field, dx_m: float = 3000.0):
    """Magnitude of the horizontal gradient of a 2-D field.

    Uses ``np.gradient`` with central differences.  Suitable for
    detecting frontal zones in temperature, theta-e, etc.

    Parameters
    ----------
    field : array-like
        2-D field (y, x).  Can be an xarray DataArray or numpy array.
    dx_m : float
        Grid spacing in metres (default 3 km for HRRR).

    Returns
    -------
    grad_mag : same type
        Gradient magnitude in units-per-metre (multiply by 1000 for
        units-per-km).
    """
    vals = field.values if hasattr(field, "values") else np.asarray(field)
    gy, gx = np.gradient(vals, dx_m)
    mag = np.sqrt(gx ** 2 + gy ** 2)
    if hasattr(field, "dims"):
        import xarray as _xr
        return _xr.DataArray(mag, dims=field.dims, coords=field.coords)
    return mag


def hourly_tendency(ds: xr.Dataset, variable: str) -> xr.Dataset:
    """Compute forward-difference hourly tendency of a variable.

    Adds ``{variable}_tendency`` to the dataset.  The last time step
    is filled with NaN.

    Parameters
    ----------
    ds : xr.Dataset
        Must have a ``time`` dimension.
    variable : str
        Variable name to differentiate.
    """
    if variable not in ds.data_vars or "time" not in ds.dims:
        return ds
    da = ds[variable]
    tend = da.diff("time")
    # Pad the last time step with NaN so dims match
    import xarray as _xr
    pad = _xr.full_like(da.isel(time=-1), np.nan)
    pad = pad.expand_dims("time")
    tend_full = _xr.concat([tend, pad], dim="time")
    tend_full["time"] = ds["time"]
    ds[f"{variable}_tendency"] = tend_full
    return ds


def add_theta_e(ds: xr.Dataset, pressure_hPa: float = 1013.25) -> xr.Dataset:
    """Add theta_e_2m to a Dataset containing temp_2m and dewpoint_2m.

    Parameters
    ----------
    ds : xr.Dataset
        Must contain ``temp_2m`` and ``dewpoint_2m`` (both in K).
    pressure_hPa : float
        Surface pressure in hPa.  If ``mslp`` is present in the dataset
        it will be used instead (converted from Pa to hPa).
    """
    if "temp_2m" not in ds or "dewpoint_2m" not in ds:
        return ds
    p = pa_to_hpa(ds["mslp"]) if "mslp" in ds else pressure_hPa
    ds["theta_e_2m"] = theta_e(ds["temp_2m"], ds["dewpoint_2m"], p)
    return ds

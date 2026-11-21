"""Derived meteorological quantities for NWP and observation data.

All functions accept xarray DataArrays or numpy arrays and return
the same type, preserving dimensions and coordinates where applicable.
"""

from __future__ import annotations

from dataclasses import dataclass

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
# Grid-relative -> earth-relative winds
# ---------------------------------------------------------------------------

#: GRIB grid types whose x/y axes already point east/north, so no rotation applies.
_EARTH_ALIGNED_GRID_TYPES = frozenset({"regular_ll", "regular_gg"})

#: Dataset attribute names that carry a WindGrid (see WindGrid.to_attrs).
_GRID_ATTRS = {
    "grid_type": "grid_type",
    "uv_relative_to_grid": "grid_uv_relative_to_grid",
    "lov_deg": "grid_lov_deg",
    "latin1_deg": "grid_latin1_deg",
    "latin2_deg": "grid_latin2_deg",
}


@dataclass(frozen=True)
class WindGrid:
    """What a GRIB grid says about its wind components: enough to turn them to east/north.

    Built from the grid definition each GRIB message carries (``from_grib_attrs``), not
    from the model's name: one model can ship several grids (RRFS: Lambert for CONUS,
    polar stereographic for Alaska, rotated lat-lon for North America).
    """

    grid_type: str  # GRIB gridType, e.g. "lambert", "regular_ll", "rotated_ll"
    uv_relative_to_grid: bool  # GRIB uvRelativeToGrid: True = along grid x/y, not east/north
    lov_deg: float | None = None  # Lambert: longitude the grid's y axis is parallel to
    latin1_deg: float | None = None  # Lambert: first standard parallel
    latin2_deg: float | None = None  # Lambert: second standard parallel (= first if tangent)

    @classmethod
    def from_grib_attrs(cls, attrs) -> WindGrid | None:
        """Read the grid from one cfgrib variable's ``GRIB_*`` attributes.

        Returns ``None`` when the attributes do not say whether u/v are grid-relative
        (no ``GRIB_gridType`` or no ``GRIB_uvRelativeToGrid``), so the caller cannot
        mistake a missing answer for "no rotation needed".
        """
        grid_type = attrs.get("GRIB_gridType")
        if grid_type is None:
            return None
        if grid_type in _EARTH_ALIGNED_GRID_TYPES:
            return cls(grid_type=str(grid_type), uv_relative_to_grid=False)
        relative = attrs.get("GRIB_uvRelativeToGrid")
        if relative is None:
            return None

        def _deg(key):
            value = attrs.get(key)
            return None if value is None else float(value)

        return cls(
            grid_type=str(grid_type),
            uv_relative_to_grid=bool(int(relative)),
            lov_deg=_deg("GRIB_LoVInDegrees"),
            latin1_deg=_deg("GRIB_Latin1InDegrees"),
            latin2_deg=_deg("GRIB_Latin2InDegrees"),
        )

    @classmethod
    def from_attrs(cls, attrs) -> WindGrid | None:
        """Read back what ``to_attrs`` wrote (e.g. from ``ds.attrs``); ``None`` if absent."""
        if _GRID_ATTRS["grid_type"] not in attrs or _GRID_ATTRS["uv_relative_to_grid"] not in attrs:
            return None
        values = {field: attrs.get(name) for field, name in _GRID_ATTRS.items()}
        return cls(
            grid_type=str(values["grid_type"]),
            uv_relative_to_grid=bool(int(values["uv_relative_to_grid"])),
            **{k: None if values[k] is None else float(values[k])
               for k in ("lov_deg", "latin1_deg", "latin2_deg")},
        )

    def to_attrs(self) -> dict:
        """Flat, netCDF-safe attributes (no None, no bool) that ``from_attrs`` reads back."""
        out = {
            _GRID_ATTRS["grid_type"]: self.grid_type,
            _GRID_ATTRS["uv_relative_to_grid"]: int(self.uv_relative_to_grid),
        }
        for field in ("lov_deg", "latin1_deg", "latin2_deg"):
            value = getattr(self, field)
            if value is not None:
                out[_GRID_ATTRS[field]] = float(value)
        return out

    def rotation_deg(self, lon):
        """Bearing (degrees, clockwise from true north) of the grid's +y axis at ``lon``.

        Zero where u/v are already earth-relative. Raises ``NotImplementedError`` for a
        grid-relative grid this module has no formula for, rather than guess.
        """
        if not self.uv_relative_to_grid or self.grid_type in _EARTH_ALIGNED_GRID_TYPES:
            return np.zeros_like(np.asarray(lon, dtype=float))
        if self.grid_type == "lambert":
            if self.lov_deg is None or self.latin1_deg is None:
                raise ValueError(f"Lambert grid without LoV/Latin1: {self}")
            return grid_rotation_deg(
                lon, lov_deg=self.lov_deg, latin_deg=self.latin1_deg,
                latin2_deg=self.latin2_deg,
            )
        raise NotImplementedError(
            f"No grid-to-earth wind rotation for GRIB gridType {self.grid_type!r} "
            "(grid-relative u/v). Add its formula to brc_tools.nwp.derived.WindGrid "
            "before using these winds as east/north."
        )


#: The Lambert conformal grid HRRR's GRIB2 messages declare (template 3.30): LoV 262.5 E,
#: Latin1 = Latin2 = 38.5 N, uvRelativeToGrid = 1. RRFS's CONUS 3 km files declare the
#: same grid (checked on rrfs.20261120/12 2dfld + prslev); its Alaska and North America
#: files do not. Pass this only where the model is fixed in the code, as in
#: nwp/aviation.py; anything fed by NWPSource reads the grid off the dataset instead.
HRRR_GRID = WindGrid(
    grid_type="lambert", uv_relative_to_grid=True,
    lov_deg=262.5, latin1_deg=38.5, latin2_deg=38.5,
)


def lambert_cone_constant(latin1_deg, latin2_deg=None):
    """Cone constant ``n`` of a Lambert conformal grid (tangent or secant)."""
    phi1 = np.radians(latin1_deg)
    if latin2_deg is None or np.isclose(latin1_deg, latin2_deg):
        return float(np.sin(phi1))
    phi2 = np.radians(latin2_deg)
    return float(
        np.log(np.cos(phi1) / np.cos(phi2))
        / np.log(np.tan(np.pi / 4 + phi2 / 2) / np.tan(np.pi / 4 + phi1 / 2))
    )


def grid_rotation_deg(lon, *, lov_deg, latin_deg, latin2_deg=None):
    """Bearing (degrees, clockwise from true north) of a Lambert grid's +y axis at ``lon``.

    ``n * (lon - lov)`` with ``n`` the cone constant: on HRRR's grid about -7.5 deg at
    Vernal and -8.6 deg at Daniels Summit. Negative west of LoV, where the grid's y
    axis leans west of true north. The grid parameters are required: there is no
    default grid, so no model can inherit another's rotation by omission.
    """
    dlon = (np.asarray(lon, dtype=float) - lov_deg + 180.0) % 360.0 - 180.0
    return lambert_cone_constant(latin_deg, latin2_deg) * dlon


def grid_to_earth_winds(u, v, lon, *, grid):
    """Rotate grid-relative (u, v) to (east, north) components on ``grid`` (a WindGrid).

    Speed is unchanged; direction moves by ``grid.rotation_deg(lon)``. Works on numpy
    arrays and xarray objects alike (``lon`` broadcasts against ``u`` and ``v``).
    """
    theta = np.radians(grid.rotation_deg(lon))
    cos_t, sin_t = np.cos(theta), np.sin(theta)
    return u * cos_t + v * sin_t, -u * sin_t + v * cos_t


def rotate_winds_to_earth(ds, u_name, v_name, *, grid=None, lon_name="longitude"):
    """Rotate ``ds[u_name]``/``ds[v_name]`` from grid-relative to earth-relative.

    The grid comes from ``grid`` if given, else from the dataset's own attributes,
    which ``NWPSource.fetch`` copies from the GRIB messages it read. A dataset that
    carries no grid and is given none raises ``ValueError``: the rotation is never
    assumed from another model.

    Marks both variables ``attrs["wind_frame"] = "earth"`` and refuses to rotate them
    twice. Returns ``ds`` unchanged if either component is missing.
    """
    if u_name not in ds or v_name not in ds:
        return ds
    if ds[u_name].attrs.get("wind_frame") == "earth":
        return ds
    grid = grid or WindGrid.from_attrs(ds.attrs)
    if grid is None:
        raise ValueError(
            f"Cannot rotate {u_name}/{v_name}: the dataset carries no grid definition "
            "(grid_type / grid_uv_relative_to_grid attributes) and no grid= was passed. "
            "NWPSource.fetch sets these from the GRIB; for data read another way, pass "
            "grid=WindGrid.from_grib_attrs(<cfgrib variable>.attrs)."
        )
    u_e, v_e = grid_to_earth_winds(ds[u_name], ds[v_name], ds[lon_name], grid=grid)
    for name, field in ((u_name, u_e), (v_name, v_e)):
        attrs = dict(ds[name].attrs, wind_frame="earth")
        ds[name] = field.transpose(*ds[name].dims).assign_attrs(attrs)
    return ds


# ---------------------------------------------------------------------------
# Convenience: add derived fields to an xarray Dataset
# ---------------------------------------------------------------------------

def add_wind_fields(ds: xr.Dataset) -> xr.Dataset:
    """Add wind_speed_10m and wind_dir_10m to a Dataset containing U/V."""
    if "wind_u_10m" in ds and "wind_v_10m" in ds:
        ds["wind_speed_10m"] = wind_speed(ds["wind_u_10m"], ds["wind_v_10m"])
        ds["wind_dir_10m"] = wind_direction(ds["wind_u_10m"], ds["wind_v_10m"])
    return ds


#: Bulk-shear layers HRRR ships as components, keyed by the depth token used in
#: the alias names.  HRRR carries the 0-1 km and 0-6 km layers only -- there is no
#: 0-3 km message, so a 0-3 km panel must come from pressure-level winds or from
#: wrfout, not from these aliases.
SHEAR_LAYERS = ("0to1km", "0to6km")


def add_shear_fields(ds: xr.Dataset) -> xr.Dataset:
    """Add bulk-shear magnitude for every layer whose components are present.

    HRRR ships the shear *components* (``VUCSH``/``VVCSH``) but not the
    magnitude, so ``shear_mag_<layer>`` is a derived field rather than a lookup
    alias.  Requesting it as an alias is what silently produced an all-NaN
    column in the Ashley gate-A0 table.

    The magnitude of a vector is the same arithmetic as a wind speed, so this
    reuses :func:`wind_speed` rather than repeating it.
    """
    for layer in SHEAR_LAYERS:
        u_name = f"shear_u_{layer}"
        v_name = f"shear_v_{layer}"
        if u_name in ds and v_name in ds:
            ds[f"shear_mag_{layer}"] = wind_speed(ds[u_name], ds[v_name])
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

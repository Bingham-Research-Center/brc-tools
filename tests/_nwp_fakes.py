"""Stand-ins for Herbie and SynopticPy at the exact seam NWPSource and ObsSource use.

Nothing here touches the network. ``FakeHerbie`` matches a search the way Herbie does
(``re.search`` over idx-style lines) and returns what cfgrib returns: one data variable
named by its GRIB short name, scalar ``time``/``step``/level/``valid_time`` coordinates,
Herbie's ``gribfile_projection`` coordinate and the ``GRIB_*`` grid attributes.
``FakeTimeSeries`` returns SynopticPy's *long* table, so the real ``.synoptic.pivot()``
runs on it.

Every field is a plane in (lat, lon, hour) whose value names where and when it was
taken, so a test can recompute what the right grid point should hold.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

import numpy as np
import polars as pl
import xarray as xr

# ── grids ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Grid:
    lat: np.ndarray  # 2-D (curvilinear) or 1-D (regular)
    lon: np.ndarray  # same; stored in the model's own convention (0..360 here)
    attrs: dict
    regular: bool = False

    def lonlat_2d(self) -> tuple[np.ndarray, np.ndarray]:
        """(lat2d, lon2d) with longitude in -180..180."""
        if self.regular:
            lon2d, lat2d = np.meshgrid(self.lon, self.lat)
        else:
            lat2d, lon2d = self.lat, self.lon
        return lat2d, ((lon2d + 180.0) % 360.0) - 180.0


LAMBERT_ATTRS = {
    "GRIB_gridType": "lambert",
    "GRIB_uvRelativeToGrid": 1,
    "GRIB_LoVInDegrees": 262.5,
    "GRIB_Latin1InDegrees": 38.5,
    "GRIB_Latin2InDegrees": 38.5,
}


def lambert_grid(*, lat0=38.6, lon0=-112.0, ny=60, nx=80) -> Grid:
    """A skewed curvilinear grid over the Uinta Basin, longitudes 0..360 like cfgrib HRRR.

    Neither lat nor lon is constant along a grid row or column (the real HRRR rows sit
    ~8 deg off east), so a crop or nearest-point that assumed a regular grid would fail.
    """
    j, i = np.mgrid[0:ny, 0:nx].astype(float)
    lat = lat0 + 0.055 * j + 0.006 * i
    lon = (lon0 + 0.060 * i - 0.007 * j) % 360.0
    return Grid(lat=lat, lon=lon, attrs=dict(LAMBERT_ATTRS))


def regular_grid(*, north=43.0, south=37.0, west=245.0, east=255.0, step=0.25) -> Grid:
    """A GEFS-like regular grid: latitude descending, longitude 0..360."""
    lat = np.arange(north, south - step / 2, -step)
    lon = np.arange(west, east + step / 2, step)
    return Grid(lat=lat, lon=lon, attrs={"GRIB_gridType": "regular_ll"}, regular=True)


# ── fields ───────────────────────────────────────────────────────────────

# idx search text (without the forecast-time column) -> (cfgrib short name, base value)
SFC_MESSAGES = {
    "TMP:2 m above ground": ("t2m", 270.0),
    "DPT:2 m above ground": ("d2m", 260.0),
    "RH:2 m above ground": ("r2", 50.0),
    "UGRD:10 m above ground": ("u10", 3.0),
    "VGRD:10 m above ground": ("v10", -2.0),
    "GUST:surface": ("gust", 8.0),
    "MSLMA:mean sea level": ("mslma", 101_000.0),
    "PRMSL:mean sea level": ("prmsl", 101_200.0),
    "APCP:surface": ("tp", 0.0),
}
PRS_LEVELS = (1000, 925, 850, 700, 500, 250)
PRS_MESSAGES = {
    f"{var}:{lv} mb": (short, base - 0.05 * (1000 - lv))
    for lv in PRS_LEVELS
    for var, short, base in (("TMP", "t", 290.0), ("UGRD", "u", 5.0), ("VGRD", "v", 1.0),
                             ("HGT", "gh", 3000.0))
}


def field_value(base: float, fxx: int, lat, lon_180):
    """Analytic field: every value says where (lat, lon) and when (fxx) it was taken."""
    return base + 0.5 * fxx + 2.0 * (np.asarray(lat) - 40.0) + 0.3 * (np.asarray(lon_180) + 110.0)


def _idx_lines(messages: dict, fxx: int) -> list[tuple[str, str, str, float]]:
    """(search line, message key, short name, base) like Herbie's ``search_this`` column."""
    lines = []
    for key, (short, base) in messages.items():
        if key.startswith("APCP"):
            if fxx == 0:
                continue  # HRRR f00 has no accumulation window
            line = f":{key}:{fxx - 1}-{fxx} hour acc fcst:"
        else:
            line = f":{key}:{'anl' if fxx == 0 else f'{fxx} hour fcst'}:"
        lines.append((line, key, short, base))
    return lines


# ── Herbie ───────────────────────────────────────────────────────────────


def make_fake_herbie(grid: Grid, *, products: dict[str, dict] | None = None,
                     grids: dict[str, Grid] | None = None):
    """Return a fresh ``FakeHerbie`` class bound to one grid (class state is per test).

    ``products`` maps Herbie product -> message table; default: ``sfc``/``2dfld``/
    ``atmos.25`` serve the surface table, ``prs``/``prslev`` the pressure one, and
    ``atmos.5`` (GEFS pgrb2a) both. ``grids`` gives a product its own grid (GEFS
    ``atmos.5`` is 0.5 deg where ``atmos.25`` is 0.25 deg); others use ``grid``.
    """
    tables = products or {
        "sfc": SFC_MESSAGES, "2dfld": SFC_MESSAGES, "atmos.25": SFC_MESSAGES,
        "atmos.5": {**SFC_MESSAGES, **PRS_MESSAGES},
        "prs": PRS_MESSAGES, "prslev": PRS_MESSAGES,
    }
    grid_for = dict(grids or {})
    default_grid = grid

    class FakeHerbie:
        calls: list[dict] = []  # every constructor call's kwargs (+ "date")
        searches: list[tuple[int, str, str]] = []  # (fxx, product, search) per xarray()
        fail: list = []  # callables (fxx, product, search, attempt) -> Exception | None
        grib_path = None  # set to a Path to simulate a cached GRIB file

        def __init__(self, date, *, model, product, fxx, member=None, save_dir=None):
            if getattr(date, "tzinfo", None) is not None:
                raise TypeError("Herbie compares naive UTC; got a tz-aware init")
            self.date = date
            self.model, self.product, self.fxx, self.member = model, product, fxx, member
            type(self).calls.append(
                dict(date=date, model=model, product=product, fxx=fxx,
                     member=member, save_dir=save_dir)
            )
            self.grib = type(self).grib_path
            self.idx = None

        def xarray(self, search, remove_grib=True):
            cls = type(self)
            attempt = sum(1 for s in cls.searches if s == (self.fxx, self.product, search))
            cls.searches.append((self.fxx, self.product, search))
            for rule in cls.fail:
                exc = rule(self.fxx, self.product, search, attempt)
                if exc is not None:
                    raise exc
            table = tables.get(self.product)
            if table is None:
                raise ValueError(f"FakeHerbie: no {self.product!r} file")
            hits = [h for h in _idx_lines(table, self.fxx) if re.search(search, h[0])]
            if not hits:
                raise ValueError(f"No GRIB messages found. There might be something wrong with {search=}")
            if len(hits) > 1:
                raise AssertionError(f"FakeHerbie: {search!r} matched {len(hits)} messages")
            _, key, short, base = hits[0]
            return self._dataset(key, short, base)

        def _dataset(self, key, short, base):
            grid = grid_for.get(self.product, default_grid)
            lat2d, lon180 = grid.lonlat_2d()
            values = field_value(base, self.fxx, lat2d, lon180)
            init = np.datetime64(self.date, "ns")
            step = np.timedelta64(self.fxx, "h")
            level_name, level = _level_coord(key)
            coords = {
                "time": init,
                "step": step,
                level_name: level,
                "valid_time": init + step,
                "gribfile_projection": 0,
            }
            if grid.regular:
                dims = ("latitude", "longitude")
                coords.update(latitude=("latitude", grid.lat), longitude=("longitude", grid.lon))
            else:
                dims = ("y", "x")
                coords.update(latitude=(dims, grid.lat), longitude=(dims, grid.lon))
            attrs = dict(grid.attrs, GRIB_shortName=short)
            return xr.Dataset({short: (dims, values, attrs)}, coords=coords)

    return FakeHerbie


def _level_coord(key: str) -> tuple[str, float]:
    if key.endswith(" mb"):
        return "isobaricInhPa", float(key.split(":")[1].split()[0])
    m = re.search(r"(\d+) m above ground", key)
    if m:
        return "heightAboveGround", float(m.group(1))
    return ("meanSea", 0.0) if "sea level" in key else ("surface", 0.0)


def fail_when(*, fxx=None, product=None, contains=None, times=None, exc=ValueError):
    """A ``FakeHerbie.fail`` rule: raise on matching calls (the first ``times`` only)."""

    def rule(f, p, search, attempt):
        if fxx is not None and f != fxx:
            return None
        if product is not None and p != product:
            return None
        if contains is not None and contains not in search:
            return None
        if times is not None and attempt >= times:
            return None
        return exc(f"FakeHerbie: injected failure f{f:03d} {p} {search!r}")

    return rule


# ── SynopticPy ───────────────────────────────────────────────────────────

# Synoptic variable -> (units, value at a station's first hour)
OBS_VARIABLES = {
    "air_temp": ("Celsius", -3.0),
    "dew_point_temperature": ("Celsius", -9.0),
    "relative_humidity": ("%", 60.0),
    "wind_speed": ("m/s", 4.0),
    "wind_direction": ("Degrees", 270.0),
    "sea_level_pressure": ("Pascals", 102_000.0),
    "soil_moisture": ("%", 25.0),
}


def long_obs_frame(
    stations: dict[str, tuple[float, float, float]],
    times: list[dt.datetime],
    *,
    values=None,
    variables=None,
) -> pl.DataFrame:
    """SynopticPy's long table: one row per (station, time, variable, sensor).

    ``values(stid, lat, lon, time, variable) -> float | None`` sets each value; the
    default is the ``OBS_VARIABLES`` constant. A second ``air_temp`` sensor (index 2)
    reads 100 degrees off so a pivot that mixed sensors would be caught.
    """
    rows = []
    variables = variables or list(OBS_VARIABLES)
    for stid, (lat, lon, elev) in stations.items():
        for t in times:
            for var in variables:
                units, default = OBS_VARIABLES[var]
                value = default if values is None else values(stid, lat, lon, t, var)
                base = dict(stid=stid, date_time=t.replace(tzinfo=dt.timezone.utc),
                            variable=var, is_derived=False, units=units, latitude=lat,
                            longitude=lon, elevation=elev, name=f"{stid} station")
                rows.append(dict(base, sensor_index=1, value=value))
                if var == "air_temp":
                    rows.append(dict(base, sensor_index=2, value=None if value is None else value + 100.0))
    return pl.DataFrame(rows, schema_overrides={
        "date_time": pl.Datetime("us", "UTC"), "sensor_index": pl.UInt32, "value": pl.Float64,
    })


def make_fake_timeseries(frame_for):
    """Fake ``synoptic.services.TimeSeries``: ``frame_for(**params)`` builds the long table."""

    class FakeTimeSeries:
        calls: list[dict] = []

        def __init__(self, **params):
            type(self).calls.append(params)
            self._params = params

        def df(self):
            return frame_for(**self._params)

    return FakeTimeSeries

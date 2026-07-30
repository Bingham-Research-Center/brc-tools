"""NEXRAD Level-III single-site products from the Iowa State IEM RIDGE archive.

This is the route that actually works for a historical case.  Level-II is the
richer product, but for an October 2025 case none of the obvious Level-II sources
serves it (see :mod:`brc_tools.radar.nexrad`).  Iowa State's IEM keeps a
long-running per-radar Level-III archive as georeferenced PNGs, and the product it
carries -- ``N0B``, base reflectivity on **elevation 1, the 0.5 deg tilt** -- is one
of the exact tilts a beam-matched comparison needs.

What you get and what you do not
--------------------------------
* **0.5 deg only.**  RIDGE carries the lowest tilt.  A signature reported at 0.0 or
  1.2 deg cannot be verified from here; that still needs Level-II.
* **Quantised to 0.5 dBZ** and already resampled by the NWS product generator onto
  a regular latitude/longitude grid.  Fine for comparing against a model field on
  the same beam surface; not raw polar data.
* **Reflectivity is calibrated here; velocity is not.**  ``N0S`` (storm-relative
  velocity) is fetchable but its index scaling is not verified in this module, so
  :func:`read_ridge` refuses to hand back unscaled velocities dressed as m/s.

Encoding, verified against a real scan (GJX, 2025-10-12 02:18Z)
---------------------------------------------------------------
A 1000x1000 8-bit palette PNG plus a ``.wld`` world file giving a north-up
plate-carree transform.  Palette index 0 is missing data; indices 1..255 map
linearly to -32..+95 dBZ in 0.5 dBZ steps.  Checked against the palette itself:
index 60 is grey (~-2 dBZ), 100 light blue (~17), 140 olive (~37), 180 dark red
(~57) -- the standard NWS ramp, in the right order.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from brc_tools.radar.nexrad import cache_dir, fetch_volume

#: Root of the IEM archive.
IEM_ARCHIVE = "https://mesonet.agron.iastate.edu/archive/data"

#: RIDGE products, mapped to ``(elevation_deg, description, quantity)``.
#:
#: All are elevation 1.  ``quantity`` gates :func:`read_ridge`: only
#: ``reflectivity`` has a verified index scaling in this module.
RIDGE_PRODUCTS: dict[str, tuple[float, str, str]] = {
    "N0B": (0.5, "base reflectivity, super-resolution", "reflectivity"),
    "N0Q": (0.5, "base reflectivity, legacy 0.25 km", "reflectivity"),
    "N0S": (0.5, "storm-relative mean radial velocity", "velocity"),
}

#: Index -> dBZ for the reflectivity products.  Index 0 is missing.
_DBZ_MIN = -32.0
_DBZ_STEP = 0.5

_SCAN_RE = re.compile(r"([A-Z]{3})_(N0[A-Z])_(\d{12})\.png")


@dataclass(frozen=True)
class RidgeField:
    """One Level-III scan on a regular latitude/longitude grid.

    ``values`` is ``(ny, nx)`` in dBZ with NaN where the product reported no data.
    ``lat`` runs **north to south** to match the image row order, as the world file
    describes; ``extent`` is ``(lon0, lon1, lat0, lat1)`` with ``lat0 < lat1`` for
    plotting.
    """

    site_id: str
    product: str
    elevation_deg: float
    valid_time: datetime
    values: np.ndarray
    lat: np.ndarray  # (ny,) descending
    lon: np.ndarray  # (nx,) ascending
    extent: tuple[float, float, float, float]

    def subset(self, extent) -> RidgeField:
        """Crop to ``(lon0, lon1, lat0, lat1)``.

        A RIDGE tile spans ~10.7 degrees; a 600 m nest is a small part of it, and
        carrying the rest into a figure wastes both memory and colour range.
        """
        lon0, lon1, lat0, lat1 = extent
        cols = np.flatnonzero((self.lon >= lon0) & (self.lon <= lon1))
        rows = np.flatnonzero((self.lat >= lat0) & (self.lat <= lat1))
        if cols.size == 0 or rows.size == 0:
            raise ValueError(f"extent {extent} does not overlap this scan's {self.extent}")
        lat = self.lat[rows]
        lon = self.lon[cols]
        return RidgeField(
            site_id=self.site_id,
            product=self.product,
            elevation_deg=self.elevation_deg,
            valid_time=self.valid_time,
            values=self.values[np.ix_(rows, cols)],
            lat=lat,
            lon=lon,
            extent=(float(lon.min()), float(lon.max()), float(lat.min()), float(lat.max())),
        )


def iem_site(site_id: str) -> str:
    """ICAO id to the 3-letter form the RIDGE archive uses (``KGJX`` -> ``GJX``)."""
    site = site_id.strip().upper()
    return site[1:] if len(site) == 4 and site[0] in "KPT" else site


def ridge_dir_url(site_id: str, day: datetime, product: str = "N0B") -> str:
    """Directory URL for one site, day and product."""
    if product not in RIDGE_PRODUCTS:
        raise KeyError(f"unknown RIDGE product {product!r}; known: {sorted(RIDGE_PRODUCTS)}")
    return f"{IEM_ARCHIVE}/{day:%Y/%m/%d}/GIS/ridge/{iem_site(site_id)}/{product}"


def available_scans(
    site_id: str, start: datetime, end: datetime, product: str = "N0B"
) -> list[tuple[datetime, str]]:
    """``(valid_time, png_url)`` for every scan in the window.

    **Touches the network.**  Scans come every ~4-5 minutes, so a target time
    generally falls between two of them.
    """
    import requests

    found: dict[datetime, str] = {}
    day = datetime(start.year, start.month, start.day)
    while day <= end:
        base = ridge_dir_url(site_id, day, product)
        response = requests.get(base + "/", timeout=(10.0, 120.0))
        if response.status_code == 200:
            for match in _SCAN_RE.finditer(response.text):
                stamp = datetime.strptime(match.group(3), "%Y%m%d%H%M")
                if start <= stamp <= end:
                    found[stamp] = f"{base}/{match.group(0)}"
        day = day + timedelta(days=1)
    return sorted(found.items())


def nearest_scan(
    site_id: str, target: datetime, *, window_minutes: float = 10.0, product: str = "N0B"
) -> tuple[datetime, str] | None:
    """The scan closest to ``target``, or ``None`` if the window holds none.

    **Touches the network.**
    """
    span = timedelta(minutes=window_minutes)
    scans = available_scans(site_id, target - span, target + span, product)
    if not scans:
        return None
    return min(scans, key=lambda item: abs((item[0] - target).total_seconds()))


def fetch_scan(png_url: str, *, dest_dir: str | Path | None = None) -> tuple[Path, Path]:
    """Download a scan's PNG **and** its world file, returning both paths.

    **Touches the network.**  Cached like a Level-II volume, with the same
    provenance sidecars; the world file is mandatory, because without the transform
    the image is unusable.
    """
    out_dir = Path(dest_dir) if dest_dir is not None else cache_dir() / "ridge"
    png = fetch_volume(png_url, dest_dir=out_dir)
    wld_url = png_url[: -len(".png")] + ".wld"
    wld = fetch_volume(wld_url, dest_dir=out_dir)
    return png, wld


def read_world_file(path: str | Path) -> tuple[float, float, float, float]:
    """Parse a six-line ESRI world file into ``(dx, dy, ul_x, ul_y)``.

    Rejects a rotated transform rather than silently ignoring the rotation terms:
    RIDGE tiles are north-up, and a rotated one would mis-georeference everything
    downstream.
    """
    numbers = [float(line) for line in Path(path).read_text().split()]
    if len(numbers) != 6:
        raise ValueError(f"{path}: expected 6 world-file values, found {len(numbers)}")
    dx, rot_y, rot_x, dy, ul_x, ul_y = numbers
    if rot_x or rot_y:
        raise ValueError(f"{path}: rotated world files are not supported ({rot_x}, {rot_y})")
    return dx, dy, ul_x, ul_y


def dbz_from_index(index) -> np.ndarray:
    """Palette index to dBZ; index 0 (missing) becomes NaN."""
    idx = np.asarray(index)
    dbz = _DBZ_MIN + (idx.astype(float) - 1.0) * _DBZ_STEP
    return np.where(idx == 0, np.nan, dbz)


def read_ridge(
    png_path: str | Path,
    wld_path: str | Path,
    *,
    site_id: str | None = None,
    product: str | None = None,
    mask_below_dbz: float | None = 5.0,
) -> RidgeField:
    """Decode a RIDGE PNG + world file into a :class:`RidgeField` in dBZ.

    ``mask_below_dbz`` masks the below-threshold end, matching the convention the
    model-side plots use so the two are directly comparable; pass ``None`` to keep
    everything.

    Refuses a velocity product: its index scaling is not verified here, and
    returning unscaled indices labelled m/s would be worse than refusing.
    """
    from PIL import Image

    png_path = Path(png_path)
    match = _SCAN_RE.search(png_path.name)
    if product is None:
        product = match.group(2) if match else "N0B"
    if site_id is None:
        site_id = match.group(1) if match else ""
    valid_time = (
        datetime.strptime(match.group(3), "%Y%m%d%H%M") if match else datetime(1970, 1, 1)
    )

    elevation, _desc, quantity = RIDGE_PRODUCTS.get(product, (0.5, "unknown", "unknown"))
    if quantity != "reflectivity":
        raise NotImplementedError(
            f"{product} is a {quantity} product and its index scaling is not verified "
            "in this module; only the reflectivity products (N0B, N0Q) are calibrated. "
            "Do not reinterpret the indices as physical units without checking IEM's "
            "documented ramp for this product."
        )

    with Image.open(png_path) as image:
        if image.mode != "P":
            raise ValueError(f"{png_path.name}: expected a palette image, got mode {image.mode}")
        index = np.array(image)

    values = dbz_from_index(index)
    if mask_below_dbz is not None:
        values = np.where(values < mask_below_dbz, np.nan, values)

    dx, dy, ul_x, ul_y = read_world_file(wld_path)
    ny, nx = index.shape
    # World-file coordinates are the UL pixel's CENTRE, so no half-pixel shift.
    lon = ul_x + np.arange(nx) * dx
    lat = ul_y + np.arange(ny) * dy  # dy is negative: rows run north to south

    return RidgeField(
        site_id=site_id,
        product=product,
        elevation_deg=elevation,
        valid_time=valid_time,
        values=values,
        lat=lat,
        lon=lon,
        extent=(float(lon.min()), float(lon.max()), float(lat.min()), float(lat.max())),
    )


def to_plan_dataset(field: RidgeField, var: str = "refl_beam"):
    """Wrap a :class:`RidgeField` as the plan-view Dataset the renderers expect.

    Same shape as :func:`brc_tools.nwp.wrf_section.plan_dataset` produces, so an
    observed scan goes through :func:`~brc_tools.visualize.nwp_maps.plot_nwp_surface_map`
    with the *same* colour scale and overlays as the model panel.  That is the whole
    point: two figures a reader can compare without arithmetic.
    """
    import xarray as xr

    lon2d, lat2d = np.meshgrid(field.lon, field.lat)
    return xr.Dataset(
        data_vars={var: (("y", "x"), field.values)},
        coords={
            "latitude": (("y", "x"), lat2d),
            "longitude": (("y", "x"), lon2d),
        },
    )


def observed_sweep(
    site_id: str,
    target: datetime,
    *,
    product: str = "N0B",
    window_minutes: float = 10.0,
    extent=None,
    dest_dir: str | Path | None = None,
) -> RidgeField | None:
    """One call: find, fetch and decode the scan nearest ``target``.

    **Touches the network.**  Returns ``None`` when the window holds no scan, which
    a caller should treat as "no observation to compare against" rather than as an
    error -- an archive gap is a fact about the data, not a failure.
    """
    found = nearest_scan(site_id, target, window_minutes=window_minutes, product=product)
    if found is None:
        return None
    _stamp, url = found
    png, wld = fetch_scan(url, dest_dir=dest_dir)
    field = read_ridge(png, wld, site_id=site_id, product=product)
    return field.subset(extent) if extent else field

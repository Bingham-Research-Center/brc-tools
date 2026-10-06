"""GOES-R ABI Level-2 products from NOAA's public buckets, without credentials or s3 clients.

Three steps, each usable on its own:

* :func:`list_abi` -- what a bucket holds for a product between two times (an HTTPS listing
  of ``<product>/<year>/<day-of-year>/<hour>/``; ``requests`` only). The bucket follows the
  satellite operational in the GOES-West (default) or GOES-East slot on the scan date
  (:func:`resolve_satellite`), and a date before there was any GOES-R ABI raises rather than
  listing nothing.
* :func:`fetch_abi` -- download those files, skipping the ones already on disk; by default
  into ``$BRC_TOOLS_GOES_CACHE`` or ``~/.cache/brc-tools/goes`` (:func:`default_cache_dir`),
  never the checkout.
* :func:`sample_on_latlon` -- put a field on a regular lat/lon grid by computing, for every
  target point, the scan angles at which the satellite sees it and taking the nearest
  fixed-grid pixel. With ``height_m`` the point is placed at its terrain height first, which
  is the parallax correction: over 2-3 km terrain seen at a 55 degree zenith angle the
  uncorrected displacement is 3-4 km.

The fixed-grid navigation is the GOES-R Product User Guide's (L1b, section 5.1.2.8), on the
GRS80 ellipsoid the files carry in ``goes_imager_projection`` -- including the sub-satellite
longitude, so it is right for whichever satellite wrote the file.

Caveats that belong to the products, not the code: ABI land-surface temperature is a
clear-sky product (cloudy pixels are missing, and at night a cold pool with fog can be
masked as cloud), its pixels are 2 km at nadir and nearer 3-4 km over the interior West,
and it is a *skin* temperature. Use it for basin-scale pattern, not for a canyon.
"""
from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree

import numpy as np

__all__ = [
    "AbiFile", "parse_listing", "OPERATIONAL", "resolve_satellite", "list_abi", "nearest_files",
    "default_cache_dir", "fetch_abi", "GoesProjection", "scan_angles", "lonlat_from_scan",
    "nearest_index", "LatLonField", "sample_on_latlon",
]

logger = logging.getLogger(__name__)

BUCKET_URL = "https://{bucket}.s3.amazonaws.com"
_S3_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
_START_RE = re.compile(r"_s(\d{4})(\d{3})(\d{2})(\d{2})(\d{2})\d_e")

# The satellite in each operational slot from a date on (00 UTC: the hand-over itself took
# place during that day, so for a scan on a changeover day name the satellite outright).
# Each one's bucket is ``noaa-<name>``.
OPERATIONAL = {
    "west": ((datetime(2019, 2, 12), "goes17"), (datetime(2023, 1, 4), "goes18")),
    "east": ((datetime(2017, 12, 18), "goes16"), (datetime(2025, 4, 7), "goes19")),
}
# Launch dates: no file from a satellite can predate its launch. A named satellite is
# otherwise taken as asked, including its post-launch test period away from its slot (the
# file's own projection then says where it looked from).
_LAUNCHED = {"goes16": datetime(2016, 11, 19), "goes17": datetime(2018, 3, 1),
             "goes18": datetime(2022, 3, 1), "goes19": datetime(2024, 6, 25)}


@dataclass(frozen=True)
class AbiFile:
    """One object in a GOES bucket."""
    bucket: str
    key: str
    size: int
    start: datetime          # scan start, UTC-naive

    @property
    def name(self) -> str:
        return self.key.rsplit("/", 1)[-1]

    @property
    def url(self) -> str:
        return f"{BUCKET_URL.format(bucket=self.bucket)}/{self.key}"


def _start_time(key: str) -> datetime | None:
    m = _START_RE.search(key)
    if not m:
        return None
    year, doy, hh, mm, ss = (int(g) for g in m.groups())
    return datetime(year, 1, 1) + timedelta(days=doy - 1, hours=hh, minutes=mm, seconds=ss)


def parse_listing(xml_text: str, bucket: str) -> list[AbiFile]:
    """The ``.nc`` objects named in one S3 ``ListObjectsV2`` response."""
    root = ElementTree.fromstring(xml_text)
    out = []
    for item in root.iter(f"{_S3_NS}Contents"):
        key = item.findtext(f"{_S3_NS}Key") or ""
        start = _start_time(key)
        if key.endswith(".nc") and start is not None:
            out.append(AbiFile(bucket, key, int(item.findtext(f"{_S3_NS}Size") or 0), start))
    return out


def resolve_satellite(satellite: str, when: datetime) -> str:
    """The GOES-R satellite (``"goes16"`` .. ``"goes19"``) that ``satellite`` means at ``when`` (UTC-naive).

    ``"west"`` and ``"east"`` resolve to the satellite operational in that slot on the date
    (:data:`OPERATIONAL`); a name -- ``"goes18"``, ``"GOES-18"``, ``"G18"`` -- is taken as
    given. A time before that slot had a GOES-R ABI, or before the named satellite was
    launched, raises ``ValueError``: there is nothing to list, and an empty listing would
    read as a gap in the record rather than as the wrong satellite or era.
    """
    key = satellite.strip().lower().replace("-", "").replace("_", "")
    if re.fullmatch(r"g1[6-9]", key):
        key = "goes" + key[1:]
    if key in OPERATIONAL:
        slots = OPERATIONAL[key]
        first, first_name = slots[0]
        if when < first:
            other = "east" if key == "west" else "west"
            raise ValueError(
                f"no GOES-R ABI data before {first:%Y-%m-%d} for satellite={satellite!r} (asked for "
                f"{when:%Y-%m-%d %H:%M} UTC): {first_name} became the operational GOES-{key.title()} then. "
                f"GOES-{other.title()} began {OPERATIONAL[other][0][0]:%Y-%m-%d}, and before GOES-16 (launched "
                f"2016-11-19) there is no ABI at all -- this module reads only GOES-R ABI files")
        return [name for start, name in slots if when >= start][-1]
    if key in _LAUNCHED:
        if when < _LAUNCHED[key]:
            raise ValueError(f"no GOES-R ABI data before {_LAUNCHED[key]:%Y-%m-%d} from {key}, its launch "
                             f"(asked for {when:%Y-%m-%d %H:%M} UTC)")
        return key
    raise ValueError(f"unknown GOES satellite {satellite!r}: use 'west', 'east' or one of {sorted(_LAUNCHED)}")


def list_abi(product: str, start: datetime, end: datetime, *, satellite: str = "west", bucket: str | None = None,
             session=None, timeout: float = 60.0, retries: int = 3) -> list[AbiFile]:
    """Files of ``product`` (e.g. ``"ABI-L2-LSTC"``) whose scan starts in ``start..end`` (UTC-naive), time-ordered.

    ``satellite`` chooses the bucket by scan date (:func:`resolve_satellite`): ``"west"``
    (the default; GOES-18 since 2023-01-04, GOES-17 before), ``"east"``, or a satellite by
    name. A window across a changeover lists each hour from the satellite operational in
    it. ``bucket`` names a bucket outright and overrides ``satellite``. A ``start`` before
    the chosen satellite has ABI data raises ``ValueError`` before any request is made.
    Failed requests are retried ``retries`` times with a growing pause, each retry logged.
    """
    import requests

    if bucket is None:
        resolve_satellite(satellite, start)
    elif m := re.fullmatch(r"noaa-(goes1[6-9])", bucket):
        resolve_satellite(m.group(1), start)
    http = session or requests.Session()
    files: list[AbiFile] = []
    hour = start.replace(minute=0, second=0, microsecond=0)
    while hour <= end:
        name = bucket or f"noaa-{resolve_satellite(satellite, max(hour, start))}"
        prefix = f"{product}/{hour:%Y}/{hour:%j}/{hour:%H}/"
        token = None
        while True:
            params = {"list-type": "2", "prefix": prefix}
            if token:
                params["continuation-token"] = token
            for attempt in range(retries):
                try:
                    resp = http.get(BUCKET_URL.format(bucket=name), params=params, timeout=timeout)
                    resp.raise_for_status()
                    break
                except Exception as exc:  # noqa: BLE001
                    if attempt == retries - 1:
                        raise
                    wait = 3 * (attempt + 1)
                    logger.warning("listing %s/%s failed (attempt %d of %d: %s); retrying in %d s",
                                   name, prefix, attempt + 1, retries, exc, wait)
                    time.sleep(wait)
            files.extend(parse_listing(resp.text, name))
            root = ElementTree.fromstring(resp.text)
            token = root.findtext(f"{_S3_NS}NextContinuationToken")
            if not token:
                break
        hour += timedelta(hours=1)
    return sorted((f for f in files if start <= f.start <= end), key=lambda f: f.start)


def nearest_files(files: list[AbiFile], times: list[datetime], *, tolerance_min: float = 35.0) -> dict[datetime, AbiFile]:
    """For each wanted time the file whose scan start is nearest, within ``tolerance_min``."""
    out = {}
    for t in times:
        if not files:
            break
        best = min(files, key=lambda f: abs((f.start - t).total_seconds()))
        if abs((best.start - t).total_seconds()) <= tolerance_min * 60:
            out[t] = best
    return out


def default_cache_dir() -> Path:
    """Return the host-neutral GOES cache outside the source checkout."""

    configured = os.environ.get("BRC_TOOLS_GOES_CACHE")
    if configured:
        return Path(configured).expanduser()
    xdg = os.environ.get("XDG_CACHE_HOME")
    root = Path(xdg).expanduser() if xdg else Path.home() / ".cache"
    return root / "brc-tools" / "goes"


def fetch_abi(files: list[AbiFile], dest_dir: str | Path | None = None, *, session=None, timeout: float = 300.0,
              retries: int = 3) -> list[Path]:
    """Download ``files`` into ``dest_dir``; a file already present at the listed size is kept.

    ``dest_dir`` defaults to :func:`default_cache_dir` (``$BRC_TOOLS_GOES_CACHE``, else
    ``~/.cache/brc-tools/goes``), so by default no download lands in the checkout (an
    explicit relative ``dest_dir`` still resolves against the working directory). Failed downloads are retried ``retries`` times, each retry logged.
    """
    import requests

    http = session or requests.Session()
    dest = Path(dest_dir).expanduser() if dest_dir else default_cache_dir()
    dest.mkdir(parents=True, exist_ok=True)
    paths = []
    for f in files:
        path = dest / f.name
        if not (path.exists() and path.stat().st_size == f.size):
            for attempt in range(retries):
                try:
                    with http.get(f.url, stream=True, timeout=timeout) as resp:
                        resp.raise_for_status()
                        part = path.with_suffix(path.suffix + ".part")
                        with open(part, "wb") as fh:
                            for chunk in resp.iter_content(1 << 20):
                                fh.write(chunk)
                        part.replace(path)
                    break
                except Exception as exc:  # noqa: BLE001
                    if attempt == retries - 1:
                        raise
                    wait = 5 * (attempt + 1)
                    logger.warning("download of %s failed (attempt %d of %d: %s); retrying in %d s",
                                   f.name, attempt + 1, retries, exc, wait)
                    time.sleep(wait)
        paths.append(path)
    return paths


@dataclass(frozen=True)
class GoesProjection:
    """The fixed-grid navigation constants of one satellite."""
    perspective_point_height: float     # m, above the ellipsoid
    semi_major_axis: float              # m
    semi_minor_axis: float              # m
    longitude_of_projection_origin: float   # degrees east

    @property
    def h(self) -> float:
        """Distance from the Earth's centre to the satellite (m)."""
        return self.perspective_point_height + self.semi_major_axis

    @classmethod
    def from_variable(cls, var) -> "GoesProjection":
        """From a netCDF4 ``goes_imager_projection`` variable."""
        return cls(float(var.perspective_point_height), float(var.semi_major_axis),
                   float(var.semi_minor_axis), float(var.longitude_of_projection_origin))


def scan_angles(lat, lon, proj: GoesProjection, height_m=0.0):
    """``(x, y)`` scan angles (radians) at which the satellite sees a point at ``lat``, ``lon``
    (degrees) and ``height_m`` above the ellipsoid; NaN where the point is over the limb."""
    lat_r = np.radians(np.asarray(lat, dtype=float))
    dlon = np.radians(np.asarray(lon, dtype=float) - proj.longitude_of_projection_origin)
    r_eq, r_pol = proj.semi_major_axis, proj.semi_minor_axis
    e2 = (r_eq ** 2 - r_pol ** 2) / r_eq ** 2
    lat_c = np.arctan((r_pol ** 2 / r_eq ** 2) * np.tan(lat_r))
    r_c = r_pol / np.sqrt(1.0 - e2 * np.cos(lat_c) ** 2) + np.asarray(height_m, dtype=float)
    s_x = proj.h - r_c * np.cos(lat_c) * np.cos(dlon)
    s_y = -r_c * np.cos(lat_c) * np.sin(dlon)
    s_z = r_c * np.sin(lat_c)
    visible = proj.h * (proj.h - s_x) >= s_y ** 2 + (r_eq ** 2 / r_pol ** 2) * s_z ** 2
    y = np.arctan(s_z / s_x)
    x = np.arcsin(-s_y / np.sqrt(s_x ** 2 + s_y ** 2 + s_z ** 2))
    return np.where(visible, x, np.nan), np.where(visible, y, np.nan)


def lonlat_from_scan(x, y, proj: GoesProjection):
    """``(lon, lat)`` in degrees of the ellipsoid point seen at scan angles ``x``, ``y`` (radians); NaN off the disc."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    r_eq, r_pol, h = proj.semi_major_axis, proj.semi_minor_axis, proj.h
    a = np.sin(x) ** 2 + np.cos(x) ** 2 * (np.cos(y) ** 2 + (r_eq ** 2 / r_pol ** 2) * np.sin(y) ** 2)
    b = -2.0 * h * np.cos(x) * np.cos(y)
    c = h ** 2 - r_eq ** 2
    disc = b ** 2 - 4.0 * a * c
    with np.errstate(invalid="ignore"):
        r_s = (-b - np.sqrt(disc)) / (2.0 * a)
    s_x = r_s * np.cos(x) * np.cos(y)
    s_y = -r_s * np.sin(x)
    s_z = r_s * np.cos(x) * np.sin(y)
    lat = np.degrees(np.arctan((r_eq ** 2 / r_pol ** 2) * s_z / np.sqrt((h - s_x) ** 2 + s_y ** 2)))
    lon = proj.longitude_of_projection_origin - np.degrees(np.arctan(s_y / (h - s_x)))
    return np.where(disc >= 0, lon, np.nan), np.where(disc >= 0, lat, np.nan)


def nearest_index(coord: np.ndarray, values) -> np.ndarray:
    """Index of the nearest element of a regularly spaced coordinate; -1 outside it or for NaN."""
    coord = np.asarray(coord, dtype=float)
    v = np.asarray(values, dtype=float)
    step = (coord[-1] - coord[0]) / (coord.size - 1)
    with np.errstate(invalid="ignore"):
        idx = np.rint((v - coord[0]) / step)
    bad = ~np.isfinite(idx) | (idx < 0) | (idx > coord.size - 1)
    return np.where(bad, -1, idx).astype(int)


@dataclass(frozen=True)
class LatLonField:
    """A field resampled to a regular lat/lon grid (rows north to south)."""
    lon: np.ndarray          # 1-D, west to east
    lat: np.ndarray          # 1-D, north to south
    values: np.ndarray       # (lat, lon); NaN where missing or screened out
    quality: np.ndarray      # (lat, lon) the product's quality flag; -1 where there is no pixel
    time: datetime           # scan start, UTC-naive
    name: str
    units: str
    source: str


def sample_on_latlon(path: str | Path, extent: tuple[float, float, float, float], *, variable: str = "LST",
                     quality_variable: str | None = "DQF", max_quality: int | None = 0, res_deg: float = 0.02,
                     height_m=None) -> LatLonField:
    """Nearest-pixel resample of one ABI L2 field onto a lat/lon grid.

    ``extent`` is ``(lon_w, lon_e, lat_s, lat_n)``. Pixels whose quality flag exceeds
    ``max_quality`` become NaN (``None`` keeps everything). ``height_m`` -- a scalar or a
    ``(lat, lon)`` array on the target grid, metres above the ellipsoid -- moves each target
    point up to its terrain before the scan angles are computed (parallax correction). The
    navigation constants, sub-satellite longitude included, are the file's own, so a GOES-East
    file is navigated (and its parallax set) from 75 W and a GOES-West one from 137 W.
    """
    import netCDF4

    lon_w, lon_e, lat_s, lat_n = extent
    lon = np.arange(lon_w, lon_e + res_deg / 2, res_deg)
    lat = np.arange(lat_n, lat_s - res_deg / 2, -res_deg)
    lon2, lat2 = np.meshgrid(lon, lat)
    with netCDF4.Dataset(str(path)) as nc:
        proj = GoesProjection.from_variable(nc.variables["goes_imager_projection"])
        xs = np.asarray(nc.variables["x"][:], dtype=float)
        ys = np.asarray(nc.variables["y"][:], dtype=float)
        sx, sy = scan_angles(lat2, lon2, proj, 0.0 if height_m is None else height_m)
        ix, iy = nearest_index(xs, sx), nearest_index(ys, sy)
        inside = (ix >= 0) & (iy >= 0)
        var = nc.variables[variable]
        data = np.ma.filled(np.ma.asarray(var[:], dtype=float), np.nan)
        values = np.full(lon2.shape, np.nan)
        values[inside] = data[iy[inside], ix[inside]]
        quality = np.full(lon2.shape, -1, dtype=int)
        if quality_variable and quality_variable in nc.variables:
            # the flag is stored unsigned: widen before the fill value, which is negative
            q = np.ma.filled(np.ma.asarray(nc.variables[quality_variable][:]).astype(np.int64), -1)
            quality[inside] = q[iy[inside], ix[inside]]
            if max_quality is not None:
                values[(quality > max_quality) | (quality < 0)] = np.nan
        units = getattr(var, "units", "")
        start = _start_time(Path(path).name) or datetime.strptime(str(nc.time_coverage_start)[:19], "%Y-%m-%dT%H:%M:%S")
        source = f"{getattr(nc, 'platform_ID', '')} {getattr(nc, 'title', variable)}".strip()
    return LatLonField(lon, lat, values, quality, start, variable, units, source)

"""NEXRAD Level-II access and sweep geolocation.

Two layers, deliberately separated so the useful part is testable without a
network:

**Pure geometry** -- :func:`sweep_from_level2` and :func:`geolocate_sweep` take an
already-decoded volume and turn one sweep into gate latitudes, longitudes and
beam heights.  No I/O, and the beam heights come from
:mod:`brc_tools.radar.beam`, so an observed sweep and a model field sampled onto
the same surface are on the same geometry by construction.

**Discovery and fetch** -- :func:`list_keys`, :func:`available_volumes` and
:func:`fetch_volume`, over plain HTTPS against a public bucket.

Dependencies: none new.  ``metpy.io.Level2File`` decodes Archive II including its
internal BZ2 chunks, and the bucket listing is ``requests`` plus the standard
library's XML parser -- no cloud SDK, since both mirrors answer the same
``ListBucketResult`` dialect.

Transport, as actually probed on 2026-07-30 -- worth writing down because three of
the four obvious routes do not work:

* **NCEI** publishes no plain Level-II archive path; ``/data/`` carries Level-3
  products and coverages only.
* **Unidata THREDDS** offers a rolling real-time collection and a case study, no
  archive; its ``nexrad/level2/S3`` path returns a server-side
  ``NullPointerException``.
* **The GCS mirror** lists anonymously and works, but its coverage stops between
  2025-08-01 and 2025-09-15.
* **AWS** is the authoritative archive.  Anonymous listing through the global
  endpoint returned ``AccessDenied`` and the regional endpoint was unreachable
  from a restricted network, so it is **unverified from a sandbox** and needs a
  probe from a DTN node.

Every function that touches the network says so in its docstring; run them from a
SLURM job on a DTN, not a login node and not a sandbox.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from brc_tools.radar.beam import beam_height_asl
from brc_tools.radar.sites import RadarSite, get_site

#: Public HTTPS mirrors of the NEXRAD Level-II archive, keyed by short name.
#:
#: Both answer the S3 ``ListBucketResult`` XML dialect, so :func:`list_keys` needs
#: no cloud SDK.  What they do *not* share is coverage, and that decides which one
#: can serve a given case (probed 2026-07-30):
#:
#: ``aws``
#:     The authoritative archive.  Anonymous listing via the **global** endpoint
#:     returned ``AccessDenied``, and the regional endpoint was unreachable from a
#:     restricted network, so this mirror is unverified from a sandbox; it should
#:     be exercised from a DTN node.
#: ``gcs``
#:     Anonymous listing verified working, but coverage **stops between
#:     2025-08-01 and 2025-09-15**, so it cannot serve an October 2025 case.
#:     Keys are hourly ``.tar`` bundles, not individual volumes.
#:
#: Unidata's THREDDS radar server is deliberately not used: its catalogue offers
#: only ``nexrad/level2/IDD`` (a rolling real-time window) and a case-study
#: collection, with no archive, and the ``.../level2/S3/`` path returns a
#: server-side ``NullPointerException``.
MIRRORS: dict[str, str] = {
    "aws": "https://noaa-nexrad-level2.s3.amazonaws.com",
    "gcs": "https://storage.googleapis.com/gcp-public-data-nexrad-l2",
}

#: Mirror used when none is named.
DEFAULT_MIRROR = "aws"


def _mirror_url(mirror: str) -> str:
    """Resolve a mirror short name, or accept a full base URL verbatim."""
    if mirror.startswith("http"):
        return mirror
    try:
        return MIRRORS[mirror]
    except KeyError:
        raise KeyError(
            f"unknown mirror {mirror!r}; known: {sorted(MIRRORS)} (or pass a base URL)"
        ) from None

#: Cache root for downloaded volumes.  Each file gets a ``.json`` provenance
#: sidecar beside it, mirroring :mod:`brc_tools.satellite.modis`.
CACHE_ENV = "BRC_TOOLS_RADAR_CACHE"

#: Moment keys in a Level-II volume.  Bytes, because that is how MetPy keys them.
MOMENT_REFLECTIVITY = b"REF"
MOMENT_VELOCITY = b"VEL"
MOMENT_SPECTRUM_WIDTH = b"SW"


def cache_dir() -> Path:
    """Resolve the volume cache directory (env-overridable, never in the repo)."""
    root = os.environ.get(CACHE_ENV)
    return Path(root) if root else Path.home() / ".cache" / "brc-tools" / "nexrad"


@dataclass(frozen=True)
class RadarSweep:
    """One elevation sweep of one moment, on its native polar grid.

    ``values`` is ``(n_azimuths, n_gates)`` in the moment's own units (dBZ for
    reflectivity), with non-detections and range folding as NaN.
    """

    site_id: str
    valid_time: datetime
    elevation_deg: float
    moment: str
    azimuth_deg: np.ndarray  # (n_az,)
    range_m: np.ndarray  # (n_gates,)
    values: np.ndarray  # (n_az, n_gates)

    @property
    def nominal_elevation_deg(self) -> float:
        """The sweep's mean elevation, which is what a beam surface should use."""
        return float(self.elevation_deg)


def sweep_elevations(level2) -> list[float]:
    """Mean elevation angle (degrees) of every sweep in a decoded volume."""
    out = []
    for sweep in level2.sweeps:
        if not sweep:
            continue
        out.append(float(np.mean([ray[0].el_angle for ray in sweep])))
    return out


def sweep_from_level2(
    level2,
    elevation_deg: float,
    *,
    moment: bytes = MOMENT_REFLECTIVITY,
    max_elevation_mismatch_deg: float = 0.3,
) -> RadarSweep:
    """Extract the sweep closest to ``elevation_deg`` from a decoded volume.

    Raises if the nearest sweep is further than ``max_elevation_mismatch_deg``
    away, rather than silently returning a different tilt: the whole point of a
    beam-matched comparison is that the elevation is the one you asked for, and a
    VCP that lacks the requested tilt should be an error, not a substitution.
    """
    elevations = sweep_elevations(level2)
    if not elevations:
        raise ValueError("volume contains no sweeps")

    # Operational VCPs use SPLIT CUTS: the low tilts appear twice, once carrying
    # reflectivity and once carrying velocity (a real KGJX volume reads
    # [-0.04, -0.04, 0.44, 0.44, 1.49, 1.49, ...]). So do not just take the
    # nearest sweep -- walk candidates outward from the requested angle and take
    # the first that actually carries the moment asked for, or a velocity request
    # lands on the reflectivity half of the pair and fails for no good reason.
    order = np.argsort(np.abs(np.asarray(elevations) - elevation_deg))
    within = [i for i in order if abs(elevations[i] - elevation_deg) <= max_elevation_mismatch_deg]
    if not within:
        nearest = int(order[0])
        raise ValueError(
            f"no sweep within {max_elevation_mismatch_deg} deg of {elevation_deg} deg; "
            f"nearest is {elevations[nearest]:.2f} deg. Available: "
            f"{[round(e, 2) for e in elevations]}"
        )

    idx = rays = None
    for candidate in within:
        found = [ray for ray in level2.sweeps[candidate] if moment in ray[4]]
        if found:
            idx, rays = candidate, found
            break
    if rays is None:
        have = sorted(
            {k.decode() for i in within for ray in level2.sweeps[i] for k in ray[4]}
        )
        tilts = [round(elevations[i], 2) for i in within]
        raise ValueError(
            f"no sweep near {elevation_deg} deg carries the {moment.decode()} moment; "
            f"tilts {tilts} carry {have}."
        )

    hdr = rays[0][4][moment][0]
    # MetPy reports first_gate and gate_width in KILOMETRES, so convert once here
    # and keep metres everywhere downstream -- beam.py is all metres.
    rng_km = np.arange(hdr.num_gates) * hdr.gate_width + hdr.first_gate
    az = np.array([ray[0].az_angle for ray in rays], dtype=float)

    # MetPy masks below-threshold and range-folded gates; unmask to NaN first, so
    # the later isfinite pass sees real values rather than a masked array's fill.
    stack = [ray[4][moment][1] for ray in rays]
    values = np.ma.filled(np.ma.masked_invalid(np.ma.asarray(stack, dtype=float)), np.nan)

    stid = getattr(level2, "stid", "")
    if isinstance(stid, (bytes, bytearray)):
        stid = stid.decode("ascii", errors="replace")

    order = np.argsort(az)
    return RadarSweep(
        site_id=str(stid or "").strip(),
        valid_time=getattr(level2, "dt", None),
        elevation_deg=float(elevations[idx]),
        moment=moment.decode(),
        azimuth_deg=az[order],
        range_m=np.asarray(rng_km, dtype=float) * 1000.0,
        values=values[order],
    )


def geolocate_sweep(
    sweep: RadarSweep, site: RadarSite | str | None = None
) -> dict[str, np.ndarray]:
    """Gate latitudes, longitudes and beam heights for a sweep.

    Returns ``{"latitude", "longitude", "height_asl_m"}``, each ``(n_az, n_gates)``.

    Heights come from :func:`brc_tools.radar.beam.beam_height_asl`, so an observed
    sweep and a model field sampled with ``beam_surface_asl`` sit on the same
    surface by construction rather than by coincidence.

    Positions use a spherical forward solution along each azimuth.  Ground range
    is taken as the slant range, which at these ranges and the shallow tilts a
    WSR-88D scans is a much smaller error than the beamwidth.
    """
    if site is None:
        site = sweep.site_id
    if isinstance(site, str):
        site = get_site(site)

    az = np.deg2rad(sweep.azimuth_deg)[:, np.newaxis]
    rng = sweep.range_m[np.newaxis, :]

    earth_r = 6_371_000.0
    delta = rng / earth_r
    lat0 = np.deg2rad(site.lat)
    lon0 = np.deg2rad(site.lon)

    sin_lat = np.sin(lat0) * np.cos(delta) + np.cos(lat0) * np.sin(delta) * np.cos(az)
    lat = np.arcsin(np.clip(sin_lat, -1.0, 1.0))
    lon = lon0 + np.arctan2(
        np.sin(az) * np.sin(delta) * np.cos(lat0),
        np.cos(delta) - np.sin(lat0) * sin_lat,
    )

    height = beam_height_asl(rng, sweep.elevation_deg, site.alt_m)
    return {
        "latitude": np.rad2deg(lat),
        "longitude": (np.rad2deg(lon) + 180.0) % 360.0 - 180.0,
        "height_asl_m": np.broadcast_to(height, lat.shape).copy(),
    }


def read_sweep(
    path: str | Path,
    elevation_deg: float,
    *,
    moment: bytes = MOMENT_REFLECTIVITY,
    **kwargs,
) -> RadarSweep:
    """Decode a Level-II file and extract one sweep.

    Thin wrapper: :class:`metpy.io.Level2File` handles the Archive II format
    including its internal BZ2 compression, then :func:`sweep_from_level2` does
    the selection.  Kept separate so the selection logic is testable without a
    binary fixture.
    """
    from metpy.io import Level2File

    return sweep_from_level2(Level2File(str(path)), elevation_deg, moment=moment, **kwargs)


# --------------------------------------------------------------------------- #
# Discovery and fetch -- these touch the network
# --------------------------------------------------------------------------- #
def list_keys(prefix: str, *, mirror: str = DEFAULT_MIRROR, max_keys: int = 1000) -> list[str]:
    """Object keys under ``prefix`` in a Level-II mirror.

    **Touches the network.**  Both mirrors answer the S3 ``ListBucketResult`` XML
    dialect, so one parser serves either; ``requests`` is enough and no cloud SDK
    is needed.  Verified against the GCS mirror, whose response is byte-compatible
    with S3's.
    """
    import xml.etree.ElementTree as ET

    import requests

    base = _mirror_url(mirror)
    keys: list[str] = []
    token: str | None = None
    while True:
        params = {"prefix": prefix, "max-keys": str(max_keys)}
        if token:
            params["marker"] = token
        response = requests.get(base, params=params, timeout=(10.0, 120.0))
        response.raise_for_status()
        root = ET.fromstring(response.content)
        ns = {"s3": root.tag.split("}")[0].strip("{")} if "}" in root.tag else {}
        found = [
            el.text
            for el in root.findall(".//s3:Contents/s3:Key" if ns else ".//Contents/Key", ns)
            if el.text
        ]
        keys.extend(found)
        truncated = root.find("s3:IsTruncated" if ns else "IsTruncated", ns)
        if truncated is None or (truncated.text or "").lower() != "true" or not found:
            break
        token = found[-1]
    return keys


def available_volumes(
    site_id: str,
    start: datetime,
    end: datetime,
    *,
    mirror: str = DEFAULT_MIRROR,
) -> list[tuple[str, str]]:
    """List ``(name, url)`` of Level-II volumes for a site over a time window.

    **Touches the network.** Run it from a DTN SLURM job, not a restricted
    sandbox and not a login node.

    Handles both key layouts in use: AWS's per-volume ``KGJX20251012_021500_V06``
    and the hourly ``NWS_NEXRAD_NXL2DPBL_KGJX_<start>_<end>.tar`` bundles the GCS
    mirror publishes (see :func:`iter_tar_volumes`).  Volumes are kept when their
    encoded time falls in ``[start, end]``; for an hourly bundle that is its start
    stamp, so widen the window by an hour if you need the bundle containing a time
    near the top of the hour.
    """
    base = _mirror_url(mirror)
    site = site_id.upper()
    seen: dict[str, str] = {}

    # A window may straddle midnight, so walk every day it touches.
    day = datetime(start.year, start.month, start.day)
    while day <= end:
        prefix = f"{day:%Y/%m/%d}/{site}/"
        for key in list_keys(prefix, mirror=mirror):
            stamp = _time_from_name(key.rsplit("/", 1)[-1])
            if stamp is None or not (start <= stamp <= end):
                continue
            name = key.rsplit("/", 1)[-1]
            seen[name] = f"{base.rstrip('/')}/{key}"
        day = day.replace(hour=0) + timedelta(days=1)
    return sorted(seen.items())


def iter_tar_volumes(path: str | Path):
    """Yield ``(member_name, bytes)`` for each volume inside an hourly ``.tar``.

    The GCS mirror (and NCEI's bulk order format) bundles an hour of scans into
    one tar rather than publishing individual volumes, so a bundle has to be
    unpacked before :class:`metpy.io.Level2File` sees anything.
    """
    import tarfile

    with tarfile.open(path) as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            handle = archive.extractfile(member)
            if handle is not None:
                yield member.name, handle.read()


def fetch_volume(
    url: str,
    *,
    dest_dir: str | Path | None = None,
    name: str | None = None,
    connect_timeout: float = 10.0,
    read_timeout: float = 300.0,
    retries: int = 3,
    backoff: float = 2.0,
) -> Path:
    """Download one Level-II volume into the cache, returning its path.

    **Touches the network.** Skips the download when the file is already cached.
    Writes a ``<file>.json`` provenance sidecar recording the source URL and the
    byte count, so a cached volume can be traced later -- the same convention
    :mod:`brc_tools.satellite.modis` uses.

    Reuses the staging module's IPv4-only workaround: outbound IPv6 from a CHPC
    DTN to these hosts has been observed to hang in SYN-SENT indefinitely.
    """
    import requests

    # Single source of truth for the DTN IPv6 workaround; see wrf_staging.
    from brc_tools.nwp.wrf_staging import _install_ipv4_only, _ipv4_only_requested

    if _ipv4_only_requested():
        _install_ipv4_only()

    out_dir = Path(dest_dir) if dest_dir is not None else cache_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / (name or url.rstrip("/").split("/")[-1])
    if dest.exists() and dest.stat().st_size > 0:
        return dest

    last: Exception | None = None
    for attempt in range(retries):
        try:
            with requests.get(
                url, stream=True, timeout=(connect_timeout, read_timeout)
            ) as response:
                response.raise_for_status()
                tmp = dest.with_suffix(dest.suffix + ".part")
                written = 0
                with tmp.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1 << 20):
                        if chunk:
                            handle.write(chunk)
                            written += len(chunk)
                tmp.replace(dest)
            dest.with_suffix(dest.suffix + ".json").write_text(
                json.dumps(
                    {"source_url": url, "bytes": written, "cache": str(out_dir)},
                    indent=2,
                ),
                encoding="utf-8",
            )
            return dest
        except Exception as exc:  # noqa: BLE001 - retried, then re-raised
            last = exc
            if attempt < retries - 1:
                import time

                time.sleep(backoff * (attempt + 1))
    raise RuntimeError(f"failed to fetch {url} after {retries} attempts: {last}")


def nearest_volume(
    site_id: str, target: datetime, *, window_minutes: float = 15.0, **kwargs
) -> tuple[str, str] | None:
    """The volume whose name-encoded time is closest to ``target``.

    **Touches the network** (via :func:`available_volumes`).  Returns ``None`` if
    the window holds nothing.  A WSR-88D volume takes 4-6 minutes, so a target
    time generally falls inside a scan rather than at its start.
    """
    span = timedelta(minutes=window_minutes)
    volumes = available_volumes(site_id, target - span, target + span, **kwargs)
    if not volumes:
        return None

    def _key(item: tuple[str, str]) -> float:
        stamp = _time_from_name(item[0])
        return abs((stamp - target).total_seconds()) if stamp else float("inf")

    return min(volumes, key=_key)


def _time_from_name(name: str) -> datetime | None:
    """Parse the timestamp out of a volume or bundle name.

    Two layouts are in use and both must work, or a whole mirror's keys get
    silently dropped by the time filter:

    * AWS per-volume: ``KGJX20251012_021500_V06`` -- 8 digits, underscore, 6.
    * GCS hourly bundle: ``NWS_NEXRAD_NXL2DPBL_KGJX_20251012020000_...tar``
      -- 14 consecutive digits, no separator.
    """
    import re

    match = re.search(r"(\d{8})_(\d{6})(?!\d)", name)
    stamp = (match.group(1) + match.group(2)) if match else None
    if stamp is None:
        match = re.search(r"(?<!\d)(\d{14})(?!\d)", name)
        stamp = match.group(1) if match else None
    if stamp is None:
        return None
    try:
        return datetime.strptime(stamp, "%Y%m%d%H%M%S")
    except ValueError:
        return None

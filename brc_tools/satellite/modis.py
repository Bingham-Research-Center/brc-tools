"""Portable MODIS context imagery from NASA CMR metadata and GIBS maps.

The renderer deliberately does not download or decode the original HDF-EOS swath.
NASA CMR identifies the Terra/Aqua granule whose footprint covers the center of the
requested map, and NASA GIBS supplies a georeferenced daily corrected-reflectance PNG
for that platform and date.  This keeps the runtime to ``requests`` + Matplotlib and
works on a laptop, Akamai, or a CHPC host with the same small cache staged offline.

The selected CMR granule provides the closest observation time.  GIBS itself has a
date (not granule) time dimension, so the provenance sidecar records that distinction
explicitly rather than claiming that the WMS response is a raw granule crop.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import platform as runtime_platform
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import requests

CMR_GRANULES_URL = "https://cmr.earthdata.nasa.gov/search/granules.json"
GIBS_WMS_URL = "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"
CMR_COLLECTION_VERSION = "6.1"
SCHEMA_VERSION = 1

_PLATFORMS = {
    "Terra": {"short_name": "MOD02HKM", "gibs_prefix": "MODIS_Terra"},
    "Aqua": {"short_name": "MYD02HKM", "gibs_prefix": "MODIS_Aqua"},
}

_PRODUCTS = {
    "true-color": {
        "suffix": "CorrectedReflectance_TrueColor",
        "title": "Corrected reflectance: true color",
        "key": "true_color",
        "guide": "snow and cloud both appear white",
    },
    "snow-false-color": {
        "suffix": "CorrectedReflectance_Bands721",
        "title": "Corrected reflectance: bands 7-2-1",
        "key": "snow_false_color",
        "guide": "snow/ice: cyan; most liquid cloud: white",
    },
}


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(value: str) -> datetime:
    """Parse an ISO-8601 timestamp and return an aware UTC datetime."""

    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include Z or an explicit UTC offset")
    return parsed.astimezone(timezone.utc)


def validate_bbox(bbox: Sequence[float]) -> tuple[float, float, float, float]:
    """Return ``(west, south, east, north)`` after geographic validation."""

    if len(bbox) != 4:
        raise ValueError("bbox must contain west south east north")
    west, south, east, north = (float(value) for value in bbox)
    if not (-180.0 <= west < east <= 180.0):
        raise ValueError("bbox longitudes must satisfy -180 <= west < east <= 180")
    if not (-90.0 <= south < north <= 90.0):
        raise ValueError("bbox latitudes must satisfy -90 <= south < north <= 90")
    return west, south, east, north


def default_cache_dir() -> Path:
    """Return the host-neutral MODIS cache outside the source checkout."""

    configured = os.environ.get("BRC_TOOLS_MODIS_CACHE")
    if configured:
        return Path(configured).expanduser()
    xdg = os.environ.get("XDG_CACHE_HOME")
    root = Path(xdg).expanduser() if xdg else Path.home() / ".cache"
    return root / "brc-tools" / "modis"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_token(payload: Mapping[str, Any], length: int = 16) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return _sha256(encoded)[:length]


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(content)
    temporary.replace(path)


def _prepared_url(url: str, params: Mapping[str, Any]) -> str:
    prepared = requests.Request("GET", url, params=params).prepare().url
    if prepared is None:  # pragma: no cover - requests always provides it here
        raise RuntimeError(f"could not prepare request URL for {url}")
    return prepared


def _get_with_retry(
    session: requests.Session,
    url: str,
    *,
    params: Mapping[str, Any],
    timeout: float,
    attempts: int = 3,
) -> requests.Response:
    """GET with bounded exponential backoff at the external-API boundary."""

    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = session.get(
                url,
                params=params,
                timeout=timeout,
                headers={"User-Agent": "brc-tools MODIS context renderer"},
            )
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(0.5 * (2**attempt))
    raise RuntimeError(f"request failed after {attempts} attempts: {url}") from last_error


def _parse_cmr_time(value: str) -> datetime:
    return parse_utc(value)


def _link(entry: Mapping[str, Any], relation_suffix: str) -> str | None:
    for item in entry.get("links", []):
        if str(item.get("rel", "")).endswith(relation_suffix):
            href = item.get("href")
            if href:
                return str(href)
    return None


@dataclass(frozen=True)
class Granule:
    """A center-covering MODIS Level-1B granule returned by NASA CMR."""

    platform: str
    short_name: str
    collection_version: str
    producer_granule_id: str
    concept_id: str
    collection_concept_id: str
    time_start: datetime
    time_end: datetime
    day_night_flag: str
    data_url: str | None = None
    browse_url: str | None = None

    @property
    def midpoint(self) -> datetime:
        return self.time_start + (self.time_end - self.time_start) / 2

    def offset_seconds(self, target: datetime) -> float:
        return (self.midpoint - target).total_seconds()

    def to_dict(self, *, target: datetime | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "platform": self.platform,
            "short_name": self.short_name,
            "collection_version": self.collection_version,
            "producer_granule_id": self.producer_granule_id,
            "concept_id": self.concept_id,
            "collection_concept_id": self.collection_concept_id,
            "time_start_utc": _utc_text(self.time_start),
            "time_end_utc": _utc_text(self.time_end),
            "midpoint_utc": _utc_text(self.midpoint),
            "day_night_flag": self.day_night_flag,
            "data_url": self.data_url,
            "browse_url": self.browse_url,
        }
        if target is not None:
            result["midpoint_offset_seconds_from_target"] = self.offset_seconds(target)
        return result

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Granule:
        return cls(
            platform=str(payload["platform"]),
            short_name=str(payload["short_name"]),
            collection_version=str(payload["collection_version"]),
            producer_granule_id=str(payload["producer_granule_id"]),
            concept_id=str(payload["concept_id"]),
            collection_concept_id=str(payload["collection_concept_id"]),
            time_start=parse_utc(str(payload["time_start_utc"])),
            time_end=parse_utc(str(payload["time_end_utc"])),
            day_night_flag=str(payload.get("day_night_flag", "")),
            data_url=payload.get("data_url"),
            browse_url=payload.get("browse_url"),
        )


@dataclass(frozen=True)
class Discovery:
    """Closest granule plus every candidate considered in the same search."""

    target: datetime
    bbox: tuple[float, float, float, float]
    center: tuple[float, float]
    selected: Granule
    candidates: tuple[Granule, ...]
    query_urls: tuple[str, ...]
    cache_file: Path


@dataclass(frozen=True)
class GibsImage:
    """One cached NASA GIBS product and its exact request metadata."""

    product: str
    layer: str
    date: str
    width: int
    height: int
    request_url: str
    cache_file: Path
    sha256: str
    content: bytes


@dataclass(frozen=True)
class RenderResult:
    """Paths and selected acquisition returned by :func:`render_context`."""

    discovery: Discovery
    images: tuple[GibsImage, ...]
    outputs: Mapping[str, str]
    provenance_path: Path


def _granule_from_entry(entry: Mapping[str, Any], platform: str) -> Granule:
    info = _PLATFORMS[platform]
    return Granule(
        platform=platform,
        short_name=str(info["short_name"]),
        collection_version=CMR_COLLECTION_VERSION,
        producer_granule_id=str(entry["producer_granule_id"]),
        concept_id=str(entry["id"]),
        collection_concept_id=str(entry["collection_concept_id"]),
        time_start=_parse_cmr_time(str(entry["time_start"])),
        time_end=_parse_cmr_time(str(entry["time_end"])),
        day_night_flag=str(entry.get("day_night_flag", "")),
        data_url=_link(entry, "data#"),
        browse_url=_link(entry, "browse#"),
    )


def _platform_names(platform: str) -> tuple[str, ...]:
    normalised = platform.strip().lower()
    if normalised == "auto":
        return ("Terra", "Aqua")
    if normalised == "terra":
        return ("Terra",)
    if normalised == "aqua":
        return ("Aqua",)
    raise ValueError("platform must be auto, terra, or aqua")


def discover_granules(
    target: datetime,
    bbox: Sequence[float],
    *,
    platform: str = "auto",
    search_hours: float = 12.0,
    cache_dir: Path | str | None = None,
    offline: bool = False,
    refresh: bool = False,
    session: requests.Session | None = None,
    timeout: float = 30.0,
) -> Discovery:
    """Find the closest daytime Terra/Aqua granule covering the map center.

    The CMR spatial query uses the center point, not merely a bounding-box
    intersection.  This prevents an adjacent five-minute swath that clips one map edge
    from winning the time comparison while missing the basin itself.
    """

    target = target.astimezone(timezone.utc)
    checked_bbox = validate_bbox(bbox)
    if search_hours <= 0:
        raise ValueError("search_hours must be positive")
    if offline and refresh:
        raise ValueError("offline and refresh cannot be used together")

    west, south, east, north = checked_bbox
    center = ((west + east) / 2.0, (south + north) / 2.0)
    platforms = _platform_names(platform)
    start = target - timedelta(hours=search_hours)
    end = target + timedelta(hours=search_hours)
    query_descriptor = {
        "schema_version": SCHEMA_VERSION,
        "target_utc": _utc_text(target),
        "bbox": list(checked_bbox),
        "center": list(center),
        "platforms": list(platforms),
        "search_hours": search_hours,
        "collection_version": CMR_COLLECTION_VERSION,
    }
    cache_root = Path(cache_dir).expanduser() if cache_dir else default_cache_dir()
    cache_file = cache_root / f"cmr_granules_{_json_token(query_descriptor)}.json"

    query_urls: list[str] = []
    candidates: list[Granule] = []
    if cache_file.exists() and not refresh:
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        query_urls = [str(url) for url in cached.get("query_urls", [])]
        candidates = [Granule.from_dict(item) for item in cached.get("granules", [])]
    else:
        if offline:
            raise FileNotFoundError(f"CMR cache is missing in offline mode: {cache_file}")
        client = session or requests.Session()
        for platform_name in platforms:
            params = {
                "short_name": _PLATFORMS[platform_name]["short_name"],
                "version": CMR_COLLECTION_VERSION,
                "point": f"{center[0]:.6f},{center[1]:.6f}",
                "temporal": f"{_utc_text(start)},{_utc_text(end)}",
                "page_size": 50,
            }
            query_urls.append(_prepared_url(CMR_GRANULES_URL, params))
            response = _get_with_retry(
                client, CMR_GRANULES_URL, params=params, timeout=timeout
            )
            payload = response.json()
            for entry in payload.get("feed", {}).get("entry", []):
                granule = _granule_from_entry(entry, platform_name)
                if granule.day_night_flag.upper() in ("", "DAY"):
                    candidates.append(granule)
        cache_payload = {
            "query": query_descriptor,
            "query_urls": query_urls,
            "granules": [item.to_dict(target=target) for item in candidates],
        }
        _atomic_write(
            cache_file,
            (json.dumps(cache_payload, indent=2, sort_keys=True) + "\n").encode(),
        )

    if not candidates:
        raise RuntimeError(
            "NASA CMR returned no daytime MODIS granule covering the map center "
            f"within {search_hours:g} h of {_utc_text(target)}"
        )
    selected = min(
        candidates,
        key=lambda item: (
            abs(item.offset_seconds(target)),
            0 if item.platform == "Terra" else 1,
            item.time_start,
        ),
    )
    return Discovery(
        target=target,
        bbox=checked_bbox,
        center=center,
        selected=selected,
        candidates=tuple(sorted(candidates, key=lambda item: item.time_start)),
        query_urls=tuple(query_urls),
        cache_file=cache_file,
    )


def find_closest_granule(
    target: datetime,
    bbox: Sequence[float],
    **kwargs: Any,
) -> Granule:
    """Convenience wrapper returning only the selected granule."""

    return discover_granules(target, bbox, **kwargs).selected


def _product_layer(platform: str, product: str) -> str:
    if product not in _PRODUCTS:
        choices = ", ".join(sorted(_PRODUCTS))
        raise ValueError(f"unknown product {product!r}; choose {choices}")
    return f"{_PLATFORMS[platform]['gibs_prefix']}_{_PRODUCTS[product]['suffix']}"


def _image_height(bbox: Sequence[float], width: int) -> int:
    west, south, east, north = validate_bbox(bbox)
    return max(64, round(width * (north - south) / (east - west)))


def fetch_gibs_image(
    granule: Granule,
    bbox: Sequence[float],
    product: str,
    *,
    width: int = 1600,
    height: int | None = None,
    cache_dir: Path | str | None = None,
    offline: bool = False,
    refresh: bool = False,
    session: requests.Session | None = None,
    timeout: float = 60.0,
) -> GibsImage:
    """Fetch one MODIS corrected-reflectance map from NASA GIBS WMS."""

    checked_bbox = validate_bbox(bbox)
    if not 64 <= width <= 4096:
        raise ValueError("width must be between 64 and 4096 pixels")
    resolved_height = height if height is not None else _image_height(checked_bbox, width)
    if not 64 <= resolved_height <= 4096:
        raise ValueError("height must be between 64 and 4096 pixels")
    if offline and refresh:
        raise ValueError("offline and refresh cannot be used together")

    layer = _product_layer(granule.platform, product)
    date = granule.midpoint.date().isoformat()
    params = {
        "SERVICE": "WMS",
        "VERSION": "1.1.1",
        "REQUEST": "GetMap",
        "LAYERS": layer,
        "STYLES": "default",
        "SRS": "EPSG:4326",
        "BBOX": ",".join(f"{value:.6f}" for value in checked_bbox),
        "WIDTH": width,
        "HEIGHT": resolved_height,
        "FORMAT": "image/png",
        "TRANSPARENT": "false",
        "TIME": date,
    }
    request_url = _prepared_url(GIBS_WMS_URL, params)
    descriptor = {
        "schema_version": SCHEMA_VERSION,
        "layer": layer,
        "date": date,
        "bbox": list(checked_bbox),
        "width": width,
        "height": resolved_height,
    }
    cache_root = Path(cache_dir).expanduser() if cache_dir else default_cache_dir()
    cache_file = cache_root / f"gibs_{date}_{product}_{_json_token(descriptor)}.png"

    if cache_file.exists() and not refresh:
        content = cache_file.read_bytes()
    else:
        if offline:
            raise FileNotFoundError(f"GIBS cache is missing in offline mode: {cache_file}")
        client = session or requests.Session()
        response = _get_with_retry(client, GIBS_WMS_URL, params=params, timeout=timeout)
        content = response.content
        request_url = getattr(response, "url", None) or request_url
        if not content.startswith(b"\x89PNG\r\n\x1a\n"):
            content_type = response.headers.get("Content-Type", "unknown")
            raise RuntimeError(
                f"GIBS returned {content_type}, not a PNG, for layer {layer}"
            )
        _atomic_write(cache_file, content)

    if not content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError(f"cached GIBS file is not a PNG: {cache_file}")
    return GibsImage(
        product=product,
        layer=layer,
        date=date,
        width=width,
        height=resolved_height,
        request_url=request_url,
        cache_file=cache_file,
        sha256=_sha256(content),
        content=content,
    )


def _format_lon(value: float, _position: float) -> str:
    suffix = "W" if value < 0 else "E"
    return f"{abs(value):g}°{suffix}"


def _format_lat(value: float, _position: float) -> str:
    suffix = "S" if value < 0 else "N"
    return f"{abs(value):g}°{suffix}"


def _draw_markers(ax: Any, markers: Mapping[str, tuple[float, float]]) -> None:
    for name, (lon, lat) in markers.items():
        ax.scatter(
            [lon],
            [lat],
            s=24,
            marker="o",
            facecolor="white",
            edgecolor="black",
            linewidth=0.8,
            zorder=20,
        )
        ax.annotate(
            name,
            (lon, lat),
            xytext=(4, 3),
            textcoords="offset points",
            fontsize=7,
            color="black",
            bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.7, "pad": 1},
            zorder=21,
        )


def _render_figure(
    discovery: Discovery,
    images: Sequence[GibsImage],
    output_stem: Path,
    *,
    formats: Sequence[str],
    markers: Mapping[str, tuple[float, float]],
    title: str | None,
    dpi: int,
) -> dict[str, str]:
    import matplotlib.pyplot as plt
    from matplotlib import image as mpimg
    from matplotlib.ticker import FuncFormatter, MaxNLocator

    count = len(images)
    if not count:
        raise ValueError("at least one GIBS image is required")
    west, south, east, north = discovery.bbox
    middle_lat = (south + north) / 2.0
    panel_width = 5.6
    fig, axes = plt.subplots(
        1,
        count,
        figsize=(panel_width * count, 5.3),
        squeeze=False,
    )
    axes_flat = axes.ravel()
    heading = title or (
        f"Uinta Basin MODIS context near {discovery.target:%H:%M UTC}, "
        f"{discovery.target.day} {discovery.target:%B %Y}"
    )
    fig.suptitle(heading, fontsize=12.5, y=0.97)

    for ax, asset in zip(axes_flat, images):
        pixels = mpimg.imread(io.BytesIO(asset.content), format="png")
        ax.imshow(
            pixels,
            extent=(west, east, south, north),
            origin="upper",
            interpolation="nearest",
            zorder=0,
        )
        ax.set_xlim(west, east)
        ax.set_ylim(south, north)
        ax.set_aspect(1.0 / math.cos(math.radians(middle_lat)))
        ax.set_title(_PRODUCTS[asset.product]["title"], fontsize=9.5)
        ax.xaxis.set_major_locator(MaxNLocator(5))
        ax.yaxis.set_major_locator(MaxNLocator(5))
        ax.xaxis.set_major_formatter(FuncFormatter(_format_lon))
        ax.yaxis.set_major_formatter(FuncFormatter(_format_lat))
        ax.tick_params(labelsize=7)
        ax.grid(color="white", alpha=0.35, linewidth=0.35)
        _draw_markers(ax, markers)
        ax.text(
            0.015,
            0.015,
            _PRODUCTS[asset.product]["guide"],
            transform=ax.transAxes,
            fontsize=7,
            ha="left",
            va="bottom",
            bbox={"facecolor": "white", "edgecolor": "0.3", "alpha": 0.78, "pad": 2},
            zorder=30,
        )
    for ax in axes_flat[1:]:
        ax.tick_params(labelleft=False)
    axes_flat[0].set_ylabel("Latitude", fontsize=8)
    for ax in axes_flat:
        ax.set_xlabel("Longitude", fontsize=8)

    selected = discovery.selected
    offset_minutes = selected.offset_seconds(discovery.target) / 60.0
    acquisition = (
        f"Target {discovery.target:%H:%M UTC}; nearest center-covering {selected.platform} "
        f"granule {selected.time_start:%H:%M}–{selected.time_end:%H:%M} UTC "
        f"(midpoint {selected.midpoint:%H:%M:%S}, {offset_minutes:+.1f} min)."
    )
    source = (
        f"NASA GIBS daily corrected reflectance; NASA CMR "
        f"{selected.short_name} Collection {selected.collection_version}."
    )
    fig.text(0.5, 0.055, acquisition, ha="center", fontsize=7.3)
    fig.text(0.5, 0.027, source, ha="center", fontsize=7.3)
    fig.subplots_adjust(left=0.07, right=0.985, bottom=0.17, top=0.88, wspace=0.05)

    output_stem.parent.mkdir(parents=True, exist_ok=True)
    output_hashes: dict[str, str] = {}
    for fmt in formats:
        clean = fmt.lower().lstrip(".")
        if clean not in ("png", "pdf"):
            raise ValueError("formats must contain only png and/or pdf")
        path = output_stem.with_suffix(f".{clean}")
        metadata = {"Creator": "brc-tools MODIS context renderer", "Title": heading}
        if clean == "png":
            metadata["Software"] = metadata.pop("Creator")
        fig.savefig(path, dpi=dpi, metadata=metadata)
        output_hashes[path.name] = _sha256(path.read_bytes())
    plt.close(fig)
    return output_hashes


def _module_sha256() -> str:
    return _sha256(Path(__file__).read_bytes())


def _runtime_versions() -> dict[str, str]:
    packages = {}
    for name in ("matplotlib", "numpy", "pillow", "requests"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:  # pragma: no cover - core deps should be present
            packages[name] = "not-installed"
    return {
        "python": runtime_platform.python_version(),
        "implementation": runtime_platform.python_implementation(),
        "system": runtime_platform.system(),
        **packages,
    }


def _write_provenance(
    discovery: Discovery,
    images: Sequence[GibsImage],
    outputs: Mapping[str, str],
    output_stem: Path,
    *,
    width: int,
    height: int | None,
    dpi: int,
    markers: Mapping[str, tuple[float, float]],
    title: str | None,
) -> Path:
    selected = discovery.selected
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": _utc_text(datetime.now(timezone.utc)),
        "target_utc": _utc_text(discovery.target),
        "selection_rule": (
            "minimum absolute difference between target and midpoint of daytime "
            "Terra/Aqua MOD02HKM/MYD02HKM v6.1 granules covering bbox center"
        ),
        "bbox_west_south_east_north": list(discovery.bbox),
        "query_point_lon_lat": list(discovery.center),
        "selected_granule": selected.to_dict(target=discovery.target),
        "candidate_granules": [
            item.to_dict(target=discovery.target) for item in discovery.candidates
        ],
        "cmr": {
            "endpoint": CMR_GRANULES_URL,
            "query_urls": list(discovery.query_urls),
            "cache_file": discovery.cache_file.name,
        },
        "gibs": {
            "endpoint": GIBS_WMS_URL,
            "time_dimension": "calendar date; not a granule-specific timestamp",
            "images": [
                {
                    "product": item.product,
                    "layer": item.layer,
                    "date": item.date,
                    "width_pixels": item.width,
                    "height_pixels": item.height,
                    "request_url": item.request_url,
                    "cache_file": item.cache_file.name,
                    "sha256": item.sha256,
                }
                for item in images
            ],
        },
        "rendering": {
            "module": "brc_tools.satellite.modis",
            "module_sha256": _module_sha256(),
            "runtime_versions": _runtime_versions(),
            "requested_width_pixels": width,
            "requested_height_pixels": height,
            "resolved_width_pixels": images[0].width,
            "resolved_height_pixels": images[0].height,
            "dpi": dpi,
            "title": title,
            "markers": {
                name: {"lon": lon, "lat": lat}
                for name, (lon, lat) in markers.items()
            },
            "outputs": dict(outputs),
        },
        "interpretation": {
            "true_color": "snow and cloud can both appear white",
            "bands_7_2_1": (
                "snow and ice usually appear cyan; most liquid cloud appears white; "
                "ice cloud can also appear cyan"
            ),
        },
        "source_documentation": [
            "https://nasa-gibs.github.io/gibs-api-docs/python-usage/",
            "https://cmr.earthdata.nasa.gov/search/site/docs/search/api.html",
            (
                "https://doi.org/10.5067/MODIS/MOD02HKM.061"
                if selected.platform == "Terra"
                else "https://doi.org/10.5067/MODIS/MYD02HKM.061"
            ),
        ],
    }
    path = output_stem.with_suffix(".provenance.json")
    _atomic_write(path, (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode())
    return path


def render_context(
    target: datetime,
    bbox: Sequence[float],
    output_stem: Path | str,
    *,
    products: Sequence[str] = ("true-color", "snow-false-color"),
    platform: str = "auto",
    search_hours: float = 12.0,
    width: int = 1600,
    height: int | None = None,
    formats: Sequence[str] = ("png", "pdf"),
    markers: Mapping[str, tuple[float, float]] | None = None,
    title: str | None = None,
    dpi: int = 300,
    cache_dir: Path | str | None = None,
    offline: bool = False,
    refresh: bool = False,
    session: requests.Session | None = None,
    timeout: float = 60.0,
) -> RenderResult:
    """Discover, fetch, render, and provenance a MODIS context figure."""

    if not products:
        raise ValueError("products cannot be empty")
    if len(set(products)) != len(products):
        raise ValueError("products cannot contain duplicates")
    if dpi <= 0:
        raise ValueError("dpi must be positive")
    stem = Path(output_stem).expanduser()
    if stem.suffix.lower() in (".png", ".pdf"):
        stem = stem.with_suffix("")

    discovery = discover_granules(
        target,
        bbox,
        platform=platform,
        search_hours=search_hours,
        cache_dir=cache_dir,
        offline=offline,
        refresh=refresh,
        session=session,
        timeout=timeout,
    )
    images = tuple(
        fetch_gibs_image(
            discovery.selected,
            discovery.bbox,
            product,
            width=width,
            height=height,
            cache_dir=cache_dir,
            offline=offline,
            refresh=refresh,
            session=session,
            timeout=timeout,
        )
        for product in products
    )
    outputs = _render_figure(
        discovery,
        images,
        stem,
        formats=formats,
        markers=markers or {},
        title=title,
        dpi=dpi,
    )
    provenance = _write_provenance(
        discovery,
        images,
        outputs,
        stem,
        width=width,
        height=height,
        dpi=dpi,
        markers=markers or {},
        title=title,
    )
    return RenderResult(
        discovery=discovery,
        images=images,
        outputs=outputs,
        provenance_path=provenance,
    )


def _parse_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _parse_marker(value: str) -> tuple[str, tuple[float, float]]:
    try:
        name, lon, lat = (item.strip() for item in value.split(",", 2))
        return name, (float(lon), float(lat))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("marker must be NAME,LON,LAT") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Render host-neutral MODIS context imagery using NASA CMR timing and "
            "NASA GIBS corrected-reflectance maps."
        )
    )
    parser.add_argument("--target", required=True, help="UTC ISO timestamp, e.g. 2013-02-02T18:00:00Z")
    parser.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        required=True,
        metavar=("WEST", "SOUTH", "EAST", "NORTH"),
    )
    parser.add_argument("--output", required=True, help="output stem (outside brc-tools checkout)")
    parser.add_argument(
        "--products",
        default="true-color,snow-false-color",
        help="comma-separated: true-color,snow-false-color",
    )
    parser.add_argument("--platform", default="auto", choices=("auto", "terra", "aqua"))
    parser.add_argument("--search-hours", type=float, default=12.0)
    parser.add_argument("--width", type=int, default=1600)
    parser.add_argument("--height", type=int)
    parser.add_argument("--formats", default="png,pdf", help="comma-separated: png,pdf")
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--cache-dir", help="default: $BRC_TOOLS_MODIS_CACHE or ~/.cache/brc-tools/modis")
    parser.add_argument("--offline", action="store_true", help="read only from an already staged cache")
    parser.add_argument("--refresh", action="store_true", help="replace matching CMR/GIBS cache entries")
    parser.add_argument("--marker", action="append", default=[], type=_parse_marker, metavar="NAME,LON,LAT")
    parser.add_argument("--title")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    products = _parse_csv(args.products)
    formats = _parse_csv(args.formats)
    markers = dict(args.marker)
    result = render_context(
        parse_utc(args.target),
        args.bbox,
        args.output,
        products=products,
        platform=args.platform,
        search_hours=args.search_hours,
        width=args.width,
        height=args.height,
        formats=formats,
        markers=markers,
        title=args.title,
        dpi=args.dpi,
        cache_dir=args.cache_dir,
        offline=args.offline,
        refresh=args.refresh,
    )
    selected = result.discovery.selected
    offset = selected.offset_seconds(result.discovery.target) / 60.0
    print(
        f"selected {selected.platform} {selected.producer_granule_id} "
        f"({selected.time_start:%H:%M}-{selected.time_end:%H:%M} UTC; "
        f"midpoint offset {offset:+.1f} min)"
    )
    for name, digest in result.outputs.items():
        print(f"wrote {Path(args.output).expanduser().parent / name} sha256={digest}")
    print(f"wrote {result.provenance_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

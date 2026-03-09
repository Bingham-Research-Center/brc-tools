"""Scrape and download images from web pages or UDOT traffic cameras.

General-purpose image scraper with first-class support for UDOT camera
feeds in the Uinta Basin. Saves images with UTC timestamps and maintains
a per-source manifest for tracking.

Usage:
    python -m brc_tools.download.scrape_images --source udot --dry-run
    python -m brc_tools.download.scrape_images --source udot --max-images 3
    python -m brc_tools.download.scrape_images --url https://example.com --dry-run
    python -m brc_tools.download.scrape_images --source udot --loop --interval 900
"""

import argparse
import json
import logging
import os
import re
import signal
import sys
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from brc_tools.utils.lookups import (
    UDOT_CAMERAS_API_URL,
    slugify_camera_name,
    udot_cameras,
)
from brc_tools.utils.util_funcs import get_current_datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff"}
DEFAULT_TIMEOUT = 30
MAX_RETRIES = 2
POLITE_DELAY = 0.1


# ---------------------------------------------------------------------------
# General web scraper
# ---------------------------------------------------------------------------

def discover_images_from_url(url, min_size=0):
    """Scrape a web page and return a list of absolute image URLs.

    Searches <img src>, <meta property="og:image">, and <source srcset>
    tags. Resolves relative URLs and filters by extension.

    Args:
        url: The web page URL to scrape.
        min_size: Ignored during discovery (applied at download time).

    Returns:
        list of str: Absolute image URLs found on the page.
    """
    resp = requests.get(url, timeout=DEFAULT_TIMEOUT)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    found = set()

    # <img src="...">
    for tag in soup.find_all("img"):
        src = tag.get("src")
        if src:
            found.add(urljoin(url, src))

    # <meta property="og:image" content="...">
    for tag in soup.find_all("meta", property="og:image"):
        content = tag.get("content")
        if content:
            found.add(urljoin(url, content))

    # <source srcset="...">
    for tag in soup.find_all("source"):
        srcset = tag.get("srcset", "")
        for part in srcset.split(","):
            src = part.strip().split()[0] if part.strip() else ""
            if src:
                found.add(urljoin(url, src))

    # Filter by image extension
    images = []
    for img_url in found:
        path = urlparse(img_url).path.lower()
        ext = os.path.splitext(path)[1]
        if ext in IMAGE_EXTENSIONS:
            images.append(img_url)

    log.info("Discovered %d images on %s", len(images), url)
    return sorted(images)


# ---------------------------------------------------------------------------
# UDOT camera fetcher
# ---------------------------------------------------------------------------

def fetch_udot_camera_images(camera_filter=None):
    """Fetch camera image URLs from the UDOT Traffic API.

    Cross-references API results with the ``udot_cameras`` list from
    lookups.py using slug matching to filter to Uinta Basin cameras only.

    Args:
        camera_filter: Optional list of camera slugs to include.
            If None, all cameras in ``udot_cameras`` are fetched.

    Returns:
        list of dict: Each dict has keys: name, slug, lat, lon, roadway,
            image_url, source_url.
    """
    api_key = os.environ.get("UDOT_API_KEY", "")
    if not api_key:
        log.error("UDOT_API_KEY env var is not set — cannot authenticate")
        raise RuntimeError("UDOT_API_KEY env var is required")

    try:
        resp = requests.get(
            UDOT_CAMERAS_API_URL,
            params={"key": api_key},
            timeout=DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
    except requests.exceptions.HTTPError as exc:
        if exc.response is not None and exc.response.status_code in (400, 401, 403):
            log.error(
                "UDOT API returned %d — check UDOT_API_KEY value",
                exc.response.status_code,
            )
        raise

    data = resp.json()

    # Build slug lookup from our known Uinta Basin cameras
    known_slugs = {}
    for cam in udot_cameras:
        slug = slugify_camera_name(cam["name"])
        known_slugs[slug] = cam

    # Parse API response — fields use PascalCase:
    # Id, Location, Latitude, Longitude, Roadway, Views[].Url
    api_cameras = []
    items = data if isinstance(data, list) else data.get("cameras", data.get("results", []))
    for cam in items:
        name = cam.get("Location", "")
        lat = cam.get("Latitude", 0.0)
        lon = cam.get("Longitude", 0.0)
        roadway = cam.get("Roadway", "")

        views = cam.get("Views", [])
        if not views or not isinstance(views, list):
            continue
        image_url = views[0].get("Url", "")
        if not image_url:
            continue

        slug = slugify_camera_name(name)

        # Filter to Uinta Basin: only keep cameras in our known list
        if slug not in known_slugs:
            continue

        if camera_filter and slug not in camera_filter:
            continue

        known = known_slugs[slug]
        api_cameras.append({
            "name": name,
            "slug": slug,
            "lat": known["lat"],
            "lon": known["lon"],
            "roadway": known["roadway"],
            "image_url": image_url,
            "source_url": UDOT_CAMERAS_API_URL,
        })

    log.info(
        "UDOT API: matched %d Uinta Basin cameras (from %d total in response)",
        len(api_cameras), len(items),
    )

    if not api_cameras:
        log.warning(
            "No cameras matched — check API response field names or udot_cameras list"
        )

    return api_cameras


# ---------------------------------------------------------------------------
# Download core
# ---------------------------------------------------------------------------

def download_image(url, dest_path, min_size=1024):
    """Download a single image with retry logic.

    Args:
        url: Image URL.
        dest_path: Local file path to save to.
        min_size: Minimum file size in bytes. Images smaller than this
            are deleted (likely error pages).

    Returns:
        int: File size in bytes, or 0 if download failed/too small.
    """
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)

    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(url, timeout=DEFAULT_TIMEOUT, stream=True)
            resp.raise_for_status()

            with open(dest_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)

            file_size = os.path.getsize(dest_path)
            if file_size < min_size:
                log.warning(
                    "Image too small (%d bytes < %d): %s",
                    file_size, min_size, url,
                )
                os.remove(dest_path)
                return 0

            return file_size

        except requests.exceptions.RequestException as exc:
            log.warning(
                "Download attempt %d/%d failed for %s: %s",
                attempt + 1, MAX_RETRIES, url, exc,
            )
            if attempt < MAX_RETRIES - 1:
                time.sleep(1)

    log.error("All download attempts failed for %s", url)
    return 0


# ---------------------------------------------------------------------------
# File naming and manifest
# ---------------------------------------------------------------------------

def build_image_path(data_dir, source, sub_id, ext=".jpg"):
    """Build the destination path for an image.

    Format: {data_dir}/{source}/{sub_id}/{YYYYMMDD_HHMMSS}Z.{ext}

    Args:
        data_dir: Root images directory.
        source: Source identifier (e.g., "udot" or sanitized domain).
        sub_id: Sub-identifier (camera slug or image index).
        ext: File extension including dot.

    Returns:
        str: Full file path.
    """
    now = get_current_datetime()
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}Z{ext}"
    return os.path.join(data_dir, source, sub_id, filename)


def _sanitize_domain(url):
    """Extract and sanitize the domain from a URL for use as a directory name."""
    domain = urlparse(url).netloc
    return re.sub(r"[^a-zA-Z0-9._-]", "_", domain)


def load_manifest(manifest_path):
    """Load existing manifest or return empty list."""
    if os.path.exists(manifest_path):
        with open(manifest_path) as f:
            return json.load(f)
    return []


def save_manifest(manifest_path, entries):
    """Save manifest entries to JSON."""
    os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
    with open(manifest_path, "w") as f:
        json.dump(entries, f, indent=2)


def update_manifest(manifest_path, new_entry):
    """Append an entry to the manifest file."""
    entries = load_manifest(manifest_path)
    entries.append(new_entry)
    save_manifest(manifest_path, entries)


# ---------------------------------------------------------------------------
# Run modes
# ---------------------------------------------------------------------------

def run_udot(args):
    """Fetch and download UDOT camera images."""
    camera_filter = None
    if args.cameras:
        camera_filter = set(args.cameras.split(","))

    cameras = fetch_udot_camera_images(camera_filter=camera_filter)

    if args.max_images and args.max_images > 0:
        cameras = cameras[: args.max_images]

    if not cameras:
        log.warning("No cameras to download")
        return

    manifest_path = os.path.join(args.data_dir, "udot", "manifest.json")
    downloaded = 0
    now = get_current_datetime()

    for cam in cameras:
        image_url = cam["image_url"]
        ext = os.path.splitext(urlparse(image_url).path)[1] or ".png"
        dest = build_image_path(args.data_dir, "udot", cam["slug"], ext)

        if args.dry_run:
            log.info("[DRY RUN] Would download: %s -> %s", image_url, dest)
            continue

        log.info("Downloading %s -> %s", cam["name"], dest)
        file_size = download_image(image_url, dest, min_size=args.min_size)

        if file_size > 0:
            entry = {
                "camera_name": cam["name"],
                "slug": cam["slug"],
                "lat": cam["lat"],
                "lon": cam["lon"],
                "roadway": cam["roadway"],
                "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "filepath": dest,
                "source_url": image_url,
                "file_size": file_size,
            }
            update_manifest(manifest_path, entry)
            downloaded += 1

        time.sleep(POLITE_DELAY)

    log.info(
        "UDOT complete: %d/%d images downloaded", downloaded, len(cameras),
    )


def run_url(args):
    """Scrape and download images from a generic URL."""
    images = discover_images_from_url(args.url, min_size=args.min_size)

    if args.max_images and args.max_images > 0:
        images = images[: args.max_images]

    if not images:
        log.warning("No images found at %s", args.url)
        return

    source = _sanitize_domain(args.url)
    manifest_path = os.path.join(args.data_dir, source, "manifest.json")
    downloaded = 0
    now = get_current_datetime()

    for idx, image_url in enumerate(images):
        ext = os.path.splitext(urlparse(image_url).path)[1] or ".jpg"
        sub_id = f"image_{idx:04d}"
        dest = build_image_path(args.data_dir, source, sub_id, ext)

        if args.dry_run:
            log.info("[DRY RUN] Would download: %s -> %s", image_url, dest)
            continue

        log.info("Downloading image %d/%d -> %s", idx + 1, len(images), dest)
        file_size = download_image(image_url, dest, min_size=args.min_size)

        if file_size > 0:
            entry = {
                "image_index": idx,
                "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "filepath": dest,
                "source_url": image_url,
                "file_size": file_size,
            }
            update_manifest(manifest_path, entry)
            downloaded += 1

        time.sleep(POLITE_DELAY)

    log.info("URL scrape complete: %d/%d images downloaded", downloaded, len(images))


# ---------------------------------------------------------------------------
# Signal handling for loop mode
# ---------------------------------------------------------------------------

_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    log.info("Received signal %d — shutting down after current cycle", signum)
    _shutdown = True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Scrape and download images from web pages or UDOT cameras",
    )

    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--source",
        choices=["udot"],
        help="Built-in source to fetch from",
    )
    source_group.add_argument(
        "--url",
        type=str,
        help="URL of a web page to scrape for images",
    )

    parser.add_argument(
        "--data-dir",
        default=os.path.join("data", "images"),
        help="Root directory for saved images (default: data/images)",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run repeatedly on an interval (for local dev/testing)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=900,
        help="Seconds between runs in loop mode (default: 900)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover images but do not download",
    )
    parser.add_argument(
        "--max-images",
        type=int,
        default=0,
        help="Maximum number of images to download (0 = unlimited)",
    )
    parser.add_argument(
        "--min-size",
        type=int,
        default=20000,
        help="Minimum image file size in bytes (default: 20000)",
    )
    parser.add_argument(
        "--cameras",
        type=str,
        default="",
        help="Comma-separated camera slugs to filter (UDOT only)",
    )

    args = parser.parse_args()

    # Resolve data dir to absolute path
    args.data_dir = os.path.abspath(args.data_dir)
    os.makedirs(args.data_dir, exist_ok=True)

    # Pick the runner
    if args.source == "udot":
        runner = run_udot
    else:
        runner = run_url

    if args.loop:
        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)
        log.info("Loop mode: running every %d seconds (Ctrl+C to stop)", args.interval)

        while not _shutdown:
            try:
                runner(args)
            except Exception:
                log.exception("Error during run cycle")
            if _shutdown:
                break
            log.info("Sleeping %d seconds...", args.interval)
            # Sleep in small increments to respond to signals quickly
            for _ in range(args.interval):
                if _shutdown:
                    break
                time.sleep(1)

        log.info("Shutdown complete")
    else:
        runner(args)


if __name__ == "__main__":
    main()

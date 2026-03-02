"""Fetch HRRR road forecasts and push JSON to BasinWX.

Extracts temperature, wind, visibility, precipitation type, and other
surface variables at road waypoints along US-40, US-191, and local
basin roads for the next 12 hours.

Usage:
    python -m brc_tools.download.get_road_forecast
    python -m brc_tools.download.get_road_forecast --dry-run
"""

import argparse
import datetime
import json
import logging
import math
import os

import numpy as np
import xarray as xr
from herbie import Herbie

from brc_tools.utils.lookups import road_corridors, udot_cameras
from brc_tools.download.download_funcs import generate_json_fpath
from brc_tools.download.push_data import send_json_to_server, load_config
from brc_tools.utils.util_funcs import get_current_datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# HRRR GRIB2 search strings mapped to output variable names.
# Names starting with "_" are intermediate (used in derivations, not output).
HRRR_VARS = {
    "TMP:2 m":         "temp_2m",
    "UGRD:10 m":       "_ugrd",
    "VGRD:10 m":       "_vgrd",
    "GUST:surface":    "wind_gust",
    "VIS:surface":     "visibility",
    "APCP:surface":    "precip_1hr",
    "CRAIN:surface":   "_crain",
    "CSNOW:surface":   "_csnow",
    "CFRZR:surface":   "_cfrzr",
    "CICEP:surface":   "_cicep",
    "SNOD:surface":    "snow_depth",
    "TCDC:entire":     "cloud_cover",
    "RH:2 m":          "rh_2m",
}

MAX_FXX = 12
MIN_USABLE_HOURS = 6


# ---------------------------------------------------------------------------
# HRRR fetch helpers
# ---------------------------------------------------------------------------

def get_latest_hrrr_init():
    """Find the most recent available HRRR initialization time.

    HRRR data typically appears ~45 minutes after init, so we start
    looking 2 hours back from the current UTC hour and step backwards.

    Returns:
        datetime.datetime: The init time of the latest available run.

    Raises:
        RuntimeError: If no HRRR run is found in the last 6 hours.
    """
    now = datetime.datetime.now(datetime.timezone.utc).replace(
        minute=0, second=0, microsecond=0
    )
    start_hour = now - datetime.timedelta(hours=2)

    for hours_back in range(6):
        candidate = start_hour - datetime.timedelta(hours=hours_back)
        try:
            Herbie(
                date=candidate,
                model="hrrr",
                product="sfc",
                fxx=1,
            )
            log.info("Found HRRR init: %s", candidate.strftime("%Y-%m-%d %HZ"))
            return candidate
        except Exception:
            log.debug("No HRRR at %s, stepping back", candidate.strftime("%HZ"))
            continue

    raise RuntimeError("No HRRR run found in the last 6 hours")


def fetch_forecast_hour(init_time, fxx):
    """Download one forecast hour and return a merged xarray Dataset.

    Args:
        init_time: HRRR initialization datetime.
        fxx: Forecast hour (1-12).

    Returns:
        xarray.Dataset with all requested variables on the HRRR grid.
    """
    h = Herbie(date=init_time, model="hrrr", product="sfc", fxx=fxx)

    datasets = []
    for search_str in HRRR_VARS:
        try:
            ds = h.xarray(search_str, remove_grib=True)
            datasets.append(ds)
        except Exception as exc:
            log.warning("Could not load %r for fxx=%d: %s", search_str, fxx, exc)

    if not datasets:
        raise ValueError(f"No variables loaded for fxx={fxx}")

    merged = xr.merge(datasets)

    # Fix longitude from 0-360 to -180..180 if needed
    if "longitude" in merged.coords and float(merged.longitude.max()) > 180.0:
        merged["longitude"] = merged.longitude - 360.0

    return merged


# ---------------------------------------------------------------------------
# Point extraction
# ---------------------------------------------------------------------------

def _find_nearest_indices(ds, lat, lon):
    """Return (y_idx, x_idx) of the nearest grid point to (lat, lon)."""
    lats = ds.latitude.values
    lons = ds.longitude.values

    # Handle 0-360 longitudes that weren't already fixed
    if np.max(lons) > 180.0:
        lons = lons - 360.0

    dist = (lats - lat) ** 2 + (lons - lon) ** 2
    y_idx, x_idx = np.unravel_index(dist.argmin(), dist.shape)
    return int(y_idx), int(x_idx)


def _deduplicate_cameras(ds, cameras):
    """Group cameras by their nearest HRRR grid cell.

    Many cameras in the same town map to the same 3-km grid cell.
    We find indices once per camera, then group by (y_idx, x_idx)
    so extraction only happens once per unique cell.

    Returns:
        dict mapping (y_idx, x_idx) -> list of camera dicts (with
        ``_y_idx`` and ``_x_idx`` keys added).
    """
    from collections import defaultdict

    grid_groups = defaultdict(list)
    for cam in cameras:
        y_idx, x_idx = _find_nearest_indices(ds, cam["lat"], cam["lon"])
        enriched = {**cam, "_y_idx": y_idx, "_x_idx": x_idx}
        grid_groups[(y_idx, x_idx)].append(enriched)
    return dict(grid_groups)


def extract_at_waypoint(ds, lat, lon):
    """Extract all variable values at the nearest grid point.

    Args:
        ds: Merged xarray Dataset for one forecast hour.
        lat: Waypoint latitude.
        lon: Waypoint longitude.

    Returns:
        dict mapping GRIB short names to float values.
    """
    y_idx, x_idx = _find_nearest_indices(ds, lat, lon)

    raw = {}
    for var_name in ds.data_vars:
        arr = ds[var_name]
        if arr.dims == () or len(arr.dims) < 2:
            continue
        val = float(arr.isel(y=y_idx, x=x_idx).values)
        raw[var_name] = val

    return raw


# ---------------------------------------------------------------------------
# Derived fields and unit conversions
# ---------------------------------------------------------------------------

# Map from xarray data-variable short names to our HRRR_VARS keys.
# Herbie names variables like "t2m", "u10", "gust", etc. — this lookup
# lets derive_fields work regardless of the exact GRIB short name.
_GRIB_TO_KEY = {
    "t2m": "temp_2m",
    "u10": "_ugrd",
    "v10": "_vgrd",
    "gust": "wind_gust",
    "vis": "visibility",
    "tp": "precip_1hr",
    "crain": "_crain",
    "csnow": "_csnow",
    "cfrzr": "_cfrzr",
    "cicep": "_cicep",
    "sde": "snow_depth",
    "tcc": "cloud_cover",
    "r2": "rh_2m",
    # Fallback aliases seen in some HRRR products
    "unknown": None,
}


def _normalize_raw(raw):
    """Map xarray short-name keys to our canonical HRRR_VARS names."""
    out = {}
    for grib_name, value in raw.items():
        canonical = _GRIB_TO_KEY.get(grib_name)
        if canonical is None:
            # Try matching by checking if the grib_name is already canonical
            if grib_name in {v for v in HRRR_VARS.values()}:
                canonical = grib_name
            else:
                continue
        out[canonical] = value
    return out


def derive_fields(raw):
    """Apply unit conversions and compute derived variables.

    Args:
        raw: dict of raw variable values extracted from xarray.

    Returns:
        dict with the 9 output variables (see JSON schema).
    """
    r = _normalize_raw(raw)

    out = {}

    # Temperature: K -> C
    if "temp_2m" in r:
        out["temp_2m"] = round(r["temp_2m"] - 273.15, 1)

    # Wind speed from u/v components: m/s
    ugrd = r.get("_ugrd", 0.0)
    vgrd = r.get("_vgrd", 0.0)
    out["wind_speed_10m"] = round(math.sqrt(ugrd**2 + vgrd**2), 1)

    # Wind gust: already m/s
    if "wind_gust" in r:
        out["wind_gust"] = round(r["wind_gust"], 1)

    # Visibility: m -> km
    if "visibility" in r:
        out["visibility"] = round(r["visibility"] / 1000.0, 1)

    # 1-hr accumulated precipitation: kg/m^2 = mm
    if "precip_1hr" in r:
        out["precip_1hr"] = round(r["precip_1hr"], 1)

    # Precip type from categorical flags
    csnow = r.get("_csnow", 0)
    crain = r.get("_crain", 0)
    cfrzr = r.get("_cfrzr", 0)
    cicep = r.get("_cicep", 0)
    flags = sum(1 for f in (csnow, crain, cfrzr, cicep) if f >= 0.5)
    if flags > 1:
        out["precip_type"] = "mixed"
    elif csnow >= 0.5:
        out["precip_type"] = "snow"
    elif crain >= 0.5:
        out["precip_type"] = "rain"
    elif cfrzr >= 0.5:
        out["precip_type"] = "freezing_rain"
    elif cicep >= 0.5:
        out["precip_type"] = "ice_pellets"
    else:
        out["precip_type"] = "none"

    # Snow depth: m -> mm
    if "snow_depth" in r:
        out["snow_depth"] = round(r["snow_depth"] * 1000.0, 1)

    # Cloud cover: already %
    if "cloud_cover" in r:
        out["cloud_cover"] = round(r["cloud_cover"], 1)

    # Relative humidity: already %
    if "rh_2m" in r:
        out["rh_2m"] = round(r["rh_2m"], 1)

    return out


# ---------------------------------------------------------------------------
# JSON builder
# ---------------------------------------------------------------------------

def build_json(init_time, forecasts_by_route, *,
               camera_grid_groups=None, camera_cell_forecasts=None):
    """Assemble the output JSON structure.

    Args:
        init_time: HRRR init datetime.
        forecasts_by_route: dict of {route_id: {wp_index: [derive_fields output per fxx]}}
        camera_grid_groups: optional dict (y,x) -> [camera dicts] from _deduplicate_cameras.
        camera_cell_forecasts: optional dict (y,x) -> [derived per fxx].

    Returns:
        dict ready for json.dump.
    """
    forecast_hours = list(range(1, MAX_FXX + 1))
    valid_times = [
        (init_time + datetime.timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")
        for h in forecast_hours
    ]

    variables_meta = {
        "temp_2m":        {"units": "Celsius", "display": "Temperature"},
        "wind_speed_10m": {"units": "m/s",     "display": "Wind Speed"},
        "wind_gust":      {"units": "m/s",     "display": "Wind Gust"},
        "visibility":     {"units": "km",      "display": "Visibility"},
        "precip_1hr":     {"units": "mm",      "display": "1-hr Precip"},
        "precip_type":    {"units": "category", "display": "Precip Type"},
        "snow_depth":     {"units": "mm",      "display": "Snow Depth"},
        "cloud_cover":    {"units": "%",       "display": "Cloud Cover"},
        "rh_2m":          {"units": "%",       "display": "Relative Humidity"},
    }

    routes = {}
    for route_id, corridor in road_corridors.items():
        wp_forecasts = forecasts_by_route.get(route_id, {})
        waypoints_out = []
        for wp_idx, wp in enumerate(corridor["waypoints"]):
            hour_data = wp_forecasts.get(wp_idx, [])

            # Transpose: list-of-dicts-per-hour -> dict-of-lists-per-variable
            var_arrays = {}
            for var_key in variables_meta:
                var_arrays[var_key] = [
                    h.get(var_key) for h in hour_data
                ]

            waypoints_out.append({
                "name": wp["name"],
                "lat": wp["lat"],
                "lon": wp["lon"],
                "elevation_m": wp["elevation_m"],
                "reference_stid": wp["reference_stid"],
                "forecasts": var_arrays,
            })

        routes[route_id] = {
            "name": corridor["name"],
            "waypoints": waypoints_out,
        }

    # Build flat cameras list (one entry per camera, sharing forecasts
    # with other cameras at the same HRRR grid cell).
    cameras_out = []
    if camera_grid_groups and camera_cell_forecasts:
        for cell_key, cam_list in camera_grid_groups.items():
            hour_data = camera_cell_forecasts.get(cell_key, [])
            var_arrays = {}
            for var_key in variables_meta:
                var_arrays[var_key] = [h.get(var_key) for h in hour_data]
            for cam in cam_list:
                cameras_out.append({
                    "name": cam["name"],
                    "roadway": cam["roadway"],
                    "lat": cam["lat"],
                    "lon": cam["lon"],
                    "forecasts": var_arrays,
                })

    result = {
        "model": "hrrr",
        "init_time": init_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_at": get_current_datetime().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "forecast_hours": forecast_hours,
        "valid_times": valid_times,
        "variables": variables_meta,
        "routes": routes,
        "cameras": cameras_out,
    }
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Fetch HRRR road forecasts for Uinta Basin corridors"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and print JSON but do not push to server",
    )
    args = parser.parse_args()

    data_root = os.path.expanduser("~/gits/brc-tools/data")
    os.makedirs(data_root, exist_ok=True)

    # 1. Find latest HRRR init
    init_time = get_latest_hrrr_init()

    # 2. Fetch each forecast hour
    hour_datasets = {}
    for fxx in range(1, MAX_FXX + 1):
        try:
            ds = fetch_forecast_hour(init_time, fxx)
            hour_datasets[fxx] = ds
            log.info("Fetched fxx=%d (%d variables)", fxx, len(ds.data_vars))
        except Exception as exc:
            log.warning("Failed to fetch fxx=%d: %s", fxx, exc)

    if len(hour_datasets) < MIN_USABLE_HOURS:
        log.error(
            "Only %d/%d forecast hours available — aborting",
            len(hour_datasets), MAX_FXX,
        )
        return

    # 3. Extract at each waypoint for each route
    forecasts_by_route = {}
    total_waypoints = 0
    for route_id, corridor in road_corridors.items():
        wp_forecasts = {}
        for wp_idx, wp in enumerate(corridor["waypoints"]):
            hour_values = []
            for fxx in range(1, MAX_FXX + 1):
                if fxx in hour_datasets:
                    raw = extract_at_waypoint(
                        hour_datasets[fxx], wp["lat"], wp["lon"]
                    )
                    derived = derive_fields(raw)
                else:
                    derived = {}
                hour_values.append(derived)
            wp_forecasts[wp_idx] = hour_values
            total_waypoints += 1
        forecasts_by_route[route_id] = wp_forecasts

    log.info("Extracted forecasts for %d waypoints across %d routes",
             total_waypoints, len(road_corridors))

    # 3b. Extract at UDOT camera locations (deduplicated by grid cell)
    first_ds = next(iter(hour_datasets.values()))
    camera_grid_groups = _deduplicate_cameras(first_ds, udot_cameras)
    log.info(
        "Deduplicated %d cameras into %d unique HRRR grid cells",
        len(udot_cameras), len(camera_grid_groups),
    )

    camera_cell_forecasts = {}
    for (y_idx, x_idx) in camera_grid_groups:
        hour_values = []
        for fxx in range(1, MAX_FXX + 1):
            if fxx in hour_datasets:
                ds = hour_datasets[fxx]
                raw = {}
                for var_name in ds.data_vars:
                    arr = ds[var_name]
                    if arr.dims == () or len(arr.dims) < 2:
                        continue
                    raw[var_name] = float(arr.isel(y=y_idx, x=x_idx).values)
                derived = derive_fields(raw)
            else:
                derived = {}
            hour_values.append(derived)
        camera_cell_forecasts[(y_idx, x_idx)] = hour_values

    # 4. Build JSON
    output = build_json(
        init_time, forecasts_by_route,
        camera_grid_groups=camera_grid_groups,
        camera_cell_forecasts=camera_cell_forecasts,
    )

    # 5. Save to file
    fpath = generate_json_fpath(
        data_root, prefix="road_forecast", t=get_current_datetime()
    )
    with open(fpath, "w") as f:
        json.dump(output, f, indent=2)
    file_size_kb = os.path.getsize(fpath) / 1024
    log.info("Saved %s (%.1f KB)", fpath, file_size_kb)

    if args.dry_run:
        log.info("Dry run — printing JSON to stdout")
        print(json.dumps(output, indent=2))
        return

    # 6. Push to server
    try:
        API_KEY, server_url = load_config()
        log.info("Pushing to %s...", server_url[:20])
        send_json_to_server(server_url, fpath, "road-forecast", API_KEY)
    except Exception as exc:
        log.error("Failed to push to server: %s", exc)


if __name__ == "__main__":
    main()

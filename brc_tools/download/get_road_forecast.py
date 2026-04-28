"""Build a minimal hourly HRRR road forecast proof-of-concept."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import math
import os
from pathlib import Path

import numpy as np

from brc_tools.download.hrrr_access import (
    extract_nearest_values,
    fetch_hourly_datasets,
    get_latest_hrrr_init,
)
from brc_tools.download.hrrr_config import (
    DEFAULT_HRRR_PRODUCT,
    DEFAULT_MAX_FXX,
    DEFAULT_MIN_USABLE_HOURS,
    ROAD_CORRIDORS,
    ROAD_FORECAST_QUERY_MAP,
    ROAD_FORECAST_VARIABLES_META,
)
from brc_tools.utils.util_funcs import get_current_datetime

LOG = logging.getLogger(__name__)


def derive_road_fields(raw: dict[str, float]) -> dict[str, float | str | None]:
    """Convert raw HRRR fields into the road forecast schema."""
    out: dict[str, float | str | None] = {
        key: None for key in ROAD_FORECAST_VARIABLES_META
    }

    if _isfinite(raw.get("temp_2m")):
        out["temp_2m"] = _round(raw["temp_2m"] - 273.15)

    ugrd = raw.get("_ugrd")
    vgrd = raw.get("_vgrd")
    if _isfinite(ugrd) and _isfinite(vgrd):
        out["wind_speed_10m"] = _round(math.hypot(ugrd, vgrd))

    if _isfinite(raw.get("wind_gust")):
        out["wind_gust"] = _round(raw["wind_gust"])

    if _isfinite(raw.get("visibility")):
        out["visibility"] = _round(raw["visibility"] / 1000.0)

    if _isfinite(raw.get("precip_1hr")):
        out["precip_1hr"] = _round(raw["precip_1hr"])

    precip_type = _derive_precip_type(raw)
    if precip_type is not None:
        out["precip_type"] = precip_type

    if _isfinite(raw.get("snow_depth")):
        out["snow_depth"] = _round(raw["snow_depth"] * 1000.0)

    if _isfinite(raw.get("cloud_cover")):
        out["cloud_cover"] = _round(raw["cloud_cover"])

    if _isfinite(raw.get("rh_2m")):
        out["rh_2m"] = _round(raw["rh_2m"])

    return out


def build_road_payload(
    *,
    init_time: dt.datetime,
    max_fxx: int,
    forecasts_by_route: dict[str, dict[int, list[dict[str, float | str | None]]]],
) -> dict[str, object]:
    """Build a stable JSON payload for the road forecast proof-of-concept."""
    forecast_hours = list(range(1, max_fxx + 1))
    valid_times = [
        (init_time + dt.timedelta(hours=hour)).strftime("%Y-%m-%dT%H:%M:%SZ")
        for hour in forecast_hours
    ]

    routes_out: dict[str, dict[str, object]] = {}
    points_out: list[dict[str, object]] = []
    for route_id, corridor in ROAD_CORRIDORS.items():
        route_forecasts = forecasts_by_route.get(route_id, {})
        waypoints_out = []

        for waypoint_index, waypoint in enumerate(corridor["waypoints"]):
            hourly_values = route_forecasts.get(
                waypoint_index,
                [derive_road_fields({}) for _ in forecast_hours],
            )
            forecast_arrays = {
                variable: [hour.get(variable) for hour in hourly_values]
                for variable in ROAD_FORECAST_VARIABLES_META
            }
            waypoints_out.append(
                {
                    "name": waypoint["name"],
                    "lat": waypoint["lat"],
                    "lon": waypoint["lon"],
                    "elevation_m": waypoint["elevation_m"],
                    "reference_stid": waypoint["reference_stid"],
                    "forecasts": forecast_arrays,
                }
            )
            points_out.append(
                {
                    "route_id": route_id,
                    "name": waypoint["name"],
                    "lat": waypoint["lat"],
                    "lon": waypoint["lon"],
                    "elevation_m": waypoint["elevation_m"],
                    "reference_stid": waypoint["reference_stid"],
                    "forecasts": [
                        {"valid_time": valid_time, **hour}
                        for valid_time, hour in zip(valid_times, hourly_values)
                    ],
                }
            )

        routes_out[route_id] = {
            "name": corridor["name"],
            "waypoints": waypoints_out,
        }

    return {
        "model": "hrrr",
        "product": DEFAULT_HRRR_PRODUCT,
        "init_time": init_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_at": get_current_datetime().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "forecast_hours": forecast_hours,
        "valid_times": valid_times,
        "variables": ROAD_FORECAST_VARIABLES_META,
        "routes": routes_out,
        "points": points_out,
        "cameras": [],
    }


def build_route_forecasts(
    *,
    hour_datasets: dict[int, object],
    max_fxx: int,
) -> dict[str, dict[int, list[dict[str, float | str | None]]]]:
    """Extract derived road forecast fields for each configured waypoint."""
    query_aliases = list(ROAD_FORECAST_QUERY_MAP)
    forecasts_by_route: dict[str, dict[int, list[dict[str, float | str | None]]]] = {}

    for route_id, corridor in ROAD_CORRIDORS.items():
        waypoint_forecasts: dict[int, list[dict[str, float | str | None]]] = {}
        for waypoint_index, waypoint in enumerate(corridor["waypoints"]):
            hourly_values = []
            for hour in range(1, max_fxx + 1):
                ds = hour_datasets.get(hour)
                if ds is None:
                    hourly_values.append(derive_road_fields({}))
                    continue
                raw = extract_nearest_values(
                    ds,
                    waypoint["lat"],
                    waypoint["lon"],
                    aliases=query_aliases,
                )
                hourly_values.append(derive_road_fields(raw))
            waypoint_forecasts[waypoint_index] = hourly_values
        forecasts_by_route[route_id] = waypoint_forecasts

    return forecasts_by_route


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build an hourly HRRR road forecast proof-of-concept"
    )
    parser.add_argument(
        "--init-time",
        help="Optional HRRR initialization time in YYYYMMDDHH format",
    )
    parser.add_argument(
        "--product",
        default=DEFAULT_HRRR_PRODUCT,
        help=f"HRRR product to use (default: {DEFAULT_HRRR_PRODUCT})",
    )
    parser.add_argument(
        "--max-fxx",
        type=int,
        default=DEFAULT_MAX_FXX,
        help=f"Maximum forecast hour to fetch (default: {DEFAULT_MAX_FXX})",
    )
    parser.add_argument(
        "--min-usable-hours",
        type=int,
        default=DEFAULT_MIN_USABLE_HOURS,
        help=(
            "Minimum successfully fetched forecast hours required before "
            "writing output"
        ),
    )
    parser.add_argument(
        "--data-dir",
        default=os.path.expanduser("~/gits/brc-tools/data"),
        help="Directory for output JSON files",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Write output locally but never upload it",
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Upload JSON after writing it locally",
    )
    parser.add_argument(
        "--upload-bucket",
        default="road-forecast",
        help="Upload bucket name passed to the shared uploader",
    )
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    args = parse_args()
    data_root = Path(args.data_dir).expanduser()
    data_root.mkdir(parents=True, exist_ok=True)

    try:
        init_time = _parse_or_find_init(args.init_time, product=args.product)
        hour_datasets = fetch_hourly_datasets(
            init_time,
            ROAD_FORECAST_QUERY_MAP,
            max_fxx=args.max_fxx,
            product=args.product,
        )
        if len(hour_datasets) < args.min_usable_hours:
            raise RuntimeError(
                "Only "
                f"{len(hour_datasets)}/{args.max_fxx} forecast hours available; "
                f"need at least {args.min_usable_hours}"
            )

        forecasts_by_route = build_route_forecasts(
            hour_datasets=hour_datasets,
            max_fxx=args.max_fxx,
        )
        payload = build_road_payload(
            init_time=init_time,
            max_fxx=args.max_fxx,
            forecasts_by_route=forecasts_by_route,
        )
    except Exception as exc:
        LOG.error("Road forecast build failed: %s", exc)
        return 1

    output_path = _build_output_path(data_root, prefix="road_forecast")
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, allow_nan=False)
    LOG.info("Wrote road forecast JSON to %s", output_path)

    if args.upload and not args.dry_run:
        try:
            from brc_tools.download.push_data import load_config_urls, send_json_to_all

            api_key, server_urls = load_config_urls()
            send_json_to_all(server_urls, output_path, args.upload_bucket, api_key)
        except Exception as exc:
            LOG.error("Road forecast upload failed: %s", exc)
            return 1
    else:
        LOG.info("Upload skipped")

    return 0


def _parse_or_find_init(init_time: str | None, *, product: str) -> dt.datetime:
    if init_time:
        return dt.datetime.strptime(init_time, "%Y%m%d%H")
    return get_latest_hrrr_init(product=product)


def _derive_precip_type(raw: dict[str, float]) -> str | None:
    flag_values = {
        "snow": raw.get("_csnow"),
        "rain": raw.get("_crain"),
        "freezing_rain": raw.get("_cfrzr"),
        "ice_pellets": raw.get("_cicep"),
    }

    available = {
        name: value for name, value in flag_values.items() if _isfinite(value)
    }
    if not available:
        return None

    active = [name for name, value in available.items() if value >= 0.5]
    if len(active) > 1:
        return "mixed"
    if len(active) == 1:
        return active[0]
    return "none"


def _isfinite(value: float | None) -> bool:
    return value is not None and bool(np.isfinite(value))


def _round(value: float) -> float | None:
    return round(float(value), 1) if np.isfinite(value) else None


def _build_output_path(data_root: Path, *, prefix: str) -> str:
    timestamp = get_current_datetime().strftime("%Y%m%d_%H%M")
    return str(data_root / f"{prefix}_{timestamp}Z.json")


if __name__ == "__main__":
    raise SystemExit(main())

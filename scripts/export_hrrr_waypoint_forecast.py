"""Export HRRR waypoint-forecast JSON for the BasinWX website."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
from pathlib import Path

from brc_tools.nwp import NWPSource
from brc_tools.nwp.waypoint_forecast import (
    DEFAULT_FORECAST_HOURS,
    DEFAULT_REGION,
    build_waypoint_payload,
    fetch_waypoint_dataset,
)

LOG = logging.getLogger(__name__)

DEFAULT_GROUP = "us40_dense"
DEFAULT_UPLOAD_BUCKET = "forecasts"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[1] / "data" / "basinwx"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export HRRR waypoint forecast JSON for BasinWX",
    )
    parser.add_argument(
        "--group",
        default=DEFAULT_GROUP,
        help=f"Waypoint group from lookups.toml (default: {DEFAULT_GROUP})",
    )
    parser.add_argument(
        "--region",
        default=DEFAULT_REGION,
        help=f"Fetch bounding-box region (default: {DEFAULT_REGION})",
    )
    parser.add_argument(
        "--max-fxx",
        type=int,
        default=max(DEFAULT_FORECAST_HOURS),
        help=f"Maximum forecast hour (default: {max(DEFAULT_FORECAST_HOURS)})",
    )
    parser.add_argument(
        "--init-time",
        default=None,
        help="Optional HRRR init time (YYYY-MM-DD HH); defaults to latest available",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Upload the JSON to BasinWX after writing",
    )
    parser.add_argument(
        "--upload-bucket",
        default=DEFAULT_UPLOAD_BUCKET,
        help=f"Upload bucket (default: {DEFAULT_UPLOAD_BUCKET})",
    )
    parser.add_argument(
        "--server-url",
        default=None,
        help="Override server URL (default: read from ~/.config/ubair-website/website_urls or BASINWX_API_URLS)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Write JSON locally but never upload",
    )
    return parser.parse_args()


def _resolve_init_time(arg: str | None, source: NWPSource) -> dt.datetime:
    if arg:
        return dt.datetime.strptime(arg, "%Y-%m-%d %H")
    return source.latest_init()


def _output_path(output_dir: Path, init_time: dt.datetime, group: str) -> Path:
    stamp = init_time.strftime("%Y%m%d_%H%M")
    return output_dir / f"forecast_hrrr_waypoints_{group}_{stamp}Z.json"


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    args = parse_args()

    output_dir = Path(args.output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        src = NWPSource("hrrr")
        init_time = _resolve_init_time(args.init_time, src)
        forecast_hours = list(range(0, args.max_fxx + 1))

        LOG.info(
            "Fetching HRRR waypoint forecast: init=%s group=%s fxx=0..%d",
            init_time.strftime("%Y-%m-%d %HZ"),
            args.group,
            args.max_fxx,
        )
        ds = fetch_waypoint_dataset(
            init_time=init_time,
            forecast_hours=forecast_hours,
            region=args.region,
            source=src,
        )
        payload = build_waypoint_payload(
            ds,
            group=args.group,
            init_time=init_time,
            forecast_hours=forecast_hours,
            region=args.region,
        )
    except Exception as exc:
        LOG.error("HRRR waypoint forecast build failed: %s", exc)
        return 1

    output_path = _output_path(output_dir, init_time, args.group)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, allow_nan=False)
    LOG.info("Wrote %s", output_path)

    if args.upload and not args.dry_run:
        try:
            from brc_tools.download.push_data import load_config_urls, send_json_to_all

            api_key, config_urls = load_config_urls()
            urls = [args.server_url] if args.server_url else config_urls
            send_json_to_all(urls, str(output_path), args.upload_bucket, api_key)
        except Exception as exc:
            LOG.error("HRRR waypoint forecast upload failed: %s", exc)
            return 1
    else:
        LOG.info("Upload skipped")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

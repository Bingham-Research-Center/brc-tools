"""Export HRRR sub-hourly cross-wind forecast at KVEL for the BasinWX aviation page."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
from pathlib import Path

from brc_tools.nwp import NWPSource
from brc_tools.nwp.aviation import (
    DEFAULT_MAX_FXX,
    DEFAULT_PRODUCT,
    build_airport_crosswind_payload,
    fetch_airport_winds,
)

LOG = logging.getLogger(__name__)

DEFAULT_AIRPORT = "KVEL"
DEFAULT_UPLOAD_BUCKET = "forecasts"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[1] / "data" / "basinwx"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export HRRR cross-wind forecast for a BasinWX airport",
    )
    parser.add_argument(
        "--airport",
        default=DEFAULT_AIRPORT,
        help=f"Airport key from lookups.toml (default: {DEFAULT_AIRPORT})",
    )
    parser.add_argument(
        "--product",
        default=DEFAULT_PRODUCT,
        choices=["subh", "sfc"],
        help=f"HRRR product (default: {DEFAULT_PRODUCT}; sfc = hourly fallback)",
    )
    parser.add_argument(
        "--max-fxx",
        type=int,
        default=DEFAULT_MAX_FXX,
        help=f"Maximum forecast hour (default: {DEFAULT_MAX_FXX})",
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


def _resolve_init_time(arg: str | None) -> dt.datetime:
    if arg:
        return dt.datetime.strptime(arg, "%Y-%m-%d %H")
    return NWPSource("hrrr").latest_init()


def _output_path(output_dir: Path, airport: str, init_time: dt.datetime) -> Path:
    stamp = init_time.strftime("%Y%m%d_%H%M")
    return output_dir / f"forecast_hrrr_{airport.lower()}_crosswind_{stamp}Z.json"


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
        init_time = _resolve_init_time(args.init_time)
        forecast_hours = list(range(0, args.max_fxx + 1))
        LOG.info(
            "Fetching HRRR %s %s init=%s fxx=0..%d",
            args.product,
            args.airport,
            init_time.strftime("%Y-%m-%d %HZ"),
            args.max_fxx,
        )
        ds = fetch_airport_winds(
            init_time=init_time,
            forecast_hours=forecast_hours,
            product=args.product,
        )
        payload = build_airport_crosswind_payload(
            ds,
            airport=args.airport,
            init_time=init_time,
            product=args.product,
        )
    except Exception as exc:
        LOG.error("HRRR aviation crosswind build failed: %s", exc)
        return 1

    output_path = _output_path(output_dir, args.airport, init_time)
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
            LOG.error("HRRR aviation crosswind upload failed: %s", exc)
            return 1
    else:
        LOG.info("Upload skipped")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

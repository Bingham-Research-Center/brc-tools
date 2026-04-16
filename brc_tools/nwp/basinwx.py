"""Export reduced HRRR surface layers for BasinWX."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
from pathlib import Path
from typing import Iterable

import numpy as np
import xarray as xr

from brc_tools.nwp import NWPSource
from brc_tools.nwp.derived import temp_K_to_C
from brc_tools.nwp.source import load_lookups

LOG = logging.getLogger(__name__)

DEFAULT_REGION = "uinta_basin"
DEFAULT_MAX_FXX = 18
DEFAULT_RUN_COUNT = 3
DEFAULT_STRIDE = 2
DEFAULT_UPLOAD_BUCKET = "forecasts"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "data" / "basinwx"

SURFACE_EXPORT_VARIABLES = [
    "temp_2m",
    "wind_u_10m",
    "wind_v_10m",
    "precip_1hr",
    "snowfall_1hr",
    "categorical_rain",
    "categorical_snow",
]

FIELD_SPECS = {
    "temperature_2m_c": {
        "label": "Temperature",
        "units": "Celsius",
        "precision": 1,
    },
    "wind_u_10m_ms": {
        "label": "Wind U",
        "units": "m/s",
        "precision": 1,
    },
    "wind_v_10m_ms": {
        "label": "Wind V",
        "units": "m/s",
        "precision": 1,
    },
    "rainfall_1h_mm": {
        "label": "Rainfall",
        "units": "Millimeters",
        "precision": 1,
    },
    "snowfall_1h_mm": {
        "label": "Snowfall",
        "units": "Millimeters",
        "precision": 1,
    },
}

GRID_PRECISION = 2
INDEX_FILENAME = "forecast_hrrr_surface_layers_index.json"


def latest_init_times(
    count: int = DEFAULT_RUN_COUNT,
    *,
    now: dt.datetime | None = None,
    source: NWPSource | None = None,
) -> list[dt.datetime]:
    """Return the latest ``count`` HRRR init times, newest first."""
    src = source or NWPSource("hrrr")
    latest = src.latest_init(now=now)
    return [latest - dt.timedelta(hours=offset) for offset in range(count)]


def fetch_surface_dataset(
    init_time: dt.datetime,
    *,
    forecast_hours: Iterable[int],
    region: str = DEFAULT_REGION,
    source: NWPSource | None = None,
) -> xr.Dataset:
    """Fetch the HRRR surface fields needed by the BasinWX export."""
    src = source or NWPSource("hrrr")
    return src.fetch(
        init_time=init_time,
        forecast_hours=list(forecast_hours),
        variables=SURFACE_EXPORT_VARIABLES,
        region=region,
    )


def prepare_surface_dataset(ds: xr.Dataset) -> xr.Dataset:
    """Convert raw HRRR variables into website-facing surface layers."""
    template = ds["temp_2m"]

    rain_flag = _maybe_field(ds, "categorical_rain", template, 0.0)
    snow_flag = _maybe_field(ds, "categorical_snow", template, 0.0)
    precip = _maybe_field(ds, "precip_1hr", template, 0.0).clip(min=0.0)
    snowfall = _maybe_field(ds, "snowfall_1hr", template, 0.0).clip(min=0.0)

    rainfall_mm = precip.where(rain_flag >= 0.5, 0.0)
    snowfall_mm = (snowfall * 1000.0).where(snow_flag >= 0.5, 0.0)

    prepared = xr.Dataset(coords=ds.coords)
    prepared["temperature_2m_c"] = temp_K_to_C(template).astype(float)
    prepared["wind_u_10m_ms"] = _maybe_field(ds, "wind_u_10m", template, np.nan)
    prepared["wind_v_10m_ms"] = _maybe_field(ds, "wind_v_10m", template, np.nan)
    prepared["rainfall_1h_mm"] = rainfall_mm.astype(float)
    prepared["snowfall_1h_mm"] = snowfall_mm.astype(float)

    for name, spec in FIELD_SPECS.items():
        prepared[name].attrs.update(
            units=spec["units"],
            long_name=spec["label"],
        )

    return prepared


def downsample_surface_dataset(ds: xr.Dataset, stride: int = DEFAULT_STRIDE) -> xr.Dataset:
    """Downsample the spatial grid by taking every ``stride`` point."""
    if stride <= 1:
        return ds

    y_dim, x_dim = _spatial_dims(ds)
    return ds.isel({y_dim: slice(None, None, stride), x_dim: slice(None, None, stride)})


def build_surface_payload(
    ds: xr.Dataset,
    *,
    init_time: dt.datetime,
    region: str = DEFAULT_REGION,
    stride: int = DEFAULT_STRIDE,
) -> dict[str, object]:
    """Serialize a reduced HRRR surface dataset into the BasinWX JSON contract."""
    lat_grid, lon_grid = _extract_grid(ds)
    valid_times = [_isoformat_utc(_to_datetime(value)) for value in ds.time.values]
    init_utc = _ensure_utc(init_time)
    init_np = np.datetime64(init_utc.replace(tzinfo=None))
    forecast_hours = [
        int((value - init_np) / np.timedelta64(1, "h"))
        for value in ds.time.values
    ]

    field_shape = [int(ds.sizes["time"]), int(lat_grid.shape[0]), int(lat_grid.shape[1])]

    payload = {
        "model": "hrrr",
        "product": "surface_layers",
        "region": region,
        "init_time": _isoformat_utc(init_utc),
        "generated_at": _isoformat_utc(dt.datetime.now(dt.timezone.utc)),
        "forecast_hours": forecast_hours,
        "valid_times": valid_times,
        "stride": int(stride),
        "bbox": _region_bbox(region, lat_grid, lon_grid),
        "grid": {
            "shape": list(lat_grid.shape),
            "lats": _flatten_rounded(lat_grid, GRID_PRECISION),
            "lons": _flatten_rounded(lon_grid, GRID_PRECISION),
        },
        "field_shape": field_shape,
        "variables": FIELD_SPECS,
        "fields": {},
    }

    for field_name, spec in FIELD_SPECS.items():
        payload["fields"][field_name] = _flatten_rounded(
            ds[field_name].values,
            spec["precision"],
        )

    return payload


def build_surface_index(entries: list[dict[str, object]]) -> dict[str, object]:
    """Build the run index file consumed by BasinWX."""
    return {
        "model": "hrrr",
        "product": "surface_layers_index",
        "generated_at": _isoformat_utc(dt.datetime.now(dt.timezone.utc)),
        "runs": entries,
    }


def export_latest_surface_layers(
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    region: str = DEFAULT_REGION,
    max_fxx: int = DEFAULT_MAX_FXX,
    run_count: int = DEFAULT_RUN_COUNT,
    stride: int = DEFAULT_STRIDE,
    upload: bool = False,
    upload_bucket: str = DEFAULT_UPLOAD_BUCKET,
) -> list[Path]:
    """Export the latest HRRR surface layers and a run index file."""
    output_root = Path(output_dir).expanduser()
    output_root.mkdir(parents=True, exist_ok=True)

    src = NWPSource("hrrr")
    forecast_hours = range(0, max_fxx + 1)
    written_paths: list[Path] = []
    index_entries: list[dict[str, object]] = []

    for init_time in latest_init_times(run_count, source=src):
        LOG.info("Fetching HRRR surface layers for %s", init_time.strftime("%Y-%m-%d %HZ"))
        raw = fetch_surface_dataset(
            init_time,
            forecast_hours=forecast_hours,
            region=region,
            source=src,
        )
        prepared = prepare_surface_dataset(raw)
        reduced = downsample_surface_dataset(prepared, stride=stride)
        payload = build_surface_payload(
            reduced,
            init_time=init_time,
            region=region,
            stride=stride,
        )

        output_path = output_root / _surface_filename(init_time)
        _write_json(payload, output_path)
        written_paths.append(output_path)
        index_entries.append(
            {
                "filename": output_path.name,
                "init_time": payload["init_time"],
                "forecast_hours": payload["forecast_hours"],
                "valid_times": payload["valid_times"],
            }
        )

    index_entries.sort(key=lambda entry: entry["init_time"], reverse=True)
    index_path = output_root / INDEX_FILENAME
    _write_json(build_surface_index(index_entries), index_path)
    written_paths.append(index_path)

    if upload:
        from brc_tools.download.push_data import load_config, send_json_to_server

        api_key, server_url = load_config()
        for path in written_paths:
            send_json_to_server(server_url, str(path), upload_bucket, api_key)

    return written_paths


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the export script."""
    parser = argparse.ArgumentParser(
        description="Export reduced HRRR surface layers for BasinWX",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Directory for output JSON files (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--region",
        default=DEFAULT_REGION,
        help=f"Named region from lookups.toml (default: {DEFAULT_REGION})",
    )
    parser.add_argument(
        "--max-fxx",
        type=int,
        default=DEFAULT_MAX_FXX,
        help=f"Maximum forecast hour to export (default: {DEFAULT_MAX_FXX})",
    )
    parser.add_argument(
        "--run-count",
        type=int,
        default=DEFAULT_RUN_COUNT,
        help=f"Number of latest runs to export (default: {DEFAULT_RUN_COUNT})",
    )
    parser.add_argument(
        "--stride",
        type=int,
        default=DEFAULT_STRIDE,
        help=f"Spatial decimation stride (default: {DEFAULT_STRIDE})",
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Upload the generated JSON files to BasinWX",
    )
    parser.add_argument(
        "--upload-bucket",
        default=DEFAULT_UPLOAD_BUCKET,
        help=f"Upload bucket name (default: {DEFAULT_UPLOAD_BUCKET})",
    )
    return parser.parse_args()


def main() -> int:
    """CLI entrypoint for the HRRR surface export."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    args = parse_args()
    try:
        paths = export_latest_surface_layers(
            output_dir=args.output_dir,
            region=args.region,
            max_fxx=args.max_fxx,
            run_count=args.run_count,
            stride=args.stride,
            upload=args.upload,
            upload_bucket=args.upload_bucket,
        )
    except Exception as exc:
        LOG.error("HRRR surface export failed: %s", exc)
        return 1

    for path in paths:
        LOG.info("Wrote %s", path)
    return 0


def _region_bbox(region: str, lat_grid: np.ndarray, lon_grid: np.ndarray) -> dict[str, object]:
    lookups = load_lookups()
    region_cfg = lookups.get("regions", {}).get(region)
    if region_cfg is not None:
        return {
            "requested": {
                "sw": list(region_cfg["sw"]),
                "ne": list(region_cfg["ne"]),
            },
            "actual": {
                "sw": [round(float(np.nanmin(lat_grid)), GRID_PRECISION), round(float(np.nanmin(lon_grid)), GRID_PRECISION)],
                "ne": [round(float(np.nanmax(lat_grid)), GRID_PRECISION), round(float(np.nanmax(lon_grid)), GRID_PRECISION)],
            },
        }
    return {
        "actual": {
            "sw": [round(float(np.nanmin(lat_grid)), GRID_PRECISION), round(float(np.nanmin(lon_grid)), GRID_PRECISION)],
            "ne": [round(float(np.nanmax(lat_grid)), GRID_PRECISION), round(float(np.nanmax(lon_grid)), GRID_PRECISION)],
        }
    }


def _extract_grid(ds: xr.Dataset) -> tuple[np.ndarray, np.ndarray]:
    if "latitude" not in ds.coords or "longitude" not in ds.coords:
        raise ValueError("Dataset must include latitude/longitude coordinates")

    lat = np.asarray(ds["latitude"].values, dtype=float)
    lon = np.asarray(ds["longitude"].values, dtype=float)
    if lat.ndim == 1 and lon.ndim == 1:
        lon_grid, lat_grid = np.meshgrid(lon, lat)
        return lat_grid, lon_grid
    return lat, lon


def _flatten_rounded(values: np.ndarray, precision: int) -> list[float | None]:
    rounded = np.round(np.asarray(values, dtype=float), decimals=precision).ravel()
    return [
        None if not np.isfinite(value) else float(value)
        for value in rounded
    ]


def _maybe_field(ds: xr.Dataset, name: str, template: xr.DataArray, fill_value: float) -> xr.DataArray:
    if name in ds.data_vars:
        return ds[name].astype(float)
    return xr.full_like(template, fill_value, dtype=float)


def _spatial_dims(ds: xr.Dataset) -> tuple[str, str]:
    if "y" in ds.dims and "x" in ds.dims:
        return "y", "x"
    if "latitude" in ds.dims and "longitude" in ds.dims:
        return "latitude", "longitude"
    raise ValueError(f"Could not determine spatial dimensions from {list(ds.dims)}")


def _surface_filename(init_time: dt.datetime) -> str:
    init_utc = _ensure_utc(init_time)
    return f"forecast_hrrr_surface_layers_{init_utc:%Y%m%d_%H%M}Z.json"


def _write_json(payload: dict[str, object], path: Path) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, allow_nan=False)


def _ensure_utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def _isoformat_utc(value: dt.datetime) -> str:
    utc_value = _ensure_utc(value)
    return utc_value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _to_datetime(value: np.datetime64) -> dt.datetime:
    seconds = value.astype("datetime64[s]").astype(int)
    return dt.datetime.fromtimestamp(int(seconds), tz=dt.timezone.utc)


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())

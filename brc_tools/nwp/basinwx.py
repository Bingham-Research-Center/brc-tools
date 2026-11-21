"""Export reduced HRRR (or RRFS) surface layers for BasinWX."""

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
from brc_tools.nwp.derived import rotate_winds_to_earth, temp_K_to_C
from brc_tools.nwp.source import load_lookups

LOG = logging.getLogger(__name__)

DEFAULT_MODEL = "hrrr"
#: Models whose surface fields this export has been checked against. RRFS's CONUS 3 km
#: grid is HRRR's grid, and every SURFACE_EXPORT_VARIABLES alias resolves for it.
SURFACE_EXPORT_MODELS = ("hrrr", "rrfs")
DEFAULT_REGION = "uinta_basin"
DEFAULT_MAX_FXX = 18
DEFAULT_RUN_COUNT = 3
DEFAULT_STRIDE = 2
DEFAULT_UPLOAD_BUCKET = "forecasts"
# staging dir for generated JSON — runtime output stays out of the repo checkout
DEFAULT_OUTPUT_DIR = Path("~/.cache/brc-tools/basinwx").expanduser()

SURFACE_EXPORT_VARIABLES = [
    "temp_2m",
    "wind_u_10m",
    "wind_v_10m",
    "precip_1hr",
    "snowfall_1hr",
    "categorical_rain",
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
    # Named "1h" for the website contract, but it is HRRR ASNOW: snowfall (depth, not
    # liquid) accumulated since the run began. HRRR has no hourly ASNOW message.
    "snowfall_1h_mm": {
        "label": "Snowfall since run start (depth)",
        "units": "Millimeters",
        "precision": 1,
    },
}

GRID_PRECISION = 2
INDEX_FILENAME = "forecast_hrrr_surface_layers_index.json"  # the HRRR name; see _index_filename


def latest_init_times(
    count: int = DEFAULT_RUN_COUNT,
    *,
    now: dt.datetime | None = None,
    source: NWPSource | None = None,
) -> list[dt.datetime]:
    """Return the latest ``count`` init times of ``source`` (default HRRR), newest first.

    Steps by the model's own cycle spacing: 1 h for HRRR, 3 h for RRFS, whose hourly
    files exist only for the 00/03/.../21Z runs.
    """
    src = source or NWPSource(DEFAULT_MODEL)
    latest = src.latest_init(now=now)
    step = src.init_cadence_hours
    return [latest - dt.timedelta(hours=offset * step) for offset in range(count)]


def fetch_surface_dataset(
    init_time: dt.datetime,
    *,
    forecast_hours: Iterable[int],
    region: str = DEFAULT_REGION,
    source: NWPSource | None = None,
) -> xr.Dataset:
    """Fetch the surface fields needed by the BasinWX export (HRRR unless ``source`` says)."""
    src = source or NWPSource(DEFAULT_MODEL)
    ds = src.fetch(
        init_time=init_time,
        forecast_hours=list(forecast_hours),
        variables=SURFACE_EXPORT_VARIABLES,
        region=region,
    )
    # HRRR u/v are grid-relative (about 8 deg off north over the Basin); the website
    # draws arrows from these components as east/north. The rotation uses the grid the
    # fetched GRIB declares, so another source gets its own grid's angle or an error.
    return rotate_winds_to_earth(ds, "wind_u_10m", "wind_v_10m")


def prepare_surface_dataset(
    ds: xr.Dataset, *, init_time: dt.datetime | None = None
) -> xr.Dataset:
    """Convert raw model variables into website-facing surface layers.

    With ``init_time``, a snowfall total missing at the analysis hour is set to zero:
    RRFS ships no ASNOW message at f000, where HRRR ships one that is all zeros.
    """
    template = ds["temp_2m"]

    rain_flag = _maybe_field(ds, "categorical_rain", template, 0.0)
    precip = _maybe_field(ds, "precip_1hr", template, 0.0).clip(min=0.0)
    snowfall = _maybe_field(ds, "snowfall_1hr", template, 0.0).clip(min=0.0)

    rainfall_mm = precip.where(rain_flag >= 0.5, 0.0)
    # ASNOW is a run total, so it is not masked by the hour's categorical snow flag:
    # masking zeroed the total in any hour the flag was off (1,615 grid-hours in one run
    # on 2026-11-19) and it reappeared the next hour.
    snowfall_mm = snowfall * 1000.0
    if init_time is not None:
        at_init = ds.time == np.datetime64(_ensure_utc(init_time).replace(tzinfo=None))
        snowfall_mm = snowfall_mm.where(~(at_init & snowfall_mm.isnull()), 0.0)

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
    model: str = DEFAULT_MODEL,
) -> dict[str, object]:
    """Serialize a reduced surface dataset into the BasinWX JSON contract."""
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
        "model": model,
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


def build_surface_index(
    entries: list[dict[str, object]], *, model: str = DEFAULT_MODEL
) -> dict[str, object]:
    """Build the run index file consumed by BasinWX."""
    return {
        "model": model,
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
    server_url: str | None = None,
    model: str = DEFAULT_MODEL,
) -> list[Path]:
    """Export the latest surface layers of ``model`` and a run index file.

    Files are named ``forecast_<model>_surface_layers_*``, so each model keeps its own
    run files and its own index on the receiving side.
    """
    if model not in SURFACE_EXPORT_MODELS:
        raise ValueError(f"model must be one of {SURFACE_EXPORT_MODELS}, got {model!r}")
    output_root = Path(output_dir).expanduser()
    output_root.mkdir(parents=True, exist_ok=True)

    src = NWPSource(model)
    forecast_hours = range(0, max_fxx + 1)
    written_paths: list[Path] = []
    index_entries: list[dict[str, object]] = []

    for init_time in latest_init_times(run_count, source=src):
        LOG.info("Fetching %s surface layers for %s", model.upper(),
                 init_time.strftime("%Y-%m-%d %HZ"))
        raw = fetch_surface_dataset(
            init_time,
            forecast_hours=forecast_hours,
            region=region,
            source=src,
        )
        prepared = prepare_surface_dataset(raw, init_time=init_time)
        reduced = downsample_surface_dataset(prepared, stride=stride)
        payload = build_surface_payload(
            reduced,
            init_time=init_time,
            region=region,
            stride=stride,
            model=model,
        )

        output_path = output_root / _surface_filename(init_time, model)
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
    index_path = output_root / _index_filename(model)
    _write_json(build_surface_index(index_entries, model=model), index_path)
    written_paths.append(index_path)

    if upload:
        from brc_tools.download.push_data import (load_config_urls,
                                                  send_bundle_to_all)

        api_key, config_urls = load_config_urls()
        urls = [server_url] if server_url else config_urls
        # written_paths ends with the index, and send_bundle_to_all drops any
        # host that already failed a run file -- so a host never gets an index
        # advertising run files it rejected.
        send_bundle_to_all(urls, [str(p) for p in written_paths],
                           upload_bucket, api_key)

    return written_paths


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the export script."""
    parser = argparse.ArgumentParser(
        description="Export reduced HRRR (or RRFS) surface layers for BasinWX",
    )
    parser.add_argument(
        "--model",
        choices=SURFACE_EXPORT_MODELS,
        default=DEFAULT_MODEL,
        help=(
            f"Model to export (default: {DEFAULT_MODEL}). rrfs needs Herbie >= 2026.10.0 "
            "(env brc-tools-2026-11) and writes forecast_rrfs_surface_layers_* files, "
            "which no BasinWX page reads yet"
        ),
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
    parser.add_argument(
        "--server-url",
        default=None,
        help="Override server URL (default: read from ~/.config/ubair-website/website_url)",
    )
    return parser.parse_args()


def main() -> int:
    """CLI entrypoint for the surface export."""
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
            server_url=args.server_url,
            model=args.model,
        )
    except Exception as exc:
        LOG.error("%s surface export failed: %s", args.model.upper(), exc)
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
    lon = np.where(lon > 180, lon - 360, lon)
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


def _surface_filename(init_time: dt.datetime, model: str = DEFAULT_MODEL) -> str:
    init_utc = _ensure_utc(init_time)
    return f"forecast_{model}_surface_layers_{init_utc:%Y%m%d_%H%M}Z.json"


def _index_filename(model: str = DEFAULT_MODEL) -> str:
    return f"forecast_{model}_surface_layers_index.json"


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

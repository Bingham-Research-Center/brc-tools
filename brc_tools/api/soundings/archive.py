"""Cache each IGRA station ZIP once; replay launches through Siphon's parser."""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import polars as pl

from brc_tools.obs.archive import atomic, digest, encode
from brc_tools.obs.research import utc

from .client import resolve_station


def station_archive(station, *, root, budget, year=None):
    from siphon.simplewebservice.igra2 import IGRAUpperAir

    site = resolve_station(station, "igra2")
    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}", site):
        raise ValueError("unresolved IGRA identifier; do not guess provider IDs")
    root = Path(root)
    receipt = root / f"{site}-{year or 'por'}.json"
    if receipt.exists():
        r = json.loads(receipt.read_text())
        blob = (root / r["file"]).read_bytes()
        if digest(blob) != r["sha256"]:
            raise ValueError("IGRA archive digest mismatch")
        return receipt
    endpoint = IGRAUpperAir()
    endpoint._base = (
        "https://www.ncei.noaa.gov/data/integrated-global-radiosonde-archive/access/"
    )
    remote = (
        f"data-y2d/{site}-data-beg{year}.txt.zip"
        if year
        else f"data-por/{site}-data.txt.zip"
    )
    with budget.transport():
        response = endpoint.get_path(remote)
    blob = response.content
    # Validate the archive before publishing a successful receipt.
    from io import BytesIO
    from zipfile import ZipFile

    with ZipFile(BytesIO(blob)) as z:
        if z.testzip() is not None:
            raise ValueError("corrupt IGRA archive")
    sha = digest(blob)
    name = f"{sha}.zip"
    atomic(root / name, blob)
    atomic(
        receipt,
        encode(
            dict(
                station=station,
                site=site,
                file=name,
                sha256=sha,
                provider="igra2",
                source_url=endpoint._base + remote,
                format="original-provider-zip",
            )
        ),
    )
    return receipt


def extract(receipt, start, end):
    """Return all delivered columns, normalized SI winds, and explicit outcome."""
    from siphon.simplewebservice.igra2 import IGRAUpperAir

    receipt = Path(receipt)
    info = json.loads(receipt.read_text())
    blob = (receipt.parent / info["file"]).read_bytes()
    if digest(blob) != info["sha256"]:
        raise ValueError("IGRA archive digest mismatch")
    parser = IGRAUpperAir()
    parser.folder, parser.suffix, parser.site_id = (
        "data/data-por/",
        "-data.txt",
        info["site"],
    )
    parser.begin_date = utc(start).replace(tzinfo=None)
    # Siphon uses inclusive ends; filter to the study's half-open window below.
    parser.end_date = utc(end).replace(tzinfo=None)
    parser.get_path = lambda path: SimpleNamespace(content=blob)
    try:
        frame, headers = parser._get_data()
    except ValueError as exc:
        if "No dates match selection" in str(exc):
            return pl.DataFrame(), {"outcome": "missing_launch", **info}
        raise ValueError("IGRA parse failure") from None
    df = pl.from_pandas(frame).with_columns(
        pl.col("date").dt.replace_time_zone("UTC").alias("time"),
        pl.lit(info["station"]).alias("station"),
    )
    df = df.filter((pl.col("time") >= utc(start)) & (pl.col("time") < utc(end)))
    names = {
        "height": "height_m",
        "pressure": "pressure_hpa",
        "temperature": "temperature_c",
        "dewpoint": "dewpoint_c",
        "u_wind": "u_ms",
        "v_wind": "v_ms",
    }
    df = df.rename({k: v for k, v in names.items() if k in df.columns})
    return df, {
        "outcome": "success" if df.height else "missing_launch",
        **info,
        "height_reference": "geopotential_m",
        "wind_unit": "m/s",
        "headers": json.loads(headers.to_json(orient="records", date_format="iso")),
    }

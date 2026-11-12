"""Token-free hydrology and snow-course clients: USGS Water Data (OGC API) and the
NRCS Air and Water Database (AWDB) REST API.

Both providers publish no quota contract, so the restraint here is cache-first access
and one request at a time with a pause between pages. Every raw page is written to the
cache before it is parsed, with a ``.meta.json`` sidecar (URL, parameters, time,
server ``Last-Modified``), so a parser fix never re-downloads. Derived parquet tables
sit beside the raw pages and are trusted only while their sidecar lists the same pages.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

__all__ = ["cache_dir", "get_json", "save_raw", "fresh_parquet"]


def cache_dir(sub: str, cache_dir: Path | str | None = None) -> Path:
    """``<cache_dir or $BRC_HYDRO_CACHE or ~/.cache/brc-tools/hydro>/<sub>``, created."""
    base = Path(cache_dir) if cache_dir is not None else Path(
        os.getenv("BRC_HYDRO_CACHE", Path.home() / ".cache" / "brc-tools" / "hydro")
    )
    p = base / sub
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_json(url: str, params: dict | None = None, *, timeout=(10, 60), pause: float = 1.0,
             retries: int = 1, backoff: float = 30.0):
    """One GET, parsed as JSON. A connection error is retried once after ``backoff`` s
    (brc-tools: retry with backoff at boundaries only); an HTTP error is raised as is.
    ``pause`` seconds are slept *after* the request so paging stays polite."""
    import requests

    attempt = 0
    while True:
        try:
            resp = requests.get(url, params=params, timeout=timeout,
                                headers={"Accept": "application/json", "User-Agent": "brc-tools/hydro"})
            resp.raise_for_status()
            data = resp.json()
            meta = {"url": resp.url, "status": resp.status_code,
                    "last_modified": resp.headers.get("Last-Modified"),
                    "retrieved_utc": datetime.now(timezone.utc).isoformat()}
            if pause:
                time.sleep(pause)
            return data, meta
        except requests.ConnectionError:
            if attempt >= retries:
                raise
            attempt += 1
            time.sleep(backoff)


def save_raw(path: Path, data, meta: dict) -> Path:
    """Write ``<path>`` (JSON) and ``<path>.meta.json`` atomically."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(json.dumps(data, separators=(",", ":")))
    os.replace(tmp, path)
    path.with_suffix(path.suffix + ".meta.json").write_text(json.dumps(meta, indent=1, sort_keys=True))
    return path


def fresh_parquet(parquet: Path, pages: list[Path]) -> bool:
    """True when ``parquet`` exists and its sidecar lists exactly these raw pages."""
    side = parquet.with_suffix(".meta.json")
    if not parquet.exists() or not side.exists():
        return False
    try:
        return json.loads(side.read_text()).get("pages") == [p.name for p in pages]
    except (OSError, ValueError):
        return False

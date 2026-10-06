"""Checks on the routing against things that are not the DEM: USGS NWIS stream gauges
(drainage areas), the Watershed Boundary Dataset (names) and NHD flowlines (mapped
streams).  All three are open USGS services with no token; hydrography is not NWP,
so Herbie does not apply (``docs/nwp/NWP-SOURCE-MATRIX.md`` rule).  The only network
calls are ``_get_text`` and ``_get_json`` so tests can monkeypatch them.
"""
from __future__ import annotations

import csv
import io
import logging
import time
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

NWIS_SITE_URL = "https://waterservices.usgs.gov/nwis/site/"
NATIONAL_MAP = "https://hydro.nationalmap.gov/arcgis/rest/services/{service}/MapServer/{layer}/query"
WBD_LAYERS = {8: 4, 10: 5, 12: 6}       # HUC level -> WBD MapServer layer (probed 2026-09-14)
NHD_FLOWLINE_LARGE = 6                  # NHD "Flowline - Large Scale"
NHD_FLOWLINE_SMALL = 4
SQMI_KM2 = 2.589988


def _get_text(url: str, params: dict | None = None, *, attempts: int = 3, timeout: float = 60.0) -> str:
    import requests

    err = None
    for k in range(attempts):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            r.raise_for_status()
            return r.text
        except Exception as exc:  # noqa: BLE001
            err = exc
            time.sleep(2 + 3 * k)
    raise RuntimeError(f"GET {url} failed after {attempts} attempts: {err!r}")


def _get_json(url: str, params: dict | None = None, *, attempts: int = 3, timeout: float = 60.0) -> dict:
    import json

    return json.loads(_get_text(url, params, attempts=attempts, timeout=timeout))


# --------------------------------------------------------------------------- #
# NWIS gauges
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class NWISSite:
    site_no: str
    name: str
    lat: float
    lon: float
    drain_area_km2: float


def parse_nwis_rdb(text: str) -> list[NWISSite]:
    """Parse the NWIS site service's RDB (tab-delimited with ``#`` comments and a
    format line after the header) into sites that report a drainage area."""
    lines = [ln for ln in text.splitlines() if not ln.startswith("#")]
    rd = csv.DictReader(io.StringIO("\n".join(lines)), delimiter="\t")
    out = []
    for i, row in enumerate(rd):
        if i == 0:
            continue                      # the "15s 50s ..." format line
        try:
            da = float(row["drain_area_va"])
            out.append(NWISSite(row["site_no"], row["station_nm"], float(row["dec_lat_va"]),
                                float(row["dec_long_va"]), da * SQMI_KM2))
        except (ValueError, TypeError, KeyError):
            continue
    return out


def nwis_sites(bbox, *, timeout: float = 60.0) -> list[NWISSite]:
    """Stream sites with a drainage area inside ``bbox`` = (lon_w, lat_s, lon_e, lat_n)."""
    w, s, e, n = bbox
    params = {"format": "rdb", "bBox": f"{w:.2f},{s:.2f},{e:.2f},{n:.2f}", "siteType": "ST",
              "siteOutput": "expanded", "siteStatus": "all"}
    return parse_nwis_rdb(_get_text(NWIS_SITE_URL, params, timeout=timeout))


def snap_to_channel(acc: np.ndarray, grid, lat: float, lon: float, target_km2: float, *,
                    snap_m: float = 300.0) -> tuple[int, int, float, float]:
    """Snap a gauge to the D8 channel: within ``snap_m`` the cell whose accumulated area
    is closest (in log) to the gauge's among cells with >= 0.3 x that area, else the
    window maximum.  Returns ``(j, i, d8_km2, snap_distance_m)``."""
    j, i = (int(v) for v in grid.ji(lat, lon))
    r = int(np.ceil(snap_m / grid.res))
    ny, nx = acc.shape
    if not (r <= j < ny - r and r <= i < nx - r):
        raise ValueError("gauge too close to the grid edge")
    win = acc[j - r:j + r + 1, i - r:i + r + 1].astype(float) * grid.cell_area_m2 / 1e6
    cand = np.where(win >= 0.3 * target_km2, np.abs(np.log(np.maximum(win, 1e-9) / target_km2)), np.inf)
    jj, ii = np.unravel_index(np.argmin(cand) if np.isfinite(cand).any() else np.argmax(win), win.shape)
    return j - r + jj, i - r + ii, float(win[jj, ii]), float(np.hypot(jj - r, ii - r) * grid.res)


def compare_to_nwis(acc: np.ndarray, grid, *, snap_m: float = 300.0, pad_deg: float = 0.05, sites=None):
    """D8 drainage area against every NWIS gauge inside the grid, as a polars frame."""
    import polars as pl

    lon_w, lon_e, lat_s, lat_n = grid.extent_lonlat()
    if sites is None:
        sites = nwis_sites((lon_w + pad_deg, lat_s + pad_deg, lon_e - pad_deg, lat_n - pad_deg))
    grid_km2 = float(acc.max()) * grid.cell_area_m2 / 1e6
    rows = []
    for s in sites:
        try:
            j, i, d8, dist = snap_to_channel(acc, grid, s.lat, s.lon, s.drain_area_km2, snap_m=snap_m)
        except ValueError:
            continue
        rows.append({"site_no": s.site_no, "station": s.name, "lat": s.lat, "lon": s.lon,
                     "nwis_km2": round(s.drain_area_km2, 1), "d8_km2": round(d8, 1),
                     "ratio_d8_nwis": round(d8 / s.drain_area_km2, 3), "snap_m": round(dist),
                     "note": "exceeds grid" if s.drain_area_km2 > 0.5 * grid_km2 else ""})
    return pl.DataFrame(rows).sort("nwis_km2", descending=True) if rows else pl.DataFrame()


def routing_score(df, *, min_km2: float = 20.0) -> dict:
    """Median D8/NWIS ratio and the shares within 10 % and 25 %, for gauges >= ``min_km2``
    that the grid holds whole."""
    if df.height == 0:
        return {"n": 0}
    ok = df.filter((df["note"] == "") & (df["nwis_km2"] >= min_km2))
    r = np.maximum(ok["ratio_d8_nwis"].to_numpy(), 1e-6)
    return {"n": int(ok.height), "median_ratio": float(np.median(r)) if r.size else float("nan"),
            "within_10pct": float(np.mean(np.abs(np.log(r)) < 0.1)) if r.size else float("nan"),
            "within_25pct": float(np.mean(np.abs(np.log(r)) < 0.25)) if r.size else float("nan")}


# --------------------------------------------------------------------------- #
# WBD names and NHD flowlines (USGS National Map ArcGIS REST)
# --------------------------------------------------------------------------- #
def wbd_name(lon: float, lat: float, *, level: int = 10, timeout: float = 30.0) -> str:
    """The Watershed Boundary Dataset unit name containing a point ("" if none)."""
    params = {"geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "inSR": "4326",
              "spatialRel": "esriSpatialRelIntersects", "outFields": "name", "returnGeometry": "false",
              "f": "json"}
    try:
        js = _get_json(NATIONAL_MAP.format(service="wbd", layer=WBD_LAYERS[level]), params, timeout=timeout)
    except RuntimeError as exc:
        logger.warning("WBD query failed at %s,%s: %s", lon, lat, exc)
        return ""
    feats = js.get("features") or []
    return str(feats[0]["attributes"].get("name", "")) if feats else ""


@dataclass(frozen=True)
class Flowline:
    gnis_name: str
    reachcode: str
    lonlat: np.ndarray          # (n, 2) vertices


def nhd_flowlines(bbox, *, layer: int = NHD_FLOWLINE_LARGE, max_records: int = 2000,
                  timeout: float = 60.0) -> list[Flowline]:
    """NHD flowlines intersecting ``bbox`` = (lon_w, lat_s, lon_e, lat_n), paginated."""
    w, s, e, n = bbox
    out, offset = [], 0
    while True:
        params = {"geometry": f"{w},{s},{e},{n}", "geometryType": "esriGeometryEnvelope", "inSR": "4326",
                  "outSR": "4326", "spatialRel": "esriSpatialRelIntersects",
                  "outFields": "gnis_name,reachcode", "returnGeometry": "true", "f": "json",
                  "resultOffset": offset, "resultRecordCount": max_records}
        js = _get_json(NATIONAL_MAP.format(service="nhd", layer=layer), params, timeout=timeout)
        feats = js.get("features") or []
        for f in feats:
            attrs = f.get("attributes") or {}
            for path in (f.get("geometry") or {}).get("paths", []):
                out.append(Flowline(str(attrs.get("gnis_name") or ""), str(attrs.get("reachcode") or ""),
                                    np.asarray(path, dtype=float)))
        if not js.get("exceededTransferLimit") or not feats:
            break
        offset += len(feats)
    return out


def channel_agreement(chan: np.ndarray, grid, flowlines, *, tol_m: float = 100.0) -> dict:
    """How well D8 channels and mapped streams coincide: the fraction of flowline vertices
    within ``tol_m`` of a channel cell, and the fraction of channel cells within ``tol_m``
    of a flowline vertex."""
    from scipy.spatial import cKDTree

    cj, ci = np.nonzero(chan)
    if cj.size == 0 or not flowlines:
        return {"n_channel_cells": int(cj.size), "n_vertices": 0}
    cx, cy = grid.xy(cj, ci)
    verts = np.concatenate([f.lonlat for f in flowlines])
    vx, vy = grid._to_grid.transform(verts[:, 0], verts[:, 1])
    tree_c = cKDTree(np.column_stack([cx, cy]))
    tree_v = cKDTree(np.column_stack([vx, vy]))
    d_v, _ = tree_c.query(np.column_stack([vx, vy]))
    d_c, _ = tree_v.query(np.column_stack([cx, cy]))
    return {"n_channel_cells": int(cj.size), "n_vertices": int(len(vx)),
            "flowline_vertices_near_channel": float(np.mean(d_v <= tol_m)),
            "channel_cells_near_flowline": float(np.mean(d_c <= tol_m))}

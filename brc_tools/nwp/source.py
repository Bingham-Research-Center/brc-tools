"""NWPSource: model-agnostic wrapper around Herbie, driven by lookups.toml."""

import datetime
import logging
import os
import tomllib
from pathlib import Path

import numpy as np
import polars as pl
import xarray as xr
from herbie import Herbie

from brc_tools.nwp._cache import purge_cached_files, validate_cached_grib
from brc_tools.nwp._crop import crop_to_bbox, nearest_point_value
from brc_tools.nwp._normalise import normalize_coords

logger = logging.getLogger(__name__)

_LOOKUPS_PATH = Path(__file__).parent / "lookups.toml"
_lookups_cache: dict | None = None


def load_lookups(path: Path | None = None) -> dict:
    """Load and cache the TOML alias registry."""
    global _lookups_cache
    if _lookups_cache is not None and path is None:
        return _lookups_cache
    p = path or _LOOKUPS_PATH
    with open(p, "rb") as f:
        data = tomllib.load(f)
    if path is None:
        _lookups_cache = data
    return data


class NWPSource:
    """Fetch NWP model data via Herbie using canonical aliases from lookups.toml.

    Usage::

        src = NWPSource("hrrr")
        ds = src.fetch(
            init_time="2025-02-22 16Z",
            forecast_hours=range(0, 13),
            variables=["temp_2m", "wind_u_10m", "wind_v_10m", "mslp"],
            region="uinta_basin",
        )
    """

    def __init__(self, model: str, *, member: str | None = None,
                 product: str | None = None):
        self._lu = load_lookups()
        if model not in self._lu["models"]:
            raise ValueError(
                f"Unknown model {model!r}. "
                f"Available: {list(self._lu['models'])}"
            )
        self._model_key = model
        self._cfg = self._lu["models"][model]
        self._member = member or self._cfg.get("default_member")
        self._default_product = product or self._cfg["default_product"]
        self._defaults = self._lu.get("defaults", {})

    # ── public API ──────────────────────────────────────────────────────

    def fetch(
        self,
        init_time,
        forecast_hours,
        variables: list[str],
        *,
        region: str | None = None,
        bbox: tuple | None = None,
        levels: list[int] | None = None,
        product: str | None = None,
        max_workers: int = 6,
    ) -> xr.Dataset:
        """Fetch model data for canonical aliases over a range of forecast hours.

        Downloads are parallelised across forecast hours (up to
        ``max_workers`` concurrent threads). Set ``max_workers=1``
        to force sequential behaviour.

        Returns an xr.Dataset with dims (time, ...) and variables renamed
        to their canonical ``output_var`` names from lookups.toml.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        init_dt = _parse_init_time(init_time)
        aliases = self._lu["aliases"]
        sw, ne = self._resolve_bbox(region, bbox)
        var_groups = self._group_by_product(variables, aliases, product)
        crop_method = self._cfg.get("crop_method", "lonlat_after_aux")

        # Build flat work list: (fxx, alias_name, search_str, output_var, product)
        retries = self._defaults.get("download_retries", 2)
        work_items = []
        for fxx in (int(f) for f in forecast_hours):
            fxx_product = self._resolve_product_for_fxx(
                product or self._default_product, fxx
            )
            for prod_key, var_list in var_groups.items():
                actual_product = prod_key if prod_key else fxx_product
                for alias_name, search_str, output_var in var_list:
                    alias_cfg = aliases[alias_name]
                    if "derived_from" in alias_cfg:
                        continue
                    for search, level_label in self._expand_search(
                        search_str, levels, alias_cfg
                    ):
                        out_name = (
                            output_var if level_label is None
                            else f"{output_var}_{level_label}"
                        )
                        work_items.append(
                            (fxx, search, actual_product, out_name, retries)
                        )

        def _do_fetch(item):
            fxx, search, prod, out_name, ret = item
            ds = self._herbie_fetch(init_dt, fxx, search, prod, ret)
            if ds is not None:
                data_vars = list(ds.data_vars)
                if data_vars:
                    ds = ds.rename({data_vars[0]: out_name})
                keep = {"time", "latitude", "longitude", "y", "x"}
                drop = [n for n in ds.coords if n not in keep and n not in ds.dims]
                if drop:
                    ds = ds.drop_vars(drop, errors="ignore")
            return fxx, out_name, ds

        # Submit all (hour × variable) pairs to a flat thread pool
        raw_results: dict[tuple[int, str], xr.Dataset] = {}
        fxx_set: set[int] = set()

        if max_workers <= 1 or len(work_items) <= 1:
            for item in work_items:
                fxx, out_name, ds = _do_fetch(item)
                if ds is not None:
                    raw_results[(fxx, out_name)] = ds
                    fxx_set.add(fxx)
        else:
            workers = min(max_workers, len(work_items))
            logger.info(
                "Parallel fetch: %d tasks (%d hours × %d vars) with %d workers",
                len(work_items),
                len(set(i[0] for i in work_items)),
                len(set(i[3] for i in work_items)),
                workers,
            )
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(_do_fetch, item): item for item in work_items}
                for future in as_completed(futures):
                    try:
                        fxx, out_name, ds = future.result()
                        if ds is not None:
                            raw_results[(fxx, out_name)] = ds
                            fxx_set.add(fxx)
                    except Exception as exc:
                        item = futures[future]
                        logger.warning("Fetch failed f%03d %s: %s", item[0], item[3], exc)

        # Group by fxx, merge, normalize, crop
        results: dict[int, xr.Dataset] = {}
        for fxx in sorted(fxx_set):
            hour_ds = {k[1]: v for k, v in raw_results.items() if k[0] == fxx}
            if not hour_ds:
                continue
            ds_hour = xr.merge(
                list(hour_ds.values()), combine_attrs="drop", compat="override"
            )
            ds_hour = normalize_coords(ds_hour, init_dt, fxx)
            if sw is not None and ne is not None:
                ds_hour = crop_to_bbox(ds_hour, sw, ne, crop_method)
            results[fxx] = ds_hour

        hour_slices = [results[fxx] for fxx in sorted(results)]
        if not hour_slices:
            raise RuntimeError(
                f"No data returned for {self._model_key} init={init_dt} "
                f"hours={list(forecast_hours)} vars={variables}"
            )
        return xr.concat(hour_slices, dim="time", combine_attrs="drop")

    def extract_at_waypoints(
        self,
        ds: xr.Dataset,
        *,
        group: str | None = None,
        waypoints: list[str] | None = None,
    ) -> pl.DataFrame:
        """Extract time series at named waypoints from a gridded dataset.

        Returns a Polars DataFrame with columns: waypoint, valid_time, plus
        one column per data variable in the dataset.
        """
        wp_names = self._resolve_waypoints(group, waypoints)
        all_wps = self._lu["waypoints"]
        method = self._cfg.get("nearest_point_method", "kdtree_2d")

        rows = []
        for wp_name in wp_names:
            wp = all_wps[wp_name]
            pt = nearest_point_value(ds, wp["lat"], wp["lon"], method=method)
            for t_idx in range(pt.sizes.get("time", 1)):
                row = {"waypoint": wp_name}
                if "time" in pt.dims:
                    row["valid_time"] = pt.time.values[t_idx].item()
                    pt_t = pt.isel(time=t_idx)
                else:
                    pt_t = pt
                for var_name in pt_t.data_vars:
                    val = pt_t[var_name].values
                    row[var_name] = float(val) if np.isfinite(val) else None
                rows.append(row)
        return pl.DataFrame(rows)

    def latest_init(self, now: datetime.datetime | None = None) -> datetime.datetime:
        """Find the most recent init time likely to have data available."""
        now = now or datetime.datetime.now(datetime.timezone.utc)
        cadence = self._cfg["init_cadence_hours"]
        lag_hours = 2  # conservative availability lag
        candidate = now - datetime.timedelta(hours=lag_hours)
        # Round down to nearest cadence
        hour = (candidate.hour // cadence) * cadence
        return candidate.replace(hour=hour, minute=0, second=0, microsecond=0)

    # ── internal helpers ────────────────────────────────────────────────

    def _fetch_hour_variables(self, init_dt, fxx, var_list, aliases, product, levels):
        """Fetch all requested variables for a single forecast hour."""
        retries = self._defaults.get("download_retries", 2)
        results = {}
        for alias_name, search_str, output_var in var_list:
            alias_cfg = aliases[alias_name]
            # Handle derived variables
            if "derived_from" in alias_cfg:
                continue  # will be computed after all native vars are fetched

            actual_searches = self._expand_search(search_str, levels, alias_cfg)
            for search, level_label in actual_searches:
                ds = self._herbie_fetch(init_dt, fxx, search, product, retries)
                if ds is not None:
                    out_name = output_var if level_label is None else f"{output_var}_{level_label}"
                    data_vars = list(ds.data_vars)
                    if data_vars:
                        ds = ds.rename({data_vars[0]: out_name})
                    # Strip transient coords NOW so merge doesn't conflict
                    keep = {"time", "latitude", "longitude", "y", "x"}
                    drop = [n for n in ds.coords if n not in keep and n not in ds.dims]
                    if drop:
                        ds = ds.drop_vars(drop, errors="ignore")
                    results[out_name] = ds
        return results

    def _herbie_fetch(self, init_dt, fxx, search_str, product, retries):
        """Single Herbie fetch with cache validation, file-level locking, and retry.

        A per-GRIB-file lock (via fasteners) prevents concurrent threads/processes
        from corrupting the cache when multiple workers download the same file.
        The lock key is (model, init, fxx, product, member) — different search
        strings hitting the same GRIB file serialize, but different files download
        freely in parallel.
        """
        import tempfile
        import fasteners

        lock_dir = os.environ.get("BRC_TOOLS_LOCK_DIR") or tempfile.gettempdir()
        member_str = self._member or "det"
        lock_name = (
            f"herbie_{self._cfg['herbie_model']}_{init_dt:%Y%m%d_%H}_"
            f"f{fxx:03d}_{product}_{member_str}.lock"
        )
        lock = fasteners.InterProcessLock(os.path.join(lock_dir, lock_name))

        for attempt in range(retries):
            try:
                herbie_kwargs = dict(
                    model=self._cfg["herbie_model"],
                    product=product,
                    fxx=fxx,
                )
                if self._member is not None:
                    herbie_kwargs["member"] = self._member
                cache_dir = self._cache_dir()
                if cache_dir is not None:
                    herbie_kwargs["save_dir"] = cache_dir

                with lock:
                    H = Herbie(init_dt, **herbie_kwargs)
                    grib_path = getattr(H, "grib", None)
                    if grib_path and not validate_cached_grib(grib_path):
                        purge_cached_files(H)
                    ds = H.xarray(search_str, remove_grib=True)

                return ds
            except Exception as exc:
                logger.warning(
                    "Herbie fetch failed (attempt %d/%d) %s f%03d %r: %s",
                    attempt + 1, retries, self._model_key, fxx, search_str, exc,
                )
                if attempt < retries - 1:
                    with lock:
                        try:
                            purge_cached_files(H)
                        except Exception:
                            pass
                    continue
                if self._defaults.get("return_nans_on_failure", False):
                    return None
                raise
        return None

    def _expand_search(self, search_template, levels, alias_cfg):
        """Expand a {level} placeholder into multiple concrete search strings."""
        if "{level}" not in search_template:
            return [(search_template, None)]
        use_levels = levels or alias_cfg.get("default_levels", [])
        if not use_levels:
            raise ValueError(
                f"Alias requires levels= but none provided and no default_levels set"
            )
        return [(search_template.format(level=lv), str(lv)) for lv in use_levels]

    def _group_by_product(self, variables, aliases, override_product):
        """Group requested variables by the product they need."""
        groups = {}  # product_key -> [(alias_name, search_str, output_var)]
        for var_name in variables:
            if var_name not in aliases:
                raise ValueError(
                    f"Unknown alias {var_name!r}. Check lookups.toml."
                )
            alias = aliases[var_name]
            # Derived variables (wind_speed_10m, wind_dir_10m) don't need fetching
            if "derived_from" in alias:
                continue
            search_table = alias.get("search", {})
            if self._model_key not in search_table:
                logger.info(
                    "Alias %r not available for model %s; skipping",
                    var_name, self._model_key,
                )
                continue
            search_str = search_table[self._model_key]
            output_var = alias["output_var"]
            # Determine product for this alias
            products_table = alias.get("products", {})
            prod_key = products_table.get(self._model_key)
            if override_product:
                prod_key = override_product
            groups.setdefault(prod_key, []).append((var_name, search_str, output_var))
        return groups

    def _resolve_bbox(self, region, bbox):
        if bbox is not None:
            return bbox[:2], bbox[2:]
        if region is not None:
            r = self._lu["regions"][region]
            return tuple(r["sw"]), tuple(r["ne"])
        return None, None

    def _resolve_waypoints(self, group, waypoints):
        if waypoints is not None:
            return waypoints
        if group is not None:
            return self._lu["waypoint_groups"][group]
        raise ValueError("Provide either group= or waypoints=")

    def _resolve_product_for_fxx(self, base_product, fxx):
        """Handle model-specific product breakpoints (e.g., GEFS atmos.5 above fxx 240)."""
        breakpoints = self._cfg.get("product_breakpoints", [])
        for bp in breakpoints:
            if fxx > bp.get("above_fxx", float("inf")):
                return bp["fallback_product"]
        return base_product

    def _cache_dir(self):
        import os
        env_var = self._defaults.get("cache_dir_env_var", "BRC_TOOLS_HERBIE_CACHE")
        return os.environ.get(env_var) or None


def _parse_init_time(init_time) -> datetime.datetime:
    """Parse init_time from string or datetime.

    Returns a tz-naive datetime (Herbie assumes UTC internally and
    rejects tz-aware objects in its validation).
    """
    if isinstance(init_time, datetime.datetime):
        return init_time.replace(tzinfo=None)
    s = str(init_time).strip()
    # Strip timezone indicators — we always mean UTC
    for tz_str in ("Z", "z", " UTC", " utc"):
        s = s.replace(tz_str, "")
    s = s.strip()
    for fmt in (
        "%Y-%m-%d %H",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y%m%d%H",
        "%Y%m%d %H",
    ):
        try:
            return datetime.datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse init_time: {init_time!r}")

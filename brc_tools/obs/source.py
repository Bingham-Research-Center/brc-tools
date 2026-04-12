"""ObsSource: SynopticPy wrapper using the same alias namespace as NWPSource."""

import datetime
import logging

import numpy as np
import polars as pl

from brc_tools.nwp.source import load_lookups

logger = logging.getLogger(__name__)


class ObsSource:
    """Fetch station observations via SynopticPy with canonical alias names.

    Usage::

        obs = ObsSource()
        df = obs.timeseries(
            waypoint_group="foehn_path",
            start="2025-02-22 12Z",
            end="2025-02-23 06Z",
            variables=["temp_2m", "wind_speed_10m", "wind_dir_10m", "mslp"],
        )
    """

    def __init__(self):
        self._lu = load_lookups()

    def timeseries(
        self,
        *,
        stids: list[str] | None = None,
        waypoint_group: str | None = None,
        waypoints: list[str] | None = None,
        start,
        end,
        variables: list[str],
    ) -> pl.DataFrame:
        """Fetch time series from Synoptic stations, renamed to canonical aliases.

        Returns a Polars DataFrame with columns: stid, waypoint (if
        waypoints were used), valid_time, plus one column per alias.
        """
        from synoptic.services import TimeSeries

        stid_list, stid_to_wp = self._resolve_stids(stids, waypoint_group, waypoints)
        synoptic_vars = self._alias_to_synoptic_vars(variables)

        start_dt = _parse_time(start)
        end_dt = _parse_time(end)

        logger.info(
            "SynopticPy fetch: stids=%s vars=%s %s to %s",
            stid_list, synoptic_vars, start_dt, end_dt,
        )
        raw = TimeSeries(
            stid=stid_list,
            start=start_dt,
            end=end_dt,
            vars=synoptic_vars,
            verbose=False,
        ).df().synoptic.pivot()

        # Convert pandas → polars if needed
        if hasattr(raw, "to_pandas"):
            df = pl.from_pandas(raw.reset_index() if hasattr(raw, "reset_index") else raw)
        else:
            df = pl.from_pandas(raw.reset_index())

        # Rename Synoptic column names → canonical aliases
        rename_map = self._build_rename_map(variables, df.columns)
        df = df.rename(rename_map)

        # Normalize time column
        time_col = next((c for c in df.columns if "time" in c.lower() or "date" in c.lower()), None)
        if time_col and time_col != "valid_time":
            df = df.rename({time_col: "valid_time"})

        # Normalize station ID column
        stid_col = next((c for c in df.columns if c.lower() in ("stid", "station_id", "station")), None)
        if stid_col and stid_col != "stid":
            df = df.rename({stid_col: "stid"})

        # Add waypoint column if we can map stid → waypoint
        if stid_to_wp and "stid" in df.columns:
            df = df.with_columns(
                pl.col("stid").replace_strict(stid_to_wp, default=None).alias("waypoint")
            )

        return df

    def align_with_nwp(self, obs_df: pl.DataFrame, nwp_df: pl.DataFrame) -> pl.DataFrame:
        """Tag source and concatenate obs + NWP point DataFrames for plotting."""
        obs_tagged = obs_df.with_columns(pl.lit("obs").alias("source"))
        nwp_tagged = nwp_df.with_columns(pl.lit("nwp").alias("source"))
        # Find shared columns
        shared = sorted(set(obs_tagged.columns) & set(nwp_tagged.columns))
        return pl.concat(
            [obs_tagged.select(shared), nwp_tagged.select(shared)],
            how="vertical_relaxed",
        )

    # ── internal ────────────────────────────────────────────────────────

    def _resolve_stids(self, stids, waypoint_group, waypoints):
        """Return (stid_list, stid_to_waypoint_name_map)."""
        if stids is not None:
            return stids, {}
        wp_names = self._resolve_waypoints(waypoint_group, waypoints)
        all_wps = self._lu["waypoints"]
        stid_list = []
        stid_to_wp = {}
        for wp_name in wp_names:
            stid = all_wps[wp_name]["reference_stid"]
            stid_list.append(stid)
            stid_to_wp[stid] = wp_name
        return stid_list, stid_to_wp

    def _resolve_waypoints(self, group, waypoints):
        if waypoints is not None:
            return waypoints
        if group is not None:
            return self._lu["waypoint_groups"][group]
        raise ValueError("Provide stids=, waypoint_group=, or waypoints=")

    def _alias_to_synoptic_vars(self, variables):
        """Map canonical aliases to SynopticPy variable names."""
        aliases = self._lu["aliases"]
        synoptic_vars = set()
        for var_name in variables:
            alias = aliases.get(var_name)
            if alias is None:
                logger.warning("Unknown alias %r; skipping", var_name)
                continue
            if "synoptic_name" in alias:
                synoptic_vars.add(alias["synoptic_name"])
            elif "synoptic_derived_from" in alias:
                for sn in alias["synoptic_derived_from"]:
                    synoptic_vars.add(sn)
        return sorted(synoptic_vars)

    def _build_rename_map(self, variables, existing_columns):
        """Build a column rename mapping from Synoptic names → canonical aliases."""
        aliases = self._lu["aliases"]
        rename = {}
        for var_name in variables:
            alias = aliases.get(var_name, {})
            syn_name = alias.get("synoptic_name")
            output_var = alias.get("output_var", var_name)
            if syn_name and syn_name in existing_columns and syn_name != output_var:
                rename[syn_name] = output_var
        return rename


def _parse_time(t) -> datetime.datetime:
    if isinstance(t, datetime.datetime):
        return t
    s = str(t).strip().replace("Z", " UTC").replace("z", " UTC")
    for fmt in ("%Y-%m-%d %H %Z", "%Y-%m-%d %H:%M %Z", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M", "%Y-%m-%d %H"):
        try:
            dt = datetime.datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            return dt
        except ValueError:
            continue
    raise ValueError(f"Cannot parse time: {t!r}")

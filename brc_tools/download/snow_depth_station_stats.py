"""Discover all Uinta Basin stations reporting snow_depth and gather stats.

Outputs a summary table to console and saves CSV to data/snow_depth_station_stats.csv.
"""
import os
import datetime

import polars as pl
from synoptic.services import Metadata, Latest, TimeSeries


# Uinta Basin bounding box: west, south, east, north (Synoptic API format)
BBOX = "-111.5,39.5,-108.5,41.0"
VARIABLE = "snow_depth"

# How far back to check for "recent" activity
RECENT_DAYS = 30

# Period for data completeness assessment
COMPLETENESS_YEARS = 20


def discover_stations():
    """Query Synoptic Metadata API for stations with snow_depth in the Uinta Basin."""
    print("Querying metadata for snow_depth stations in the Uinta Basin...")
    df_meta = Metadata(bbox=BBOX, vars=VARIABLE, verbose=True).df()

    cols_available = df_meta.columns
    keep_cols = ["stid", "name", "latitude", "longitude", "elevation"]

    # Period of record columns may vary
    for candidate in ["period_of_record_start", "period_of_record_end",
                       "PERIOD_OF_RECORD.start", "PERIOD_OF_RECORD.end"]:
        if candidate in cols_available:
            keep_cols.append(candidate)

    # Network info
    for candidate in ["network", "mnet_shortname", "shortname"]:
        if candidate in cols_available:
            keep_cols.append(candidate)

    keep_cols = [c for c in keep_cols if c in cols_available]
    df_meta = df_meta.select(keep_cols).sort("stid")

    print(f"Found {df_meta.height} stations reporting {VARIABLE}")
    return df_meta


def check_recent_activity(stids):
    """Check which stations have reported snow_depth in the last RECENT_DAYS days."""
    print(f"\nChecking recent activity (last {RECENT_DAYS} days)...")
    stid_str = ",".join(stids)
    try:
        df_latest = Latest(
            stid=stid_str,
            vars=VARIABLE,
            within=datetime.timedelta(days=RECENT_DAYS),
            verbose=True,
        ).df()
    except Exception as e:
        print(f"  Warning: Latest query failed: {e}")
        return pl.DataFrame(schema={"stid": pl.Utf8, "last_ob_time": pl.Datetime})

    if df_latest.height == 0:
        print("  No recent observations found.")
        return pl.DataFrame(schema={"stid": pl.Utf8, "last_ob_time": pl.Datetime})

    # Get the most recent observation per station
    df_recent = (
        df_latest
        .filter(pl.col("variable") == VARIABLE)
        .sort(["stid", "date_time"], descending=[False, True])
        .unique(subset=["stid"], keep="first")
        .select(
            pl.col("stid"),
            pl.col("date_time").alias("last_ob_time"),
        )
    )
    print(f"  {df_recent.height} stations reported in the last {RECENT_DAYS} days")
    return df_recent


def assess_completeness(df_meta):
    """Pull TimeSeries in 2-year chunks, only querying stations active in each chunk.

    Uses period_of_record_start/end from metadata to skip stations with no data
    in a given time window.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    start = now - datetime.timedelta(days=365 * COMPLETENESS_YEARS)

    print(f"\nAssessing data completeness ({COMPLETENESS_YEARS}-year window)...")
    print(f"  Period: {start:%Y-%m-%d} to {now:%Y-%m-%d}")

    empty_schema = {
        "stid": pl.Utf8, "days_with_data": pl.UInt32,
        "total_days": pl.UInt32, "pct_complete": pl.Float64,
        "years_active": pl.Utf8,
    }

    # Build lookup of each station's period of record
    stids = df_meta.select("stid").to_series().to_list()
    por = {}
    for row in df_meta.select("stid", "period_of_record_start", "period_of_record_end").iter_rows(named=True):
        por[row["stid"]] = (row["period_of_record_start"], row["period_of_record_end"])

    # Query per-station in 1-year chunks to stay under station-hours limits.
    # The API caps total station-hours per request; 1 station × 1 year ≈ 8760 hrs is safe.
    chunk_days = 365
    all_dfs = []
    for idx, stid in enumerate(stids, 1):
        por_start, por_end = por.get(stid, (None, None))
        if por_start is None or por_end is None:
            continue
        # Clip to query window
        stn_start = max(por_start, start)
        stn_end = min(por_end, now)
        if stn_start >= stn_end:
            continue

        print(f"  [{idx}/{len(stids)}] {stid} ({stn_start:%Y-%m-%d} to {stn_end:%Y-%m-%d})")
        chunk_start = stn_start
        while chunk_start < stn_end:
            chunk_end = min(chunk_start + datetime.timedelta(days=chunk_days), stn_end)
            try:
                df_ts = TimeSeries(
                    stid=stid,
                    start=chunk_start,
                    end=chunk_end,
                    vars=VARIABLE,
                    verbose=False,
                ).df().synoptic.pivot()
                all_dfs.append(df_ts)
            except Exception as e:
                print(f"    Warning ({chunk_start:%Y-%m-%d}): {e}")
            chunk_start = chunk_end

    if not all_dfs:
        print("  No time series data returned.")
        return pl.DataFrame(schema=empty_schema)

    df_ts = pl.concat(all_dfs)

    # Calculate per-station stats
    results = []
    station_list = df_ts.select("stid").unique().to_series().to_list()
    for stid in sorted(station_list):
        df_stn = df_ts.filter(pl.col("stid") == stid).drop_nulls(subset=[VARIABLE])
        if df_stn.height == 0:
            results.append({
                "stid": stid, "days_with_data": 0,
                "total_days": 0, "pct_complete": 0.0,
                "years_active": "",
            })
            continue

        # Count unique days with at least one observation
        days_with_data = (
            df_stn.select(pl.col("date_time").dt.date().alias("day"))
            .unique()
            .height
        )

        # Which years have data
        years = (
            df_stn.select(pl.col("date_time").dt.year().alias("year"))
            .unique()
            .sort("year")
            .to_series()
            .to_list()
        )
        years_str = ",".join(str(y) for y in years)

        # Total days = station's period of record within the query window
        por_start, por_end = por[stid]
        effective_start = max(por_start, start)
        effective_end = min(por_end, now)
        total_days = max((effective_end - effective_start).days, 1)
        pct = round(100.0 * days_with_data / total_days, 1)

        results.append({
            "stid": stid,
            "days_with_data": days_with_data,
            "total_days": total_days,
            "pct_complete": pct,
            "years_active": years_str,
        })

    return pl.DataFrame(results)


def main():
    # 1. Discover stations
    df_meta = discover_stations()
    if df_meta.height == 0:
        print("No stations found. Exiting.")
        return

    stids = df_meta.select("stid").to_series().to_list()

    # 2. Check recent activity
    df_recent = check_recent_activity(stids)

    # 3. Assess completeness (needs period_of_record columns from metadata)
    df_complete = assess_completeness(df_meta)

    # 4. Join everything together
    df_result = df_meta.join(df_recent, on="stid", how="left")
    df_result = df_result.join(df_complete, on="stid", how="left")

    # Sort by completeness descending
    if "pct_complete" in df_result.columns:
        df_result = df_result.sort("pct_complete", descending=True)

    # Print summary
    print("\n" + "=" * 80)
    print("UINTA BASIN SNOW DEPTH STATION STATS")
    print("=" * 80)
    with pl.Config(tbl_cols=-1, tbl_rows=-1, tbl_width_chars=120):
        print(df_result)

    # Save CSV
    data_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data")
    os.makedirs(data_dir, exist_ok=True)
    csv_path = os.path.join(data_dir, "snow_depth_station_stats.csv")
    df_result.write_csv(csv_path)
    print(f"\nSaved to {os.path.abspath(csv_path)}")


if __name__ == "__main__":
    main()

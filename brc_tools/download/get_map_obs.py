#%%
import os
import sys
import datetime
import time
import pytz
import json
from pathlib import Path

import numpy as np
from scipy.signal import medfilt
import matplotlib.pyplot as plt
import polars as pl
import pandas as pd

from synoptic.services import Metadata, Latest, TimeSeries

from brc_tools.utils.lookups import obs_map_vrbls, obs_map_stids
from brc_tools.download.download_funcs import generate_json_fpath
from brc_tools.download.push_data import (clean_dataframe_for_json, save_json,
                                          send_json_to_all, load_config_urls)
from brc_tools.download.resend_gate import is_due, record_sent
from brc_tools.utils.util_funcs import get_current_datetime


# Station metadata is near-static: send it when it changes, and otherwise at the first
# 5-minute run after 5 h 45 min, so a copy lands inside the 6 h the website's manifest
# declares for `metadata` even when a run or two is late.
METADATA_MAX_AGE_SECONDS = 6 * 3600 - 15 * 60

if __name__ == "__main__":
    # Runtime output stays out of the repo checkout: the website holds the live
    # copy, so local snapshots are a rolling cache, not a record.
    data_root = os.path.expanduser("~/.cache/brc-tools/map_obs")
    os.makedirs(data_root, exist_ok=True)

    # Without pruning this grows ~4.4 GB/yr at the 5-min cron cadence.
    cutoff = time.time() - 90 * 86400
    for old in Path(data_root).glob("map_obs*.json"):
        if old.stat().st_mtime < cutoff:
            old.unlink(missing_ok=True)

    map_datetime = get_current_datetime()

    print("Downloading metadata...")
    df_meta = Metadata(stid=obs_map_stids, verbose=True,
                       ).df()

    # Keep stid, name, elevation, latitude, longitude only
    df_meta = df_meta.select(
        pl.col("stid"),
        pl.col("name"),
        pl.col("elevation"),
        pl.col("latitude"),
        pl.col("longitude")
    ).sort("stid")

    meta_fpath = generate_json_fpath(data_root,
                                    prefix="map_obs_meta", t=map_datetime,)
    save_json(df_meta, meta_fpath)
    meta_state = os.path.join(data_root, "metadata_last_sent.json")
    send_meta = is_due(meta_fpath, meta_state,
                       max_age_seconds=METADATA_MAX_AGE_SECONDS)
    if not send_meta:
        # Unchanged and sent recently: do not keep or upload another identical copy.
        os.remove(meta_fpath)
        print("Station metadata unchanged since the last send; not uploading it.")



    # TODO - move this to where we get time series rather than map obs
    # print("Downloading time series data...")
    # df_data = synoptic.TimeSeries(stid=obs_map_stids, start=start_date, end=end_date,
    #                                 vars=obs_map_vrbls, verbose=True,
    #                                 ).df().synoptic.pivot()

    print("Downloading latest observations...")
    latest_obs = Latest(stid=obs_map_stids, vars=obs_map_vrbls, verbose=True,
                                 within=datetime.timedelta(hours=25), # 1 hour
                                ).df()

    # Check for rows with identical stid and variable; keep only most recent.
    latest_obs = latest_obs.sort(["stid", "variable", "date_time"],
                                 descending=[False, False, True])
    latest_obs = latest_obs.unique(subset=["stid", "variable"], keep="first")

    # we only want stid, variable, value, date_time, units
    latest_obs = latest_obs.select(
        pl.col("stid"),
        pl.col("variable"),
        pl.col("value"),
        pl.col("date_time"),
        pl.col("units")
    )

    latest_obs = latest_obs.with_columns(
        pl.col("date_time").dt.convert_time_zone("UTC")
    ).sort(["stid", "date_time"], descending=[False, True])

    map_fpath = generate_json_fpath(data_root,
                                   prefix="map_obs", t=map_datetime,)
    clean_df = clean_dataframe_for_json(latest_obs)
    save_json(clean_df, map_fpath)

    send_json = True
    if send_json:
        API_KEY, server_urls = load_config_urls()
        print(f"Using API key {API_KEY[:5]}... and {len(server_urls)} URL(s): "
              f"primary={server_urls[0]}"
              + (f", mirrors={server_urls[1:]}" if len(server_urls) > 1 else ""))

        uploads = [(map_fpath, "observations")]
        if send_meta:
            # Metadata first, so a new station is described before its first reading.
            uploads.insert(0, (meta_fpath, "metadata"))

        # One failed upload no longer stops the other: a primary failure on metadata
        # used to raise here and skip that run's observations too. Every failure is
        # still printed and still makes the job exit non-zero, as before.
        failed = []
        for f, data_type in uploads:
            try:
                results = send_json_to_all(server_urls, f, data_type, API_KEY)
            except RuntimeError as exc:
                print(f"ERROR {data_type} upload failed: {exc}", file=sys.stderr)
                failed.append(data_type)
                continue
            if data_type == "metadata" and all(results.values()):
                # Only once every host has it: a mirror that missed it gets it next run.
                record_sent(f, meta_state)

        if failed:
            sys.exit(f"Primary upload failed for: {', '.join(failed)}")

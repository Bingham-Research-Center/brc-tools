#%%
import os
import sys
import datetime
import pytz
import json

import numpy as np
from scipy.signal import medfilt
import matplotlib.pyplot as plt
import polars as pl
import pandas as pd

from synoptic.services import Metadata, Latest, TimeSeries

from brc_tools.utils.lookups import obs_map_vrbls, obs_map_stids
from brc_tools.download.download_funcs import generate_json_fpath
from brc_tools.download.push_data import (clean_dataframe_for_json, save_json,
                                          send_json_to_server, load_config)
from brc_tools.utils.util_funcs import get_current_datetime


if __name__ == "__main__":
    # Save to scratch or temp directory (works from any cwd)
    data_root = os.path.expanduser("~/gits/brc-tools/data")
    os.makedirs(data_root, exist_ok=True)
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

    # TODO - eventually, also send metadata to the website



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

    # This is where I want to send json to the website server
    send_json = True
    if send_json:
        # tempdir = os.environ.get('TMP_DIR')
        API_KEY, server_url = load_config()
        print(f"Using API key {API_KEY[:5]}... and server URL starting"
              f" {server_url[:10]}")

        for f, data_type in (
                (meta_fpath, "metadata"), (map_fpath, "observations")):
            send_json_to_server(server_url, f, data_type, API_KEY)

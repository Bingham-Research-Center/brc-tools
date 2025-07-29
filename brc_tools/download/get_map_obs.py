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

import synoptic

from brc_tools.utils.lookups import obs_map_vrbls, obs_map_stids
from brc_tools.download.download_funcs import generate_json_fpath
from brc_tools.download.push_data import (clean_dataframe_for_json, save_json,
                                          send_json_to_server, load_config)

# JRL: if problems, delete your existing config toml file
# then create new one by uncommenting:
# synoptic.configure(token="blah")

# Use Helvetica or Arial for plots
plt.rcParams['font.family'] = 'Helvetica'
plt.rcParams['font.sans-serif'] = 'Helvetica'
plt.rcParams['font.size'] = 12


if __name__ == "__main__":
    # Are we saving the dataframe to fisc first before exporting to json?
    data_root = "../data"

    start_date = datetime.datetime(2025, 1, 24, 0, 0, 0)
    end_date = datetime.datetime(2025, 2, 4, 0, 0, 0)
    # end_date = datetime.datetime(2025, 3, 16, 0, 0, 0)

    # df_meta = load_pickle(df_meta_fpath)
    # df_obs = pd.read_hdf(df_obs_fpath, key='df_obs')
    # df_obs_winter = df_obs[df_obs.index.month.isin([11, 12, 1, 2, 3])]

    # Download the data.
    print("Downloading metadata...")
    # synoptic_vrbls =
        # [value['synoptic'] for value in _VRBLS.values()]

    df_meta = synoptic.Metadata(stid=obs_map_stids, verbose=True).df()

    # TODO - eventually, also send metadata to the website

    # TODO - move this to where we get time series rather than map obs
    # print("Downloading time series data...")
    # df_data = synoptic.TimeSeries(stid=obs_map_stids, start=start_date, end=end_date,
    #                                 vars=obs_map_vrbls, verbose=True,
    #                                 ).df().synoptic.pivot()

    print("Downloading latest observations...")
    latest_obs = synoptic.Latest(stid=obs_map_stids, vars=obs_map_vrbls, verbose=True,
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
                                   prefix="map_obs", t=end_date)
    clean_df = clean_dataframe_for_json(latest_obs)
    save_json(clean_df, map_fpath)

    # This is where I want to send json to the website server
    tempdir = os.environ.get('TMP_DIR')
    API_KEY, server_url = load_config()
    print(f"Using API key {API_KEY[:5]}... and server URL starting"
          f" {server_url[:10]}")
    send_json_to_server(server_url, map_fpath,
                        "map-obs", API_KEY)

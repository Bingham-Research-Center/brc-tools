"""Functions for fetching/sending data to website server for graphics"""
import os
import datetime
import socket

import pytz

import numpy as np
import pandas as pd
import requests
import synoptic


def compute_start_time(valid_time, history_hours):
    begin_time = valid_time - datetime.timedelta(hours=history_hours)
    return begin_time


def download_obs_metadata(stids):
    df_meta = synoptic.Metadata(stid=stids, verbose=True).df()
    return df_meta


def download_obs_timeseries(stids, start_time, valid_time, vrbls):
    df_data = synoptic.TimeSeries(stid=stids,start=start_time, end=valid_time,
                                  vars=vrbls, verbose=True,
                                  ).df().synoptic.pivot()
    return df_data


def generate_json_fpath(data_root, prefix, t):
    """Generate a file path for json export.

    Args:
        data_root (str): The root directory where the file will be saved.
        prefix (str): Prefix for the file name.
        t (datetime): The time to include in the file nam    Returns:
        str: The full file path for the JSON file. Convention
            we use for data is YYYYMMDD_HHMMZ (seconds don't matter).
    """
    fpath = os.path.join(data_root,
                         f"{prefix}_{t.strftime('%Y%m%d_%H%M')}Z.json")
    return fpath



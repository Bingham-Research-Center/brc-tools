"""Functions for fetching/sending data for UBAIR website graphics"""
import os
import datetime
import pytz

import numpy as np
import pandas as pd
import requests
import synoptic

from utils.lookups import map_stids, map_vrbls

def download_map_obs(valid_time: datetime.datetime, history_hours=25,
                        tempdir="../data/obs",):
    """Download observations from Synoptic Weather for the UBAIR map.

    Args:
        valid_time (datetime): The time (UTC) to download observations for.
        history_hours (int): Number of hours of obs to download.
        tempdir (str): Directory to save the downloaded files.
            Default is "../data/obs". Not using it here yet.
    """
    begin_time = valid_time - datetime.timedelta(hours=history_hours)

    df_meta = synoptic.Metadata(stid=map_stids, verbose=True).df()
    df_data = synoptic.TimeSeries(stid=map_stids,start=begin_time, end=valid_time,
                                  vars=map_vrbls, verbose=True,
                                  # rename_set_1=False, rename_value_1=False
                                  ).df().synoptic.pivot()

    return df_data, df_meta

def clean_dataframe_for_json(df):
    # If the dataframe is a Polars dataframe, convert it to Pandas.
    if hasattr(df, "to_pandas"):
        df = df.to_pandas()

    # Replace NaN with None to become proper JSON null.
    df = df.where(pd.notnull(df), None)

    # Clean string columns (remove unnecessary quotes).
    for col in df.select_dtypes(include=['object']):
        df[col] = df[col].str.strip('"')

    return df

def save_json(df, fpath, orient='records'):
    if hasattr(df, "to_pandas"):
        df = df.to_pandas()

    # Pandas will map NaN → null automatically
    df.to_json(fpath, orient=orient, indent=2, date_format="iso")
    print(f"Exported {len(df)} records to {fpath}")
    return

def get_map_json(valid_time: datetime.datetime, history_hours=48,
                    tempdir="../data/obs",):
    """Get obs from Synoptic Weather for the UBAIR map in json format.

    Args:
        valid_time (datetime): The time (UTC) to download observations for.
        history_hours (int): Number of hours of obs to download.
        tempdir (str): Directory to save the downloaded files (json).
            Default is "../data/obs".
    """
    def create_map_fnames(t):
        """Create file names for the map obs based on the valid time."""
        # Format time t as a string "YYYYMMDD_HHMM" and add UTC reminder
        time_str = t.strftime("%Y%m%d_%H%M") + "-Z"

        fname_data = f"map_obs_{time_str}.json"
        fname_meta = f"map_meta_{time_str}.json"

        return fname_data, fname_meta

    df_data, df_meta = download_map_obs(valid_time, history_hours, tempdir)

    # If direectory doesn't exist, create it.
    if not os.path.exists(tempdir):
        os.makedirs(tempdir)

    # Create file paths based on the valid_time
    fname_data, fname_meta = create_map_fnames(valid_time)

    # Save the data to JSON files
    save_json(df_data, os.path.join(tempdir, fname_data))
    save_json(df_meta, os.path.join(tempdir, fname_meta))
    return fname_data, fname_meta

def send_json_to_server(server_address, fpath, file_data, API_KEY):
    endpoint = f"{server_address}/api/data/upload/{file_data}"

    # Prepare upload file
    with open(fpath, 'rb') as f:
        files = {'file': (os.path.basename(fpath), f, 'application/json')}

        # Add authentication
        headers = {'X-API-Key': API_KEY}

        # Send the file
        response = requests.post(
            endpoint,
            files=files,
            headers=headers
        )

    if response.status_code == 200:
        print(f"Successfully uploaded {os.path.basename(fpath)} to {endpoint}")
    else:
        print(f"Failed to upload {os.path.basename(fpath)}: {response.text}")

def load_config():
    """Load API key and website URL from file."""
    # TODO - what is "weather-website"?
    config_dir = os.path.join(os.path.expanduser('~'), '.config',
                                    'ubair-website')

    api_key_file = os.path.join(config_dir, 'api_key')
    if not os.path.exists(api_key_file):
        raise FileNotFoundError(f"API key file not found at {api_key_file}. "
                                f"Check docs for setup.")

    with open(api_key_file, 'r') as f:
        api_key = f.read().strip()

    # Read website URL
    url_file = os.path.join(config_dir, 'website_url')
    if not os.path.exists(url_file):
        raise FileNotFoundError("Website URL file not found. Check docs for setup.")

    with open(url_file, 'r') as f:
        website_url = f.read().strip()

    return api_key, website_url

if __name__ == "__main__":
    # Run typical usage of rounding the time now (UTC) to most recent minute.
    now_dt = datetime.datetime.now(tz=pytz.timezone("UTC"))
    now_dt = now_dt.replace(minute=int(np.floor(now_dt.minute / 5) * 5),
                        second=0, microsecond=0)
    print(f"Getting map obs for {now_dt} UTC")
    fname_data, fname_meta = get_map_json(now_dt)

    # Send the files to the UBAIR website
    server_url, API_KEY = load_config()
    send_json_to_server(server_url, os.path.join("../data/obs", fname_data),
                        "map-obs", API_KEY)
    send_json_to_server(server_url, os.path.join("../data/obs", fname_meta),
                        "map-meta", API_KEY)
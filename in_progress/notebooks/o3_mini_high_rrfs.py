#!/usr/bin/env python3
import os
import requests

def construct_rrfs_url(date: str, run_hour: str, forecast_hour: int, coord_mode: str = 'natlev') -> tuple[str, str]:
    """
    Construct the download URL and filename for an RRFS GRIB2 file.

    Parameters:
        date (str): The model run date in YYYYMMDD format.
        run_hour (str): The run hour in two-digit format.
        forecast_hour (int): The forecast hour.
        coord_mode (str, optional): The coordinate specification. Defaults to 'natlev'.

    Returns:
        tuple[str, str]: A tuple containing the URL and filename.
    """
    base_url = "https://noaa-gsl-experimental-pds.s3.amazonaws.com/rrfs_b_deterministic"
    filename = f"rrfs.t{run_hour}z.{coord_mode}.f{forecast_hour:03d}.grib2"
    url = f"{base_url}/{date}/{run_hour}/{filename}"
    return url, filename


def download_rrfs_file(date: str, run_hour: str, forecast_hour: int, coord_mode: str = 'natlev', output_dir = "./") -> str:
    r"""
    Download a RRFS GRIB2 file from the NOAA S3 bucket.

    The function constructs the download URL based on the provided parameters.
    The file naming convention is as follows:

    \[
    \texttt{rrfs.t\{run\_hour\}z.\{coord\_mode\}.f\{forecast\_hour:03d\}.grib2}
    \]

    Parameters
    ----------
    date : str
        The model run date in YYYYMMDD format (e.g. "20250131").
    run_hour : str
        The run hour in two-digit format (e.g. "00" for 00Z).
    forecast_hour : int
        The forecast hour (e.g. 12 for forecast hour 12).
    coord_mode : str, optional
        The coordinate specification, either 'natlev' (natural coordinates) or another value
        such as 'prslev'. Default is 'natlev'.

    Returns
    -------
    str
        The local path to the downloaded file. If an error occurs, the function returns None.
    """
    # Define the base URL for the S3 bucket and construct the filename
    url, filename = construct_rrfs_url(date, run_hour, forecast_hour, coord_mode)
    # Put temporary data in the tmp directory under root.
    tmp_dir = output_dir

    # Provide some logging information

    # Define the local file path (current working directory)
    local_filepath = os.path.join(tmp_dir, filename)
    print(f"Downloading file from: {url} and trying to save to {local_filepath}")

    try:
        # Send the GET request in stream mode to handle large files efficiently.
        response = requests.get(url, stream=True)
        response.raise_for_status()  # Raise an exception if the download fails

        # Open a local file handle and write the data in chunks.
        with open(local_filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:  # Filter out keep-alive chunks
                    f.write(chunk)

        print(f"Download completed: {local_filepath}")
    except requests.exceptions.RequestException as e:
        print(f"Error occurred during download: {e}")
        local_filepath = None

    return local_filepath

if __name__ == "__main__":
    # The following parameters specify:
    # - Date: January 31, 2025 (formatted as YYYYMMDD)
    # - Run hour: "00" (i.e., 00Z run)
    # - Forecast hour: 12, which corresponds to f012 in the filename.
    # - Coordinates: Natural level ("natlev")
    date = "20250131"
    run_hour = "00"
    forecast_hour = 12
    coord_mode = "natlev"

    # Call the download function with the specified parameters.
    downloaded_file = download_rrfs_file(date, run_hour, forecast_hour, coord_mode)

    if downloaded_file:
        print(f"File successfully downloaded: {downloaded_file}")
    else:
        print("Download failed.")
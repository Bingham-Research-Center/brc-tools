"""Download NWP model data (GEFS, HRRR, etc.) using Herbie.

Standardized download interface for operational forecasting and research.
Saves to Zarr format for fast access and web delivery.

Author: JRL, 2025-10-26
"""

import datetime
import logging
from pathlib import Path
from typing import Optional, Union, Literal
import warnings

import xarray as xr
import numpy as np

try:
    from herbie import Herbie
    HERBIE_AVAILABLE = True
except ImportError:
    HERBIE_AVAILABLE = False
    warnings.warn("Herbie not available - install with: pip install herbie-data")


# Setup logging
logger = logging.getLogger(__name__)


def download_gefs_ensemble(
    init_time: datetime.datetime,
    forecast_hours: Union[list[int], range] = range(0, 384, 6),
    members: Union[list[int], Literal['all', 'control']] = 'all',
    variables: Optional[list[str]] = None,
    save_dir: Union[str, Path] = '/scratch/general/lustre',
    save_format: Literal['zarr', 'netcdf'] = 'zarr',
    overwrite: bool = False,
    subset_bbox: Optional[tuple[float, float, float, float]] = None
) -> Path:
    """Download GEFS ensemble data using Herbie and save in standardized format.

    Designed for operational use on CHPC or research workflows. Downloads
    all requested members/times and saves to efficient Zarr or NetCDF format.

    Args:
        init_time: Model initialization time (UTC)
        forecast_hours: Forecast lead times to download (hours)
            Default: 0-384h (16 days) every 6 hours for clyfar
        members: Which ensemble members to download:
            - 'all': Control (c00) + 30 perturbations (p01-p30)
            - 'control': Control member only
            - list of ints: Specific members (0=control, 1-30=perturbations)
        variables: Herbie search strings for variables to download
            Default: ['TMP:2 m', 'UGRD:10 m', 'VGRD:10 m', 'SNOD', 'DSWRF']
            (temp, u-wind, v-wind, snow depth, solar radiation - for clyfar)
        save_dir: Directory to save downloaded data
            Default: CHPC scratch space (update to your u-number)
        save_format: Output format ('zarr' recommended for speed, 'netcdf' for compatibility)
        overwrite: If False, skip download if file already exists
        subset_bbox: Optional spatial subset (south, north, west, east) in degrees
            Example: (39.4, 41.1, -110.9, -108.5) for Uinta Basin

    Returns:
        Path to saved data file

    Example:
        >>> # Download for clyfar operations
        >>> data_path = download_gefs_ensemble(
        ...     init_time=datetime.datetime(2025, 10, 26, 0),
        ...     members='all',
        ...     subset_bbox=(39.4, 41.1, -110.9, -108.5)
        ... )
        >>> print(f"Saved to: {data_path}")

        >>> # Quick test with fewer members
        >>> data_path = download_gefs_ensemble(
        ...     init_time=datetime.datetime(2025, 10, 26, 0),
        ...     members=[0, 1, 2],  # Control + 2 perturbations
        ...     forecast_hours=range(0, 48, 6)  # Just 2 days
        ... )

    Raises:
        ImportError: If Herbie not installed
        ValueError: If invalid parameters
        RuntimeError: If download fails

    Note:
        Downloads can be slow (~5-10 min for full GEFS ensemble).
        Use subset_bbox to reduce data size for regional applications.
    """
    if not HERBIE_AVAILABLE:
        raise ImportError("Herbie required. Install: pip install herbie-data")

    # Setup paths
    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    # Generate filename
    init_str = init_time.strftime('%Y%m%d_%H%M')
    if save_format == 'zarr':
        save_path = save_dir / f"gefs_{init_str}.zarr"
    else:
        save_path = save_dir / f"gefs_{init_str}.nc"

    # Check if already exists
    if save_path.exists() and not overwrite:
        logger.info(f"Data already exists: {save_path}")
        return save_path

    # Determine member list
    if members == 'all':
        member_list = [0] + list(range(1, 31))
        logger.info("Downloading all 31 members (c00 + p01-p30)")
    elif members == 'control':
        member_list = [0]
        logger.info("Downloading control member only")
    else:
        member_list = members
        logger.info(f"Downloading {len(member_list)} members: {member_list}")

    # Default variables for clyfar
    if variables is None:
        variables = [
            'TMP:2 m',           # 2-m temperature
            'UGRD:10 m',         # 10-m u-wind
            'VGRD:10 m',         # 10-m v-wind
            'SNOD:surface',      # Snow depth
            'DSWRF:surface',     # Downward shortwave radiation
        ]

    logger.info(f"Variables: {variables}")
    logger.info(f"Forecast hours: {list(forecast_hours)[:3]}...{list(forecast_hours)[-1]}")

    # Download data
    member_datasets = []
    n_total = len(member_list) * len(list(forecast_hours))
    n_done = 0

    for member_num in member_list:
        member_name = 'c00' if member_num == 0 else f'p{member_num:02d}'
        logger.info(f"Downloading member {member_name}...")

        time_datasets = []
        for fhr in forecast_hours:
            try:
                # Create Herbie object
                H = Herbie(
                    init_time,
                    model='gefs',
                    member=member_num,
                    fxx=fhr,
                )

                # Download all variables
                # Herbie can take regex: use '|' to combine patterns
                var_pattern = '|'.join(f'({v})' for v in variables)
                ds_time = H.xarray(var_pattern, remove_grib=True)

                # Apply spatial subset if requested
                if subset_bbox is not None:
                    south, north, west, east = subset_bbox
                    # Handle longitude wrapping (GEFS uses 0-360)
                    if west < 0:
                        west += 360
                    if east < 0:
                        east += 360

                    # Subset using nearest neighbor for now
                    # TODO: Could add proper bbox masking
                    ds_time = ds_time.sel(
                        latitude=slice(south, north),
                        longitude=slice(west, east)
                    )

                time_datasets.append(ds_time)

                n_done += 1
                if n_done % 10 == 0:
                    logger.info(f"Progress: {n_done}/{n_total} files downloaded")

            except Exception as e:
                logger.error(f"Failed to download {member_name} F{fhr:03d}: {e}")
                # Continue with other times rather than failing completely
                continue

        if not time_datasets:
            logger.warning(f"No data downloaded for member {member_name}, skipping")
            continue

        # Concatenate times for this member
        ds_member = xr.concat(time_datasets, dim='time')

        # Add member coordinate
        ds_member = ds_member.assign_coords(member=member_name)

        member_datasets.append(ds_member)

    if not member_datasets:
        raise RuntimeError("No data successfully downloaded")

    logger.info("Combining all members...")

    # Concatenate all members
    ds = xr.concat(member_datasets, dim='member')

    # Add metadata
    ds.attrs['init_time'] = init_time.isoformat()
    ds.attrs['download_time'] = datetime.datetime.utcnow().isoformat()
    ds.attrs['model'] = 'GEFS'
    ds.attrs['source'] = 'NOAA via Herbie'

    # Compute derived variables
    if 'UGRD:10 m' in variables and 'VGRD:10 m' in variables:
        logger.info("Computing wind speed and direction...")
        # Get variable names (Herbie names may vary)
        u_var = [v for v in ds.data_vars if 'u10' in v.lower() or 'ugrd' in v.lower()]
        v_var = [v for v in ds.data_vars if 'v10' in v.lower() or 'vgrd' in v.lower()]

        if u_var and v_var:
            u = ds[u_var[0]]
            v = ds[v_var[0]]

            # Wind speed
            ds['wind_speed_10m'] = np.sqrt(u**2 + v**2)
            ds['wind_speed_10m'].attrs['long_name'] = '10-meter wind speed'
            ds['wind_speed_10m'].attrs['units'] = 'm/s'

            # Wind direction (meteorological convention: direction FROM)
            wdir = (180 / np.pi) * np.arctan2(-u, -v)
            wdir = (wdir + 360) % 360  # Ensure 0-360
            ds['wind_dir_10m'] = wdir
            ds['wind_dir_10m'].attrs['long_name'] = '10-meter wind direction'
            ds['wind_dir_10m'].attrs['units'] = 'degrees'

    # Save to disk
    logger.info(f"Saving to {save_path}...")

    if save_format == 'zarr':
        # Zarr is faster and web-friendly
        ds.to_zarr(save_path, mode='w')
    else:
        # NetCDF for compatibility
        ds.to_netcdf(save_path)

    logger.info(f"Download complete: {save_path}")
    logger.info(f"Data shape: {dict(ds.dims)}")
    logger.info(f"Variables: {list(ds.data_vars)}")

    return save_path


def download_hrrr(
    valid_time: datetime.datetime,
    forecast_hour: int = 0,
    variables: Optional[list[str]] = None,
    save_dir: Union[str, Path] = '/scratch/general/lustre',
    product: Literal['sfc', 'prs', 'nat', 'subh'] = 'nat',
    subset_bbox: Optional[tuple[float, float, float, float]] = None
) -> Path:
    """Download HRRR data for a single valid time.

    Simpler interface than GEFS since HRRR is deterministic (no ensemble).

    Args:
        valid_time: Valid time for the forecast
        forecast_hour: Forecast lead time (0 for analysis)
        variables: Variables to download (same format as GEFS)
        save_dir: Where to save data
        product: HRRR product type ('nat' = native levels, 'sfc' = surface)
        subset_bbox: Spatial subset (south, north, west, east)

    Returns:
        Path to saved NetCDF file

    Example:
        >>> # Download HRRR analysis for current conditions
        >>> path = download_hrrr(
        ...     valid_time=datetime.datetime.utcnow(),
        ...     forecast_hour=0,
        ...     subset_bbox=(39.4, 41.1, -110.9, -108.5)
        ... )
    """
    if not HERBIE_AVAILABLE:
        raise ImportError("Herbie required. Install: pip install herbie-data")

    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    # Calculate init time
    init_time = valid_time - datetime.timedelta(hours=forecast_hour)

    # Generate filename
    valid_str = valid_time.strftime('%Y%m%d_%H%M')
    save_path = save_dir / f"hrrr_{valid_str}_f{forecast_hour:02d}.nc"

    if save_path.exists():
        logger.info(f"HRRR data already exists: {save_path}")
        return save_path

    # Default variables
    if variables is None:
        variables = ['TMP:2 m', 'UGRD:10 m', 'VGRD:10 m']

    logger.info(f"Downloading HRRR for {valid_time} (F{forecast_hour:02d})")

    # Create Herbie object
    H = Herbie(init_time, model='hrrr', product=product, fxx=forecast_hour)

    # Download
    var_pattern = '|'.join(f'({v})' for v in variables)
    ds = H.xarray(var_pattern, remove_grib=True)

    # Apply subset
    if subset_bbox is not None:
        south, north, west, east = subset_bbox
        # HRRR uses negative longitudes
        ds = ds.sel(
            latitude=slice(south, north),
            longitude=slice(west, east)
        )

    # Save
    ds.to_netcdf(save_path)
    logger.info(f"HRRR saved to: {save_path}")

    return save_path


def get_latest_gefs_init() -> datetime.datetime:
    """Get the most recent available GEFS initialization time.

    GEFS runs 4x/day at 00, 06, 12, 18 UTC.
    Returns the most recent cycle that should be available.

    Returns:
        datetime.datetime: Latest GEFS init time (UTC)

    Note:
        GEFS typically has a 3-4 hour delay from init to availability.
        This function accounts for that delay.
    """
    now = datetime.datetime.utcnow()

    # GEFS cycles
    cycles = [0, 6, 12, 18]

    # Account for ~4 hour processing delay
    available_time = now - datetime.timedelta(hours=4)

    # Find most recent cycle
    cycle_hour = max([c for c in cycles if c <= available_time.hour])

    latest_init = available_time.replace(
        hour=cycle_hour,
        minute=0,
        second=0,
        microsecond=0
    )

    return latest_init


# Convenience function for operational use
def download_latest_gefs_for_clyfar(
    save_dir: Union[str, Path] = '/scratch/general/lustre',
    **kwargs
) -> Path:
    """Download latest GEFS with clyfar-specific settings.

    Convenience wrapper for operational clyfar runs.

    Args:
        save_dir: Where to save data
        **kwargs: Additional arguments to pass to download_gefs_ensemble()

    Returns:
        Path to downloaded data
    """
    init_time = get_latest_gefs_init()

    logger.info(f"Downloading GEFS for clyfar operations")
    logger.info(f"Init time: {init_time}")

    # Clyfar defaults
    clyfar_defaults = {
        'forecast_hours': range(0, 384, 6),  # 15 days
        'members': 'all',
        'variables': [
            'TMP:2 m',
            'UGRD:10 m',
            'VGRD:10 m',
            'SNOD:surface',
            'DSWRF:surface'
        ],
        'subset_bbox': (39.0, 41.5, -111.5, -108.0),  # Uinta Basin + buffer
    }

    # Merge with user kwargs (user kwargs take precedence)
    download_kwargs = {**clyfar_defaults, **kwargs}

    return download_gefs_ensemble(
        init_time=init_time,
        save_dir=save_dir,
        **download_kwargs
    )


if __name__ == '__main__':
    # Test/demo mode
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    print("Testing GEFS download...")
    print("This will download a small subset for testing")

    # Test with recent date, few members, short forecast
    test_init = datetime.datetime(2025, 10, 26, 0)

    try:
        save_path = download_gefs_ensemble(
            init_time=test_init,
            members=[0, 1],  # Just control + 1 perturbation
            forecast_hours=range(0, 24, 6),  # Just 1 day
            subset_bbox=(39.4, 41.1, -110.9, -108.5),  # Uinta Basin
            save_dir='./test_data'
        )
        print(f"\n✓ Success! Data saved to: {save_path}")
        print("\nTo load this data:")
        print(f"  import xarray as xr")
        print(f"  ds = xr.open_zarr('{save_path}')")

    except Exception as e:
        print(f"\n✗ Download failed: {e}")
        sys.exit(1)

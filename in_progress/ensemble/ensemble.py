"""Modern ensemble forecast class using xarray.

Salvaged concepts from evac (2018) and modernized with xarray, Herbie, and type hints.

Design philosophy:
- xarray.Dataset as core container (not numpy arrays)
- Lazy loading via dask for large ensembles
- CF-compliant metadata
- Support for lagged and mixed-model ensembles
- Probabilistic analysis methods
- JSON serialization for web APIs

Author: Salvaged from evac by JRL, modernized 2025
"""

import datetime
from typing import Literal, Optional, Union
from pathlib import Path
import warnings

import numpy as np
import xarray as xr

import herbie
from herbie import Herbie


class Ensemble:
    """Manage and analyze NWP ensemble forecasts.

    Core container is xarray.Dataset with dimensions:
        - member: Ensemble member names (e.g., 'ctrl', 'p01', 'p02')
        - time: Valid forecast times
        - lat: Latitude
        - lon: Longitude
        - level: Vertical level (optional, if 3D data)

    Examples:
        # Load GEFS ensemble
        >>> ens = Ensemble.from_gefs(
        ...     init_time=datetime.datetime(2025, 10, 26, 0),
        ...     members=range(1, 6),
        ...     forecast_hours=range(0, 24, 6)
        ... )

        # Compute exceedance probability
        >>> prob = ens.get_exceedance_prob('t2m', threshold=273.15, operator='>')

        # Export to JSON for web
        >>> json_data = ens.to_timeseries_json('t2m', location=(40.5, -110.0))
    """

    def __init__(
        self,
        ds: xr.Dataset,
        lazy: bool = True,
        validate: bool = True
    ):
        """Initialize Ensemble from xarray Dataset.

        Args:
            ds: xarray.Dataset with at least 'member' dimension
            lazy: If True, use dask for lazy evaluation (default: True)
            validate: If True, check CF conventions and required coords

        Raises:
            ValueError: If ds missing required dimensions or invalid structure
        """
        if validate:
            self._validate_dataset(ds)

        self.ds = ds

        # Setup lazy loading if requested
        if lazy and not self._is_dask_backed(ds):
            self.ds = self._setup_chunking(ds)
        elif not lazy and self._is_dask_backed(ds):
            self.ds = ds.compute()

    @staticmethod
    def _validate_dataset(ds: xr.Dataset) -> None:
        """Validate dataset structure."""
        required_dims = {'member', 'time'}
        missing = required_dims - set(ds.dims)
        if missing:
            raise ValueError(f"Dataset missing required dimensions: {missing}")

        # Check for at least one data variable
        if not ds.data_vars:
            raise ValueError("Dataset has no data variables")

    @staticmethod
    def _is_dask_backed(ds: xr.Dataset) -> bool:
        """Check if dataset uses dask arrays."""
        return any(
            hasattr(var.data, 'chunks')
            for var in ds.data_vars.values()
        )

    @staticmethod
    def _setup_chunking(ds: xr.Dataset) -> xr.Dataset:
        """Setup optimal chunking strategy.

        Strategy:
        - Chunk by member (enables parallel processing across members)
        - Keep time/space contiguous for efficient operations
        """
        n_members = len(ds.member)

        if n_members < 10:
            # Small ensemble - load into memory
            return ds
        else:
            # Large ensemble - chunk by member
            return ds.chunk({'member': 1, 'time': -1})

    @classmethod
    def from_gefs(
        cls,
        init_time: datetime.datetime,
        members: Union[list[int], Literal['all', 'control']] = 'all',
        forecast_hours: Union[list[int], range] = range(0, 48, 6),
        variables: Optional[list[str]] = None,
        **herbie_kwargs
    ):
        """Load GEFS ensemble using Herbie.

        Args:
            init_time: Model initialization time
            members: Which members to load:
                - 'all': All 30 perturbations + control
                - 'control': Control member only
                - list of ints: Specific member numbers (1-30)
            forecast_hours: Forecast lead times to load (hours)
            variables: Variables to load (Herbie search strings)
                Examples: ['TMP:2 m', 'UGRD:10 m', 'VGRD:10 m']
            **herbie_kwargs: Additional arguments to pass to Herbie

        Returns:
            Ensemble instance with loaded GEFS data

        Raises:
            ImportError: If Herbie not installed
            ValueError: If invalid member specification

        Note:
            This method loops over members and times - may be slow for large requests.
            Consider caching or using Herbie's built-in features if available.
        """
        # Determine member list
        if members == 'all':
            member_list = [0] + list(range(1, 31))  # c00 + p01-p30
        elif members == 'control':
            member_list = [0]
        else:
            member_list = members

        # Default variables if not specified
        if variables is None:
            variables = ['TMP:2 m']  # 2-meter temperature as default

        # Load data for each member
        member_datasets = []
        for member_num in member_list:
            # Create member name (c00 for control, p01-p30 for perturbations)
            member_name = 'c00' if member_num == 0 else f'p{member_num:02d}'

            # TODO: Test if we can load all forecast hours at once
            # For now, loop over forecast hours
            time_datasets = []
            for fhr in forecast_hours:
                # Create Herbie object
                H = Herbie(
                    init_time,
                    model='gefs',
                    member=member_num,
                    fxx=fhr,
                    **herbie_kwargs
                )

                # Load all requested variables
                # Note: Herbie.xarray() can take regex patterns
                var_pattern = '|'.join(f'({v})' for v in variables)
                ds_time = H.xarray(var_pattern)

                time_datasets.append(ds_time)

            # Concatenate times
            ds_member = xr.concat(time_datasets, dim='time')

            # Add member coordinate
            ds_member = ds_member.assign_coords(member=member_name)

            member_datasets.append(ds_member)

        # Concatenate members
        ds = xr.concat(member_datasets, dim='member')

        # Add init_time as coordinate (useful for lagged ensembles)
        ds = ds.assign_coords(init_time=init_time)

        return cls(ds, lazy=True)

    @classmethod
    def from_zarr(
        cls,
        zarr_path: Union[str, Path],
        lazy: bool = True
    ) -> 'Ensemble':
        """Load ensemble from Zarr format (e.g., from brc_tools.download.nwp).

        This is the recommended way to load data downloaded via the
        standardized download pipeline.

        Args:
            zarr_path: Path to Zarr store (file or directory)
            lazy: Whether to use lazy loading (default: True)

        Returns:
            Ensemble instance

        Example:
            >>> from brc_tools.download.nwp import download_gefs_ensemble
            >>> # First, download data
            >>> zarr_path = download_gefs_ensemble(
            ...     init_time=datetime.datetime(2025, 10, 26, 0)
            ... )
            >>> # Then load into Ensemble
            >>> ens = Ensemble.from_zarr(zarr_path)
            >>> print(ens)
        """
        import xarray as xr
        ds = xr.open_zarr(zarr_path)
        return cls(ds, lazy=lazy, validate=True)

    @classmethod
    def from_netcdf(
        cls,
        netcdf_path: Union[str, Path],
        lazy: bool = True
    ) -> 'Ensemble':
        """Load ensemble from NetCDF file.

        Alternative to from_zarr() for NetCDF format data.

        Args:
            netcdf_path: Path to NetCDF file
            lazy: Whether to use lazy loading (default: True)

        Returns:
            Ensemble instance
        """
        import xarray as xr
        ds = xr.open_dataset(netcdf_path, chunks='auto' if lazy else None)
        return cls(ds, lazy=lazy, validate=True)

    @classmethod
    def from_lagged(
        cls,
        model: str,
        init_times: list[datetime.datetime],
        members_per_init: int,
        forecast_hours: Union[list[int], range],
        variables: Optional[list[str]] = None,
        **kwargs
    ) -> 'Ensemble':
        """Create lagged ensemble from multiple initialization times.

        A lagged ensemble combines forecasts from different init times,
        useful for increasing ensemble size and capturing uncertainty
        from IC/model errors.

        Args:
            model: Model name ('gefs', 'sref', etc.)
            init_times: List of initialization times to use
            members_per_init: How many members to take from each init
            forecast_hours: Forecast lead times
            variables: Variables to load
            **kwargs: Additional arguments for model-specific loader

        Returns:
            Ensemble with members from multiple init times

        Example:
            # Create 15-member lagged GEFS (5 members from 3 init times)
            >>> ens = Ensemble.from_lagged(
            ...     model='gefs',
            ...     init_times=[
            ...         datetime.datetime(2025, 10, 25, 12),
            ...         datetime.datetime(2025, 10, 25, 18),
            ...         datetime.datetime(2025, 10, 26, 0),
            ...     ],
            ...     members_per_init=5,
            ...     forecast_hours=range(0, 24, 3)
            ... )
        """
        if model != 'gefs':
            raise NotImplementedError(f"Lagged ensembles not yet supported for {model}")

        # Load ensemble for each init time
        init_datasets = []
        for init_time in init_times:
            # Load subset of members
            member_subset = list(range(1, members_per_init + 1))

            ens_init = cls.from_gefs(
                init_time=init_time,
                members=member_subset,
                forecast_hours=forecast_hours,
                variables=variables,
                **kwargs
            )

            # Rename members to include init time
            # e.g., 'p01' -> '00Z_p01', '06Z_p01'
            init_str = init_time.strftime('%HZ')
            new_members = [f"{init_str}_{m}" for m in ens_init.ds.member.values]
            ens_init.ds = ens_init.ds.assign_coords(
                member=new_members,
                init_time=('member', [init_time] * len(new_members))
            )

            init_datasets.append(ens_init.ds)

        # Concatenate all members
        ds_lagged = xr.concat(init_datasets, dim='member')

        return cls(ds_lagged, lazy=True)

    # ========== Statistical Methods (salvaged from evac) ==========

    def mean(
        self,
        var: str,
        time: Optional[datetime.datetime] = None,
        level: Optional[float] = None
    ) -> xr.DataArray:
        """Compute ensemble mean.

        Args:
            var: Variable name
            time: Optional time slice
            level: Optional vertical level

        Returns:
            DataArray with 'member' dimension averaged out
        """
        data = self._get_subset(var, time=time, level=level)
        return data.mean(dim='member')

    def std(
        self,
        var: str,
        time: Optional[datetime.datetime] = None,
        level: Optional[float] = None
    ) -> xr.DataArray:
        """Compute ensemble standard deviation (spread).

        Args:
            var: Variable name
            time: Optional time slice
            level: Optional vertical level

        Returns:
            DataArray with standard deviation across members
        """
        data = self._get_subset(var, time=time, level=level)
        return data.std(dim='member')

    def percentile(
        self,
        var: str,
        q: Union[float, list[float]],
        time: Optional[datetime.datetime] = None,
        level: Optional[float] = None
    ) -> xr.DataArray:
        """Compute ensemble percentiles.

        Args:
            var: Variable name
            q: Percentile(s) to compute (0-100)
            time: Optional time slice
            level: Optional vertical level

        Returns:
            DataArray with percentile values
        """
        data = self._get_subset(var, time=time, level=level)
        return data.quantile(q / 100, dim='member')

    def get_exceedance_prob(
        self,
        var: str,
        threshold: float,
        operator: Literal['>', '<', '>=', '<=', '=='],
        time: Optional[datetime.datetime] = None,
        level: Optional[float] = None,
        bbox: Optional[tuple[float, float, float, float]] = None
    ) -> xr.DataArray:
        """Compute probability of threshold exceedance.

        Salvaged from evac.datafiles.ensemble.Ensemble.get_exceedance_probs()
        but modernized with xarray.

        Args:
            var: Variable name
            threshold: Threshold value (in same units as variable)
            operator: Comparison operator
                '>' : probability of exceeding threshold
                '<' : probability of being below threshold
                '>=': probability of reaching or exceeding
                '<=': probability of at or below
                '==': probability of equaling (use with caution for floats)
            time: Optional time slice
            level: Optional vertical level
            bbox: Optional bounding box (south, north, west, east)

        Returns:
            DataArray with probability values (0-100%) at each grid point/time

        Example:
            # Probability of T > 0°C (freezing)
            >>> prob_above_freezing = ens.get_exceedance_prob(
            ...     't2m', threshold=273.15, operator='>'
            ... )
        """
        # Get data subset
        data = self._get_subset(var, time=time, level=level, bbox=bbox)

        # Apply operator (salvaged from evac, using modern approach)
        ops = {
            '>': np.greater,
            '<': np.less,
            '>=': np.greater_equal,
            '<=': np.less_equal,
            '==': np.equal
        }

        if operator not in ops:
            raise ValueError(f"Invalid operator '{operator}'. Must be one of {list(ops.keys())}")

        # Create boolean mask
        mask = ops[operator](data, threshold)

        # Compute probability (percentage of members meeting condition)
        prob = 100 * mask.sum(dim='member') / len(data.member)

        # Add metadata
        prob.attrs['threshold'] = threshold
        prob.attrs['operator'] = operator
        prob.attrs['long_name'] = f"Probability of {var} {operator} {threshold}"
        prob.attrs['units'] = '%'

        return prob

    def closest_to_mean(
        self,
        var: str,
        time: datetime.datetime,
        level: Optional[float] = None,
        bbox: Optional[tuple[float, float, float, float]] = None
    ) -> str:
        """Find ensemble member closest to ensemble mean.

        Useful for identifying a "representative" member for visualization.
        Salvaged from evac.datafiles.ensemble.Ensemble.closest_to_mean()

        Args:
            var: Variable to use for comparison
            time: Time to evaluate
            level: Optional vertical level
            bbox: Optional region to limit comparison (south, north, west, east)

        Returns:
            Member name closest to mean

        Example:
            >>> repr_member = ens.closest_to_mean('t2m', time=valid_time)
            >>> repr_data = ens.ds.sel(member=repr_member)
        """
        # Get data and mean
        data = self._get_subset(var, time=time, level=level, bbox=bbox)
        mean = data.mean(dim='member')

        # Compute RMSE from mean for each member
        diff = data - mean
        rmse = np.sqrt((diff ** 2).sum(dim=['lat', 'lon']))

        # Find member with minimum RMSE
        closest_idx = rmse.argmin(dim='member').values
        closest_member = data.member.values[closest_idx]

        return str(closest_member)

    # ========== Helper Methods ==========

    def _get_subset(
        self,
        var: str,
        time: Optional[datetime.datetime] = None,
        level: Optional[float] = None,
        bbox: Optional[tuple[float, float, float, float]] = None
    ) -> xr.DataArray:
        """Get data subset with optional time/level/bbox slicing."""
        data = self.ds[var]

        if time is not None:
            data = data.sel(time=time, method='nearest')

        if level is not None and 'level' in data.dims:
            data = data.sel(level=level, method='nearest')

        if bbox is not None:
            south, north, west, east = bbox
            data = data.sel(
                lat=slice(south, north),
                lon=slice(west, east)
            )

        return data

    # ========== Web API Methods ==========

    def to_timeseries_json(
        self,
        var: str,
        location: tuple[float, float],
        members: Literal['all', 'mean', 'spread'] = 'all',
        level: Optional[float] = None
    ) -> dict:
        """Export time series at a point location to JSON.

        For BasinWx interactive charts showing ensemble forecast evolution.

        Args:
            var: Variable name
            location: (lat, lon) point
            members: Which members to include:
                'all': All individual members
                'mean': Ensemble mean only
                'spread': Mean ± 1 std dev
            level: Optional vertical level

        Returns:
            JSON-serializable dict with structure:
            {
                'location': {'lat': ..., 'lon': ...},
                'variable': var,
                'units': '...',
                'times': ['2025-10-26T00:00:00Z', ...],
                'members': {
                    'p01': [val1, val2, ...],
                    'p02': [...],
                    'mean': [...],  # if members='mean' or 'spread'
                    'std': [...]    # if members='spread'
                }
            }
        """
        lat, lon = location

        # Extract point data
        data = self.ds[var].sel(lat=lat, lon=lon, method='nearest')

        if level is not None and 'level' in data.dims:
            data = data.sel(level=level, method='nearest')

        # Prepare output
        output = {
            'location': {'lat': float(data.lat.values), 'lon': float(data.lon.values)},
            'variable': var,
            'units': data.attrs.get('units', 'unknown'),
            'times': [str(t.values) for t in data.time],
            'members': {}
        }

        # Add member data
        if members == 'all':
            for member in data.member.values:
                member_data = data.sel(member=member).values
                output['members'][str(member)] = member_data.tolist()

        elif members == 'mean':
            mean_data = data.mean(dim='member').values
            output['members']['mean'] = mean_data.tolist()

        elif members == 'spread':
            mean_data = data.mean(dim='member').values
            std_data = data.std(dim='member').values
            output['members']['mean'] = mean_data.tolist()
            output['members']['std'] = std_data.tolist()
            output['members']['upper'] = (mean_data + std_data).tolist()
            output['members']['lower'] = (mean_data - std_data).tolist()

        return output

    def to_geojson(
        self,
        var: str,
        statistic: Literal['mean', 'std', 'prob'],
        time: datetime.datetime,
        threshold: Optional[float] = None,
        operator: Optional[str] = None,
        level: Optional[float] = None,
        downsample: Optional[int] = None
    ) -> dict:
        """Export gridded data as GeoJSON for map overlays.

        Args:
            var: Variable name
            statistic: Which statistic to export:
                'mean': Ensemble mean
                'std': Ensemble spread
                'prob': Exceedance probability (requires threshold & operator)
            time: Valid time to export
            threshold: Threshold for probability calculation
            operator: Operator for probability calculation
            level: Optional vertical level
            downsample: Optional downsampling factor for web performance

        Returns:
            GeoJSON FeatureCollection

        Note:
            This creates a grid of points. For large grids, consider
            using raster formats (GeoTIFF, Zarr) instead.
        """
        # Get statistic
        if statistic == 'mean':
            data = self.mean(var, time=time, level=level)
        elif statistic == 'std':
            data = self.std(var, time=time, level=level)
        elif statistic == 'prob':
            if threshold is None or operator is None:
                raise ValueError("threshold and operator required for statistic='prob'")
            data = self.get_exceedance_prob(
                var, threshold=threshold, operator=operator,
                time=time, level=level
            )
        else:
            raise ValueError(f"Invalid statistic: {statistic}")

        # Downsample if requested
        if downsample:
            data = data.coarsen(lat=downsample, lon=downsample, boundary='trim').mean()

        # Convert to GeoJSON (placeholder - needs proper implementation)
        # TODO: Use geojson-xarray or similar library
        features = []
        for lat_idx, lat in enumerate(data.lat.values):
            for lon_idx, lon in enumerate(data.lon.values):
                value = float(data.values[lat_idx, lon_idx])
                if not np.isnan(value):
                    features.append({
                        'type': 'Feature',
                        'geometry': {
                            'type': 'Point',
                            'coordinates': [float(lon), float(lat)]
                        },
                        'properties': {
                            'value': value,
                            'variable': var,
                            'statistic': statistic
                        }
                    })

        return {
            'type': 'FeatureCollection',
            'features': features
        }

    # ========== Dunder Methods ==========

    def __repr__(self) -> str:
        n_members = len(self.ds.member)
        n_times = len(self.ds.time)
        vars_list = ', '.join(self.ds.data_vars)
        return (
            f"Ensemble({n_members} members, {n_times} times)\n"
            f"Variables: {vars_list}\n"
            f"Lazy: {self._is_dask_backed(self.ds)}"
        )

    def __iter__(self):
        """Iterate over members (salvaged from evac)."""
        return iter(self.ds.member.values)

    def __len__(self) -> int:
        """Number of members."""
        return len(self.ds.member)

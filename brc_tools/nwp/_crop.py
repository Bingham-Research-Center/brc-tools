"""Spatial cropping and nearest-point extraction."""

import logging

import numpy as np

logger = logging.getLogger(__name__)

_kdtree_cache: dict = {}


def crop_to_bbox(ds, sw, ne, crop_method="lonlat_after_aux"):
    """Crop an xarray Dataset to a lat/lon bounding box.

    Handles both regular lat/lon grids and projected grids with 2-D
    auxiliary latitude/longitude coordinates. Automatically detects
    0..360 vs -180..180 longitude conventions.
    """
    if crop_method == "lonlat_shift_then_sel":
        # GEFS: native lon is 0..360, shift to -180..180 first
        if "longitude" in ds and float(ds.longitude.max()) > 180.0:
            shifted = ((ds.longitude + 180.0) % 360.0) - 180.0
            ds = ds.assign_coords(longitude=shifted).sortby("longitude")
        lat_slice = slice(max(sw[0], ne[0]), min(sw[0], ne[0]))
        if float(ds.latitude[0]) < float(ds.latitude[-1]):
            lat_slice = slice(sw[0], ne[0])
        ds = ds.sel(latitude=lat_slice, longitude=slice(sw[1], ne[1]))

    elif crop_method in ("lonlat_after_aux", "lonlat_direct"):
        if "latitude" in ds.dims and "longitude" in ds.dims:
            lat_slice = slice(sw[0], ne[0])
            if "latitude" in ds.coords and float(ds.latitude[0]) > float(ds.latitude[-1]):
                lat_slice = slice(ne[0], sw[0])
            q_sw_lon = _match_lon_convention(sw[1], ds)
            q_ne_lon = _match_lon_convention(ne[1], ds)
            ds = ds.sel(latitude=lat_slice, longitude=slice(q_sw_lon, q_ne_lon))
        else:
            lat2d = _get_2d_coord(ds, "latitude")
            lon2d = _get_2d_coord(ds, "longitude")
            if lat2d is not None and lon2d is not None:
                sw_lon = _match_lon_convention_2d(sw[1], lon2d)
                ne_lon = _match_lon_convention_2d(ne[1], lon2d)
                mask = (
                    (lat2d >= sw[0]) & (lat2d <= ne[0])
                    & (lon2d >= sw_lon) & (lon2d <= ne_lon)
                )
                y_any = mask.any(dim="x") if "x" in mask.dims else mask.any(axis=1)
                x_any = mask.any(dim="y") if "y" in mask.dims else mask.any(axis=0)
                y_idx = np.where(y_any.values)[0]
                x_idx = np.where(x_any.values)[0]
                if len(y_idx) > 0 and len(x_idx) > 0:
                    y_dim = "y" if "y" in ds.dims else [d for d in ds.dims if d not in ("time",) and "x" not in d.lower()][0]
                    x_dim = "x" if "x" in ds.dims else [d for d in ds.dims if d not in ("time",) and "y" not in d.lower()][0]
                    ds = ds.isel(
                        {y_dim: slice(y_idx[0], y_idx[-1] + 1),
                         x_dim: slice(x_idx[0], x_idx[-1] + 1)}
                    )
    return ds


def nearest_point_value(ds, lat, lon, method="kdtree_2d"):
    """Extract the nearest grid point values for all data variables."""
    if method == "ds_sel_nearest":
        query_lon = _match_lon_convention(lon, ds)
        return ds.sel(latitude=lat, longitude=query_lon, method="nearest")

    lat2d = _get_2d_coord(ds, "latitude")
    lon2d = _get_2d_coord(ds, "longitude")
    if lat2d is None or lon2d is None:
        return ds.sel(latitude=lat, longitude=lon, method="nearest")

    query_lon = _match_lon_convention_2d(lon, lon2d)
    cache_key = id(lat2d.values.data)
    if cache_key not in _kdtree_cache:
        from scipy.spatial import cKDTree
        pts = np.column_stack([lat2d.values.ravel(), lon2d.values.ravel()])
        _kdtree_cache[cache_key] = (cKDTree(pts), lat2d.shape)
    tree, shape = _kdtree_cache[cache_key]
    _, idx = tree.query([lat, query_lon])
    yi, xi = np.unravel_index(idx, shape)
    y_dim = [d for d in lat2d.dims if "y" in d.lower() or d == lat2d.dims[0]][0]
    x_dim = [d for d in lat2d.dims if "x" in d.lower() or d == lat2d.dims[-1]][0]
    return ds.isel({y_dim: int(yi), x_dim: int(xi)})


def _get_2d_coord(ds, name):
    """Get a 2-D coordinate array (latitude or longitude) from a Dataset."""
    if name in ds.coords and ds[name].ndim == 2:
        return ds[name]
    for coord_name in ds.coords:
        if name in coord_name.lower() and ds[coord_name].ndim == 2:
            return ds[coord_name]
    return None


def _match_lon_convention(lon, ds):
    """Convert a query longitude to match the dataset's convention."""
    if "longitude" in ds.coords:
        if float(ds.longitude.max()) > 180.0:
            return lon % 360
    return lon


def _match_lon_convention_2d(lon, lon2d):
    """Convert a query longitude to match a 2-D longitude array's convention."""
    if float(lon2d.max()) > 180.0:
        return lon % 360
    return lon

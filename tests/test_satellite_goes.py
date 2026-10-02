"""GOES-R ABI listing, navigation and resampling (``brc_tools.satellite.goes``). No network."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest

from brc_tools.satellite import goes

G18 = goes.GoesProjection(35786023.0, 6378137.0, 6356752.31414, -137.0)

LISTING = """<?xml version="1.0" encoding="UTF-8"?>
<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><Name>noaa-goes18</Name>
<Prefix>ABI-L2-LSTC/2025/027/06/</Prefix><KeyCount>3</KeyCount><IsTruncated>false</IsTruncated>
<Contents><Key>ABI-L2-LSTC/2025/027/06/OR_ABI-L2-LSTC-M6_G18_s20250270601181_e20250270603554_c20250270606444.nc</Key><Size>1090560</Size></Contents>
<Contents><Key>ABI-L2-LSTC/2025/027/06/README.txt</Key><Size>12</Size></Contents>
<Contents><Key>ABI-L2-LSTC/2025/366/23/OR_ABI-L2-LSTC-M6_G18_s20243662301181_e20243662303554_c20243662306444.nc</Key><Size>5</Size></Contents>
</ListBucketResult>"""


def test_parse_listing_keeps_netcdf_objects_and_reads_the_scan_start():
    files = goes.parse_listing(LISTING, "noaa-goes18")
    assert len(files) == 2
    f = files[0]
    assert f.start == datetime(2025, 1, 27, 6, 1, 18) and f.size == 1090560
    assert f.name.startswith("OR_ABI-L2-LSTC") and f.url.startswith("https://noaa-goes18.s3.amazonaws.com/ABI-L2-LSTC/2025/027/06/")
    assert files[1].start == datetime(2024, 12, 31, 23, 1, 18)        # day 366 of a leap year


def test_nearest_files_within_tolerance():
    files = goes.parse_listing(LISTING, "noaa-goes18")
    picked = goes.nearest_files(files, [datetime(2025, 1, 27, 6), datetime(2025, 1, 27, 9)], tolerance_min=35)
    assert list(picked) == [datetime(2025, 1, 27, 6)]
    assert picked[datetime(2025, 1, 27, 6)].size == 1090560
    assert goes.nearest_files([], [datetime(2025, 1, 27, 6)]) == {}


def test_navigation_round_trip_and_special_points():
    lat = np.array([40.5, 39.2, 41.8, 0.0])
    lon = np.array([-109.5, -111.7, -107.5, -137.0])
    x, y = goes.scan_angles(lat, lon, G18)
    assert x[3] == pytest.approx(0.0, abs=1e-12) and y[3] == pytest.approx(0.0, abs=1e-12)   # sub-satellite point
    assert x[0] > 0 and y[0] > 0                                         # east and north of it
    lon2, lat2 = goes.lonlat_from_scan(x, y, G18)
    assert np.allclose(lat2, lat, atol=1e-7) and np.allclose(lon2, lon, atol=1e-7)
    over = goes.scan_angles(0.0, -137.0 + 100.0, G18)
    assert np.isnan(over[0]) and np.isnan(over[1])
    off_disc = goes.lonlat_from_scan(0.3, 0.0, G18)                       # beyond the limb (max ~0.151 rad)
    assert np.isnan(off_disc[0])


def test_height_shifts_the_apparent_position_away_from_the_satellite():
    lat, lon, h = 40.5, -109.5, 3000.0
    x, y = goes.scan_angles(lat, lon, G18, height_m=h)
    lon_app, lat_app = goes.lonlat_from_scan(x, y, G18)                  # where that pixel lands on the ellipsoid
    # displacement expected: h * tan(zenith angle of the satellite at the point)
    r = 6371.0e3
    lat_r, dlon = np.radians(lat), np.radians(lon - G18.longitude_of_projection_origin)
    cos_c = np.cos(lat_r) * np.cos(dlon)                                 # central angle to the sub-satellite point
    central = np.arccos(cos_c)
    zen = np.arctan2(np.sin(central), cos_c - r / (r + G18.perspective_point_height))
    expected = h * np.tan(zen)
    d_north = np.radians(lat_app - lat) * r
    d_east = np.radians(lon_app - lon) * r * np.cos(lat_r)
    moved = np.hypot(d_north, d_east)
    assert moved == pytest.approx(expected, rel=0.08)
    assert 3500.0 < moved < 5500.0                                       # km-scale: bigger than a pixel is not, but real
    assert d_east > 0 and d_north > 0                                    # away from a satellite to the south-west


def test_nearest_index_on_ascending_and_descending_coordinates():
    asc = np.linspace(-0.1, 0.1, 201)
    desc = asc[::-1]
    assert goes.nearest_index(asc, [-0.1, 0.0004, 0.1, 0.2, np.nan]).tolist() == [0, 100, 200, -1, -1]
    assert goes.nearest_index(desc, [0.1, 0.0, -0.1004]).tolist() == [0, 100, 200]


def test_sample_on_latlon_reads_the_nearest_pixel_and_applies_the_quality_flag(tmp_path):
    netCDF4 = pytest.importorskip("netCDF4")
    # a small fixed grid round 40.5 N, 109.5 W as GOES-18 sees it: 56 microradian (2 km) pixels
    x0, y0 = goes.scan_angles(40.5, -109.5, G18)
    step = 56e-6
    xs = float(x0) + step * (np.arange(81) - 40)
    ys = float(y0) - step * (np.arange(61) - 30)                         # north to south, as the files are
    lst = 250.0 + 0.1 * np.arange(81)[None, :] + 0.5 * np.arange(61)[:, None]
    dqf = np.ma.zeros(lst.shape, dtype="u2")                             # unsigned, as the real files store it
    dqf[:, :35] = 2                                                      # the western columns are screened out
    dqf[:, 35:] = np.where(np.arange(61)[:, None] % 2 == 0, 0, 1) * np.ones((1, 46), dtype="u2")
    dqf[0, 0] = np.ma.masked                                             # a fill value must not break the read
    path = tmp_path / "OR_ABI-L2-LSTC-M6_G18_s20250270601181_e20250270603554_c20250270606444.nc"
    with netCDF4.Dataset(path, "w") as nc:
        nc.createDimension("x", xs.size)
        nc.createDimension("y", ys.size)
        nc.createVariable("x", "f8", ("x",))[:] = xs
        nc.createVariable("y", "f8", ("y",))[:] = ys
        v = nc.createVariable("LST", "f4", ("y", "x"), fill_value=-999.0)
        v.units = "K"
        v[:] = lst
        nc.createVariable("DQF", "u2", ("y", "x"), fill_value=65535)[:] = dqf
        p = nc.createVariable("goes_imager_projection", "i4")
        p.perspective_point_height, p.semi_major_axis = G18.perspective_point_height, G18.semi_major_axis
        p.semi_minor_axis, p.longitude_of_projection_origin = G18.semi_minor_axis, G18.longitude_of_projection_origin
        nc.platform_ID, nc.title = "G18", "ABI L2 Land Surface Temperature"
    out = goes.sample_on_latlon(path, (-109.9, -109.1, 40.3, 40.7), res_deg=0.05, max_quality=1)
    assert out.time == datetime(2025, 1, 27, 6, 1, 18) and out.units == "K" and out.name == "LST"
    assert out.values.shape == (out.lat.size, out.lon.size) and out.lat[0] > out.lat[-1]
    j, i = int(np.argmin(np.abs(out.lat - 40.5))), int(np.argmin(np.abs(out.lon + 109.5)))
    assert out.values[j, i] == pytest.approx(lst[30, 40])               # the centre pixel
    # every sampled value is the pixel whose scan angles are nearest the target's
    sx, sy = goes.scan_angles(*np.meshgrid(out.lat, out.lon, indexing="ij"), G18)
    ix, iy = goes.nearest_index(xs, sx), goes.nearest_index(ys, sy)
    assert (ix >= 0).all() and (iy >= 0).all()                           # the whole target grid is inside the image
    keep = ix >= 35
    assert keep.any() and (~keep).any()
    assert np.allclose(out.values[keep], lst[iy[keep], ix[keep]])
    assert np.isnan(out.values[~keep]).all()
    assert out.quality[keep].max() == 1 and out.quality[~keep].min() >= -1
    strict = goes.sample_on_latlon(path, (-109.9, -109.1, 40.3, 40.7), res_deg=0.05)      # default: high quality only
    assert np.isnan(strict.values[keep & (iy % 2 == 1)]).all() and np.isfinite(strict.values[keep & (iy % 2 == 0)]).all()
    everything = goes.sample_on_latlon(path, (-109.9, -109.1, 40.3, 40.7), res_deg=0.05, max_quality=None)
    assert np.isfinite(everything.values[(ix >= 0) & (iy >= 0)]).all()

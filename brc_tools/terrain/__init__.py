"""Terrain analysis for airshed proxies: DEM mosaics, D8 routing, catchments and gates.

Cold air drains like water until it does not -- it crosses low saddles, ponds behind
sills and rides over pools -- so a D8 watershed is a *lower-bound proxy* for a canyon's
supply region, never the airshed itself.  This subpackage gives that proxy on the
finest terrain that exists (USGS 3DEP 1/3 and 1 arc-second) and the geometry a
heat-deficit budget needs from it: the basin floor at a rim height, every channel that
crosses the rim into it, the catchment behind each crossing, and a gate line cut
perpendicular to the channel at the crossing with its width in metres and in WRF cells.

Modules
-------
``dem``          tiles -> one metric grid (UTM 12N), the ``Grid`` geometry, label NPZ I/O,
                 warping onto any grid, block reduction
``d8``           priority-flood fill, D8 receivers, flow accumulation, upstream labelling,
                 path tracing, fill depth
``catchments``   basin floor, rim crossings, hypsometry, supply curves, matching two
                 labellings by overlap, unique display names
``gates``        perpendicular gate lines, valley widths, the lookups.toml ``[gates]`` row
``profiles``     long profiles of a channel; reach-averaged valley sections against stage
``depressions``  closed-depression inventory, the sill between two basins, volume against stage
``throat``       the narrowest passage between two basins: clearance width, minimum-cut area
``conditioning`` slope limiting and channel breaching (what a model grid does to terrain)
``skyview``      sky-view factor
``wrfgrid``      a WRF ``geo_em`` on a ``Grid``; HGT_M against its source; WPS tile coverage
``validate``     NWIS gauges, WBD units and NHD flowlines as checks on the routing

The heavy dependencies (rasterio, richdem, pyproj, netCDF4) are optional and imported
lazily: ``pip install brc-tools[terrain]`` or the ``terrain-2026`` conda env
(``environment-terrain.yml``).  Everything else is numpy/scipy.  Method notes and the
knobs: ``docs/TERRAIN-D8.md`` (routing) and ``docs/TERRAIN-THROATS.md`` (model grids,
sills and throats).  The theory that consumes this geometry is ``brc_tools.drainage``.
"""
from __future__ import annotations

__all__ = ["dem", "d8", "catchments", "gates", "profiles", "depressions", "throat", "conditioning",
           "skyview", "wrfgrid", "validate"]

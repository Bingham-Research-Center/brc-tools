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
``dem``          tiles -> one metric grid (UTM 12N), the ``Grid`` geometry, label NPZ I/O
``d8``           priority-flood fill, D8 receivers, flow accumulation, upstream labelling
``catchments``   basin floor, rim crossings, hypsometry, supply curves
``gates``        perpendicular gate lines, valley widths, the lookups.toml ``[gates]`` row
``validate``     NWIS gauges, WBD names and NHD flowlines as checks on the routing

The heavy dependencies (rasterio, richdem, pyproj) are optional and imported lazily:
``pip install brc-tools[terrain]`` or the ``terrain-2026`` conda env
(``environment-terrain.yml``).  Everything else is numpy/scipy.  Method notes and the
knobs: ``docs/TERRAIN-D8.md``.
"""
from __future__ import annotations

__all__ = ["dem", "d8", "catchments", "gates", "validate"]

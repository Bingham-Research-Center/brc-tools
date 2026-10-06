# Terrain routing for airshed proxies (`brc_tools.terrain`)

D8 catchments, basin floors and gate lines on USGS 3DEP elevation, for the drainage
budgets of the Uinta Basin (ub-wx `drainage-canyons-gigawatts`). This page is the
method note; the API is in `docs/API-REFERENCE.md`, the knobs are all caller
arguments, and the numbers a case derives from it belong to the case.

## 1. What D8 is, and why single-flow

**D8** (O'Callaghan & Mark 1984) sends all of a cell's flow to the steepest of its
eight neighbours. It is the standard single-flow-direction algorithm of every GIS;
the alternatives split flow among several neighbours (D-infinity, Tarboton 1997;
multiple-flow-direction, Freeman 1991 / Quinn et al. 1991). For a *catchment
inventory* single flow is the right tool: every cell belongs to exactly one
catchment, catchments tile the terrain, and "what drains through this mouth" has one
answer. Multiple-flow methods give fractional membership, which is right for
hillslope wetness and wrong for a budget that needs additive areas.

Pits are removed first by **priority-flood filling** (Barnes, Lehman & Mulla 2014,
`richdem`) with an epsilon gradient so every filled cell still drains; NaN cells are
outlets. Flow accumulation and upstream labelling use one Kahn (topological)
ordering of the receiver graph (`d8.flow_accumulation`), so both are vectorised
gathers: 6e8 cells at 10 m over the Basin route in ~30 min and 60 GB.

## 2. A watershed is not an airshed

D8 routes water. Cold air also drains downhill, but it crosses low saddles under a
pressure gradient or an ambient wind, ponds behind sills at the depth the night has
filled them to, and rides over a pool that is denser than itself. So a D8 catchment
is a **lower-bound proxy** for the region that supplies a canyon on a given night,
never the airshed. The registry entry that uses these numbers forbids the claim
"that a D8 watershed is an airshed" for that reason, and the tracer runs are what
measure the difference.

Two other caveats. Resolution: catchment **areas** converge early (< 2 % change from
90 m to 10 m; routing against 317-587 USGS gauges gives a median D8/NWIS ratio of
0.999 at 30 m), but **mouth widths and slopes** do not, so widths come from the
finest DEM and areas from whichever is convenient. And the DEM is filled: a real
closed depression (Strawberry Valley behind its gorge, a glacial lake basin) is
routed *through* as if it overflowed, which is exactly the storage the drainage
budget has to add back.

## 3. The floor, the rim and the cuts

The basin floor is not "everything below a height". It is
(`catchments.basin_floor`):

- the connected component of cells below the **rim height** that contains the
  **sink** (a lookups.toml waypoint: `ouray` for the Uinta Basin),
- restricted to cells hydrologically upstream of the **outlet line** (where the
  basin's river leaves: the Green at Sand Wash) and upstream of **no cut line**
  (`catchments.hydro_mask`).

A cut is placed where the floor is open to a river corridor whose own basin the
grid cannot hold (the Green above Split Mountain, the White east of Rangely). The
corridor then appears as a truncated catchment -- a **port**, an entry for air the
domain never saw cool -- instead of being counted as a canyon.

Everything outside the floor that drains into it crosses the rim somewhere;
`catchments.rim_crossings` finds those cells, `d8.label_upstream` gives each its
catchment, and a crossing with at least `channel_km2` upstream is a canyon
**gate**. Crossings whose catchment contains floor cells (`floor_leak_fraction`
above ~1 %) are artefacts of the floor's shape and are dropped.

**A higher rim makes a canyon narrower or wider by construction.** The crossing
moves up-valley to where the channel passes the new height, and the width is
measured *there*. The Duchesne's 2000 m crossing is at Farm Creek above Hanna; at
1900 m it is 20 km further downstream. Report widths with their rim, and choose the
rim from the pool depth the question is about, not the other way round.

## 4. Gate geometry rules (`gates.perpendicular_gate`)

1. The line passes through the crossing cell, **perpendicular to the channel**;
   the channel direction is the main stem from ~500 m upstream to ~500 m
   downstream (`walk_upstream_main` / `walk_downstream`).
2. Its length is `clip(1.5 x width150, 6 km, 12 km)` unless the caller says
   otherwise, straight in the projected grid, converted to lat/lon at the ends.
3. It is ordered so that walking **a -> b puts downstream on the right**: with
   `wrf_output.integrate_flux_transect` the rightward normal is the export
   direction, so `Phi > 0` is flow out of the catchment.
4. Widths are the contiguous run of DEM cells around the thalweg lying below
   thalweg + 50 / 100 / 150 / 200 m (`valley_widths`), in metres;
   `width_in_cells(width, dx)` says whether a model resolves the mouth (a bulk
   flux wants five cells or more).
5. `gate_to_lookup_entry` + `format_gate_toml` write the `[gates.<name>]` block
   for lookups.toml with the citation string, so a gate is a registered place
   only when the terrain it came from is named.

## 5. Validation surfaces (`terrain.validate`)

- **NWIS** stream gauges with a published drainage area (`compare_to_nwis`,
  `routing_score`): snap each gauge to the channel within 300 m and compare areas.
- **WBD** HUC10/HUC12 names at a point up the main channel (`wbd_name`), so a gate
  carries the canyon's name rather than the receiving valley's.
- **NHD** flowlines (`nhd_flowlines`, `channel_agreement`): does the D8 channel
  follow the mapped stream, especially where a canyon bends round a foothill.

All three are open USGS services; none is NWP, so the Herbie rule does not apply.

## 6. Running it

`scripts/terrain_pipeline.py` is the reference pipeline (tiles -> fill -> D8 ->
floor/crossings per rim -> perpendicular gates -> NPZ + CSV + JSON). It runs in the
`terrain-2026` env (`environment-terrain.yml`: rasterio, richdem, pyproj, GDAL) on a
compute node through `scripts/terrain_pipeline.slurm`, which puts the checkout on
`PYTHONPATH` because that env carries no editable install. The package itself
imports without the optional stack; only `dem.mosaic_tiles`, `d8.fill_depressions`
and the `Grid` coordinate transforms need it. Caches: `$BRC_TOOLS_TERRAIN_CACHE`
(default `~/.cache/brc-tools/terrain`), never the checkout.

Source tiles: USGS 3DEP 1/3 arc-second (~10 m) and 1 arc-second (~30 m) GeoTIFFs,
1 x 1 degree, named by their NW corner. The Basin set lives in
`$WRF_ARCHIVE/terrain/usgs_3dep/` (ub-wx `drainage-canyons-gigawatts`, with a
manifest).

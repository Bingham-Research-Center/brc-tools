# Sills, throats and model grids (`brc_tools.terrain`, second half)

`docs/TERRAIN-D8.md` is the routing: catchments, floors, gates. This page is what was
added for the question *"what does a model grid do to the terrain a cold pool has to
drain through?"* (ub-wx `drainage-canyons-gigawatts`, Iteration 5). Everything here
works on any `(ny, nx)` elevation raster with a `Grid` -- the 3DEP mosaic, a block
mean of it, or `HGT_M` of a real WRF domain -- so the same function is run on the truth
and on the grid and the difference is the result.

## 1. Why a grid dams a canyon

A river leaves a basin through a canyon a few hundred metres wide. A 600 m model cell
straddling that canyon averages its floor with its walls, so on the grid the lowest
route out of the basin climbs over a **sill** that does not exist. Air (and water)
must then fill the basin to that level before any of it can leave. The priority-flood
fill that D8 routing starts from *hides* this: it raises the basin to the sill and
routes across it. The functions below measure what the fill hides.

| Question | Function | Returns |
|---|---|---|
| Where is terrain below its spill level, and by how much? | `d8.fill_depth` | depth raster (fill without the epsilon gradient, minus the terrain) |
| What closed depressions are there? | `depressions.inventory` | labels + `Depression` list (area, volume, depth, spill level, deepest cell) |
| How high is the lowest pass between two places? | `depressions.sill_between` | the minimax level, to a tolerance |
| How much does a basin hold below a level? | `depressions.volume_stage`, `stage_for_volume` | volume / flooded area against stage, and the inverse |
| How large is the narrowest cross-section between two basins under a level pool top? | `throat.min_cut_area` | area in m2 (and the cut, on request) |
| How many cells wide is the widest passage? | `throat.clearance_width` | width in metres |
| What are a canyon's sections, reach by reach? | `profiles.slab_sections` | area, top width, wetted perimeter against stage per reach |
| What does the channel look like end to end? | `profiles.long_profile`, `sample_path` | distance, elevation, drainage area, widths; another raster sampled under a path |

## 2. Closed depressions

`depressions.inventory(dem, d8.fill_depth(dem, grid), cell_area)` labels connected
regions deeper than `min_depth_m` (8-neighbour) with at least `min_cells` cells and
summarises each. The thresholds are the caller's: 3 m and 0.05 km2 drop the pits every
30 m DEM has; on a 600 m grid one cell is already 0.36 km2.

On the true terrain the depressions are reservoirs behind real dams, lake basins and
glacial hollows. On a model grid there is a second population -- the valleys above
canyons the grid could not resolve -- and it is hundreds of times larger in volume.

**A natural closed basin needs an outlet.** The fill treats grid edges and NaN cells as
outlets and raises everything else until it spills. A real internally drained basin (the
Great Divide Basin) is therefore filled to its rim and spilled into a neighbour, adding
its area to the wrong river. Give it an outlet first: set the deepest cell of any
depression above an area and depth threshold to NaN before the routing fill
(`terrain_reference.py` in ub-wx does this for depressions over 300 km2 and 20 m).

## 3. The sill between two basins

`depressions.sill_between(z, seed_a, seed_b)` returns the lowest stage at which a pool
floods a continuous path between two seeds: the highest point of the lowest connecting
route. It is a bisection on the stage with a connected-component test, so it needs no
path search and costs about `log2(relief / tol)` labelings of the window.

- Seeds are `(j, i)` cells or bool masks -- a single cell is fine *here*, because a sill
  is a level, not a cross-section (the throat functions below refuse one). A named place
  can sit on a bench or a wall on a coarse grid; `depressions.lowest_cell(z, grid, lat,
  lon, radius_m=...)` snaps it to the lowest cell nearby.
- Take the seeds **once, on the true terrain**, and reuse their coordinates on every
  grid, or the comparison measures the seed, not the grid.
- The answer is only as wide as the window: if the true lowest route leaves the array,
  the sill is overestimated. Use a window with a margin and check `storage_reaches_edge`
  style flags in the caller.

## 4. The throat

`throat.min_cut_area(z, res, stage, src, dst)` is the smallest cross-sectional area
separating two basins inside the region a pool at `stage` floods: a depth-weighted
minimum cut. Flooded cells are graph nodes; neighbouring cells are joined by an edge
whose capacity is the area of the water column on the face between them,
`w * res * (stage - max(z_a, z_b))`, with the Cauchy-Crofton weights (`pi/8` for the
four axis neighbours, `pi/(8 sqrt 2)` for the diagonals) that make the total weight of a
cut approximate its Euclidean length whatever its orientation. `scipy.sparse.csgraph.
maximum_flow` gives the cut.

**The basins are masks, never cells.** `src` and `dst` must be bool masks of the grid's
shape; a `(j, i)` cell or a one-cell mask is a `ValueError`. With a point seed the
cheapest cut is the ring round that one cell, so the answer measures the seed, not the
canyon: 13 400 m2 against 39 900 m2 for a 9-cell test channel, and a clearance width
limited by the clearance at the seed. Build each mask well wider than the throat --
a disc of a few kilometres round the `lowest_cell` of each basin, or the basin's own
floor -- and keep it the same on every grid.

Why a cut and not a transect: it needs no thalweg and no perpendicular, so meanders do
not matter; dead-end side canyons contribute nothing; parallel routes (a braided reach, a
bypass over a low saddle) add up, as they should. On straight channels rotated to any
angle the result is within 10 % of the analytic section (`tests/test_terrain_throat.py`).

`throat.clearance_width` is the companion that says whether a model can carry a current
through the passage at all: the width of the widest path between the basins through the
flooded cells, by a bisection on the distance-to-dry transform. A one-cell channel has
width `res`; a bulk current wants about five.

A cell exactly at the stage counts as flooded, as it does in `sill_between`: at the sill
the throat is open, one cell wide, with zero area.

`throat.throat_curve` evaluates both over a list of stages. **Use the same absolute
stages on every terrain** (heights above the true upstream floor), so that
`area_grid / area_true` is a like-for-like ratio and a grid whose sill is above a stage
simply returns zero there.

Cost: one maximum flow per stage on the flooded cells of the window. Half a million
cells takes seconds; several million takes minutes and gigabytes -- cap it and fall back
to the reach sections.

## 5. Reach sections

`profiles.slab_sections(z, grid, rcv, order, starts, stem, stages)` gives each reach of
a channel its section as a function of stage **without cutting a transect**: every cell
whose own flow path joins the stem within `max_reach_m` belongs to the stem cell it
joins; consecutive stem cells are grouped into slabs of `slab_len_m`; a slab's flooded
volume, plan area and terrain-surface area divided by its length are the section's
area, top width and wetted perimeter. `max_reach_m` keeps the interiors of side canyons
-- storage a current does not flow through -- out of the section. The table is exactly
what `brc_tools.drainage.hydraulics.Reach` takes.

## 6. Model grids

- `wrfgrid.read_geo_em(path)` returns `HGT_M` north-up with a `Grid` in the domain's
  own Lambert projection on the WRF sphere, and the land mask, land use and lake mask
  beside it. The projection is checked against the file's own corner coordinates, and
  the cells whose `LANDMASK` is not 0 or 1 (the seam cell below) are counted into
  `meta["landmask_bad_cells"]`, with a warning when there are any.
- `dem.warp_tiles(tifs, grid, resampling="average", src_crs=wrfgrid.sphere_geo_crs())`
  puts the source DEM on the same cells the way geogrid sees it (no datum shift).
- `wrfgrid.hgt_source_diff(hgt, src)` is the crater detector: `HGT_M` minus the source.
  geogrid's own smoothing pass leaves differences of 100-170 m on canyon rims at
  500-600 m; a real artefact is several hundred metres and has a cross of half-depth
  neighbours (the smoothing pass spreading one empty cell).
- `wrfgrid.wps_tile_coverage(tile_dir)` reads a WPS binary tile set back (in the
  `index`'s `endian`, big by default) and reports missing cells per tile and whether
  `index` declares a `missing_value`. A declared `missing_value` is what counts as
  missing; without one, values at or below `nodata_below` (-1000 m) do, because geogrid
  then reads a hole -- -32768 m -- as terrain.

**The seam cell.** The WPS build used here leaves *every* field without data at any
cell whose centre has the float32 longitude -110.00003051757812 (four float32 steps of
7.63e-6 degrees west of the -110 meridian, a tile seam of the 10-degree standard
datasets): `LANDMASK` comes out -1, the land use "water", and `HGT_M` 0 m before
smoothing. All 23 such cells in 64 archived `geo_em` files sit on that one value. The
check -- `LANDMASK` must be 0 or 1 everywhere -- is `meta["landmask_bad_cells"]` from
`read_geo_em`, and the cure is in the domain spec: make -110 the central
meridian (`stand_lon = ref_lon = -110`) with an odd coarse `e_we`, so the meridian is a
cell edge of every domain and no centre comes near it.

## 7. Conditioning: what a grid does to terrain on purpose

- `conditioning.limit_slope(z, res, max_deg)` relaxes only the cells that are too steep
  (and their neighbours) until no cell-to-cell slope exceeds the limit: the smoothing a
  steep fine nest needs before it will integrate. Run the throat functions on its output
  to see how much of the canyon the smoothing puts back.
- `conditioning.breach(z, cells, profile)` lowers cells along a path to a thalweg
  profile; with `monotone_downstream` on the true river's elevation sampled per model
  cell it "carves" the river through a grid that averaged it shut.
- `conditioning.max_neighbour_slope` is the slope the stability predictor wants.

Both are for *evaluating* a choice. Nothing in this package edits a model's static data.

## 8. Comparing labellings across grids, and naming

- `dem.regrid_nearest` lays a label raster of one spacing over another on the same CRS
  by index arithmetic; `dem.sample_labels` does it by lat/lon for any pair of grids.
- `catchments.match_labels` matches catchments of two labellings by overlap (IoU,
  covered fraction, area ratio). Counting mouths says little -- two crossings a kilometre
  apart are one mouth or two depending on the rim contour; overlap says whether the
  catchment behind a known mouth still exists as one unit. For a fixed-pour-point
  comparison snap each reference mouth onto the other grid's channel with
  `validate.snap_to_channel` and re-derive the catchment there.
- `catchments.unique_names` builds display names from a mapped stream name
  (`validate.stream_name` on NHD flowlines) qualified by the HUC12 and HUC10 units
  (`validate.wbd_unit`). **A name is never a join key**: a HUC10 unit usually holds
  several rim catchments. Key on an ID made from the mouth's coordinates.

## 9. Sinks

The basins a pool fills are places and live in `lookups.toml` `[sinks.*]`: an `exit`
point (where the basin's outlet channel enters its throat), the `throat` it leads into,
where that throat ends, and the sink it feeds. `brc_tools.drainage.sinks` reads them
with `tomllib` alone (the terrain environment cannot import `brc_tools.nwp`), and
`catchments.point_max_acc_cell` turns an exit point into a cell: the largest
accumulation within a radius, which -- since accumulation grows downstream -- is the
most downstream channel cell inside it.

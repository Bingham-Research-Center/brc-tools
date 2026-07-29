# WRF winds — basin-winds-style figures from a WRF run

The WRF counterpart of the ub-wx `basin-winds` HRRR case. For each nest it renders

- **plan views** — a surface field (10 m wind speed by default) with earth-relative
  barbs, terrain contours, Natural-Earth reference overlays, and town labels;
- **cross-sections** — terrain-filled wind curtains along named A→B geographic
  lines, with θ contours, in-plane (along + exaggerated `w`) vectors, along-line
  town markers, and the geographic locator inset;
- **3-D cold-pool views** — hillshaded terrain with the θ = θ_iso surface floating
  above it as a lid coloured by the depth of air it caps.

Plan views use the same renderer as the HRRR path (`brc_tools.visualize.nwp_maps`),
so the two are directly comparable. The vertical is where they part company.
`extract_nwp_section` has to stack isobaric levels because that is all GRIB
carries; the WRF adapter samples the **native eta column**, which for a drainage
layer tens of metres deep is the difference between seeing the feature and
interpolating it away.

The curtain renderer is therefore separate too. The isobaric one resamples each
column onto a regular `dz` axis and shades it `gouraud`, because 13 pressure levels
flat-shaded would be 13 fat bands — the smoothing buys back detail GRIB never had.
A WRF section is the opposite case: ~80 stretched eta levels whose near-surface
spacing is metres, where resampling and blurring destroy exactly the structure
being studied. So `plot_wrf_curtain` shades the model's **true cells** with
`pcolormesh(..., shading="flat")` on the w-level edges, contours and quivers on the
mass points, and draws the terrain as the staircase the model actually feels.

| piece | lives in |
|---|---|
| adapter (`wrfout` → plan `Dataset` / `NWPSection`) | `brc_tools/nwp/wrf_section.py` |
| native-grid curtain renderer | `brc_tools/visualize/wrf_curtain.py` |
| 3-D cold-pool renderer | `brc_tools/visualize/coldpool3d.py` |
| engine + CLI | `scripts/wrf_winds.py` |
| SLURM wrapper | `scripts/wrf_winds.dtn.slurm` |
| **per-case config** | a TOML in the repo that owns the case |

No case-specific code lives in brc-tools — a new case is a new TOML.

Related but distinct: **`docs/WRF-FIGURE-ENGINE.md`** (`scripts/wrf_figures.py`) is the
publication engine for the pelican2013-style study families — grid-aligned EW/NS
sections, multi-domain surface panels, differences, heat-deficit diagnostics. Reach
for that one for a study's figure set; reach for this one for arbitrary transects,
the locator inset, and a quick matched look across nests while a run is still
writing.

## Run

```
# on a DTN: lawson-group6 is read-only on login nodes, and lawson-np is usually
# busy running the very job you want to look at
sbatch scripts/wrf_winds.dtn.slurm --config <case.toml> [--run-dir <run>] \
       [--hourly | --every 15 | --all | --valid 2025-09-08_22:00 | --lead 120] \
       [--domain 2] [--w-exag 10] [--theta-iso 311] [--output-dir <dir>] [--dpi 200]
```

- `--every MIN` sweeps every valid time on a MIN-minute cadence; `--hourly` is
  shorthand for `--every 60`; `--all` takes the run's native output interval.
  Sweeps use the **union** of times across domains, not the intersection — a 3 km
  parent on hourly output and a 600 m nest on 5-minute output share only whole
  hours, so intersecting would discard every sub-hourly frame the fine nest has.
  Each domain then renders only the times it holds, and the count of skipped
  domain-times is reported once at the end rather than per line.
- Figures are simply overwritten, so re-running as the job advances costs nothing
  but wall clock.
- `--valid` takes an exact `YYYY-MM-DD_HH:MM`; `--lead` takes **minutes** after
  init (`SIMULATION_START_DATE`, else the earliest wrfout).
- With none of those, the engine renders **the latest valid time present on every
  requested domain** — the useful default against a *running* job, where a 3 km
  parent on hourly output lags a 600 m nest on 5-minute output. Domains missing
  the chosen time are named-skipped, never a crash; so is a single time that fails
  mid-sweep (a wrfout caught half-written), which does not abort the rest.
- `--run-dir` overrides the TOML, so one config serves every run of a case.
- `--w-exag` overrides every section's vertical exaggeration for that render (see
  the note under `w_exag` below).
- Output: `<out>/<YYYYmmdd_HHMM>/<tag>/{topdown_<var>,xsection_<key>}_<tag>_<stamp>.png`.
  Default root is `$BRC_TOOLS_OUTPUT_DIR` (else group6 `brc-tools-output`) `/ <slug>`.

Both wrfout filename conventions are read: WRF's default `%Y-%m-%d_%H:%M:%S` **and**
the `nocolons = .true.` form `%Y-%m-%d_%H_%M_%S`. (`brc_tools.nwp.wrf_output` assumes
the first; the tolerant helpers live in `wrf_section.py`.)

## Case TOML schema

```toml
[case]
slug = "ashley-drainage-120m"     # output subdirectory
label = "Ashley drainage"         # figure titles
annotation = "..."                # small bottom-right provenance stamp
run_dir = "/scratch/.../wrf_run"  # $VARS expanded; --run-dir overrides
output_dir = "..."                # optional; --output-dir overrides

[map]                             # Natural-Earth overlays; fail-soft if unstaged
states = true; counties = true; roads = true; rivers = true; lakes = true

[style.overrides.<var>]           # vmin/vmax/cmap/label/extend/diverging
vmin = 306.0                      # the shared table is tuned for winter cold pools
vmax = 322.0

[[domains]]                       # one per VIEW, not per nest
domain = 2                        # nest number
tag = "d02_ashley"                # names the output dir; lets one nest have several views
extent = [lon0, lon1, lat0, lat1] # optional; else the full grid
pad_deg = 0.03                    # inset the full-grid view (hides the relaxation zone)
barb_stride = 16
waypoint_group = "basin_landmarks"   # a group in nwp/lookups.toml
surface_vars = ["wind_speed_10m", "theta_2m", "pblh"]
sections = ["we", "dryfork"]      # keys into [[sections]]
views3d = ["ashley_pool"]         # keys into [[views3d]]

[[sections]]
key = "dryfork"
label = "Dry Fork -> Vernal -> Green R."   # keep SHORT: the quiver key sits top-right
a = [lat, lon]                    # terminus A
b = [lat, lon]                    # terminus B
termini = ["NW", "SE"]
waypoint_group = "us40_dense"
offset_km = 12.0                  # label towns within this distance of the line
y_top_m = 4200.0                  # must clear the highest terrain on the line
w_exag = 8.0
n_points = 200                    # samples along the line (nearest column each)
shade = "speed"                   # speed | theta | temp | along | w | theta_e
theta_interval = 1.0              # K between theta contours
quiver_stride = [5, 10]           # (vertical, horizontal), in MODEL LEVELS
loc_extent = [lon0, lon1, lat0, lat1]   # locator inset map window
loc_rect = [x, y, w, h]                 # inset placement, axes fraction

[[views3d]]
key = "ashley_pool"
label = "Ashley + Dry Fork cold pool"
extent = [lon0, lon1, lat0, lat1]
theta_iso = [311.0, 313.0]        # one panel per isentrope; --theta-iso overrides
azim = -90.0                      # camera due south = LOOKING NORTH; -60 is oblique
elev = 22.0
stride = 2                        # decimate the surface mesh
z_frac = 0.45                     # vertical size as a fraction of the wider side
depth_min_m = 25.0                # thinner than this is a skim, not a pool
depth_max_m = 400.0               # colour-scale top (share it across a sweep)
max_depth_m = 700.0               # reject lids this far up: that is a mixed layer
```

`n_points` should be about the number of **grid cells** the line crosses, not more:
the curtain is flat-shaded on the model's own cells, so oversampling just draws
duplicated columns as visible repeats.

`surface_vars` are **style keys**, because the renderer looks the colour scale up by
variable name: `wind_speed_10m`, `theta_2m`, `temp_2m`, `pblh`. A variable the run
did not write is named-skipped.

### Choosing `w_exag`

The renderer's docstring suggests the plot aspect (transect length ÷ visible depth),
which is right when `w` is small — the HRRR case uses 100. It is **not** a geometric
constant: it is set by the regime. A convective afternoon on a 600 m mesh resolves
`w ~ 1–3 m s⁻¹`, so an exaggeration of 100 makes every vector vertical and hides the
along-transect flow entirely; ~8–15 reads correctly. A quiescent drainage night has
`w` two orders of magnitude smaller and wants the geometric value back. Put the
common regime in the TOML and switch with `--w-exag` for the other.

### Choosing `theta_iso`

The isentrope is an **absolute** threshold, which is what makes a fixed value
across a sweep show the pool *filling*: it starts as a sliver on the coldest ground
and grows up the canyons as the surface cools. Sample the basin-floor θ₂ₘ first and
bracket it — one value a kelvin or two below (empty now, grows through the night)
and one at or just above (already substantial).

Too warm is a trap. An isentrope above the environmental θ over high terrain sits
a kilometre above the ground there, and the "pool" it draws is just the mountain
boundary layer. `max_depth_m` is the guard: set it to about the depth of a
brim-full basin, so a genuine pool survives and a mixed layer does not.

### Choosing `loc_rect`

The inset (default top-right) collides with the rotated town labels that hang from
the top edge. Put it wherever the panel is dead: for a transect that descends
left-to-right, the **bottom-left** corner is inside the terrain fill and free.

## Adding a case

1. Copy an existing TOML into the repo that owns the case (for ub-wx WRF
   experiments: `experiments/<id>/figures.toml`).
2. Set `run_dir`, `[[domains]]`, and the transect endpoints.
3. Check the transect actually crosses the terrain you meant — sample `HGT` along it
   before rendering; an endpoint outside a nest silently samples that nest's edge
   column all the way out.
4. `sbatch scripts/wrf_winds.dtn.slurm --config <that TOML>`.

# WRF winds — basin-winds-style figures from a WRF run

The WRF counterpart of the ub-wx `basin-winds` HRRR case. Four families, selected
with `--figure` (repeatable; default is all of them):

| `--figure` | renders |
|---|---|
| `topdown` | **plan views** — a surface field with earth-relative barbs, terrain contours, Natural-Earth overlays and town labels |
| `section` | **cross-sections** — terrain-filled curtains on native eta levels along named A→B lines, with θ contours, in-plane vectors, along-line town markers and a locator inset |
| `profile` | **vertical profiles** — θ and humidity against height at named waypoints, with a wind-speed panel and height-paced barbs |
| `view3d` | **3-D cold-pool views** — hillshaded terrain with the θ = θ_iso surface floating above it as a lid coloured by the depth of air it caps |
| `tracers` | **air-mass origin** — dominant passive-tracer source as a curtain and a plan view, per-source share curtains, and a stacked source spectrum at a point. Needs a run seeded with `tracer_opt`; named-skipped otherwise |

A fifth product lives in a **separate engine** because it spans the whole run
rather than one valid time: `scripts/wrf_timeheight.py` draws **time–height
sections** at `tslist` stations. See "Time–height sections" below.

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
| derived diagnostics (fog, cloud, radiation, stability, TKE) | `brc_tools/nwp/wrf_derived.py` |
| passive-tracer source attribution | `brc_tools/nwp/wrf_tracers.py` |
| native-grid curtain renderer | `brc_tools/visualize/wrf_curtain.py` |
| 3-D cold-pool renderer | `brc_tools/visualize/coldpool3d.py` |
| tracer-origin renderers | `brc_tools/visualize/tracer_origin.py` |
| time–height renderer | `brc_tools/visualize/timeheight.py` |
| engine + CLI | `scripts/wrf_winds.py`, `scripts/wrf_timeheight.py` |
| SLURM wrappers | `scripts/wrf_winds.dtn.slurm`, `scripts/wrf_timeheight.dtn.slurm` |
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
       [--figure topdown --figure section --figure profile --figure view3d] \
       [--hourly | --every 15 | --all | --valid 2025-09-08_22:00 | --lead 120] \
       [--start 2025-09-08_18:00] [--end 2025-09-09_06:00] \
       [--domain 2] [--w-exag 10] [--theta-iso 311] [--output-dir <dir>] [--dpi 200]
```

- `--figure` selects families (repeatable); `--start`/`--end` bound a sweep. Both
  are shared with `wrf_convective.py` via `wrf_engine.add_time_arguments`, so the
  procedure in `docs/VISUAL-SUITE-SOP.md` is the same against either engine.
- `--every MIN` sweeps every valid time on a MIN-minute cadence; `--hourly` is
  shorthand for `--every 60`; `--all` takes the run's native output interval.
  Sweeps use the **union** of times across domains, not the intersection — a 3 km
  parent on hourly output and a 600 m nest on 5-minute output share only whole
  hours, so intersecting would discard every sub-hourly frame the fine nest has.
  Each domain then renders only the times it holds, and the count of skipped
  domain-times is reported once at the end rather than per line.
- Figures are overwritten by default, so re-running as the job advances costs
  nothing but wall clock. `--skip-existing` makes that re-run cheap instead: see
  "Idempotence, dry runs and coverage" below.
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

### Idempotence, dry runs and coverage

Shared by both this engine and `wrf_convective.py`
(`brc_tools.nwp.wrf_engine.FigureLedger`):

| flag | what it does |
|---|---|
| `--dry-run` | print the exact figure list this job would render, then exit. Nothing is written — no PNGs, no manifest |
| `--skip-existing` | keep a figure at least as new as every file it derives from. A `wrfout` rewritten by a later run is newer than its figure, so that figure regenerates — safe against a still-writing job |
| `--allow-errors` | exit 0 even if some figures failed. Without it **any** failure exits non-zero |
| `--report` | summarise coverage from the manifests already in the output root, then exit. Renders nothing |

Every real job writes `manifest_<jobid>.json` into the output root — config path and
SHA-256, run dir, argv, and one record per attempted figure with its family, domain,
valid time, variable and status (`rendered` / `skipped` / `error` / `absent`). Named
by `SLURM_JOB_ID`, so the normal pattern of several jobs sweeping into one output
root does not clobber itself.

`absent` is a distinct status on purpose: "this run never wrote that field" and
"this figure failed" are different answers to *where is my figure?*, and `find`
cannot tell them apart.

Per-figure failures are still caught and printed, so one bad panel cannot lose a
run. What changed is that the job can no longer *look* like a success — the old
`return 0 if total else 1` could not distinguish 400-of-400 from 100-of-400.

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

[diagnostics.heat_deficit]        # case knobs for the derived surface fields
crest_m = 2400.0
[diagnostics.theta_grad_sfc]
depth_m = 100.0
[diagnostics.tke_max]
below_m = 1000.0

[tracers]                         # only for a run seeded with tracer_opt
names  = ["source 1", "..."]      # in tr17_1..tr17_N order
floor  = 1.0e-3                   # below this total, a cell is "untagged"
level  = 0                        # model level for the origin map
shares = [2, 7]                   # 1-based: also draw these sources' share curtains

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
tracer_map = true                 # plan view of the dominant tracer source

[[sections]]
key = "dryfork"
label = "Dry Fork -> Vernal -> Green R."   # keep SHORT: the quiver key sits top-right
a = [lat, lon]                    # terminus A
b = [lat, lon]                    # terminus B
termini = ["NW", "SE"]
waypoint_group = "us40_dense"
offset_km = 12.0                  # label towns within this distance of the line
y_top_m = 4200.0                  # must clear the highest terrain -- unless tight-z
y_bottom_m = 1400.0               # optional; default is just below the lowest terrain
vertical = "asl"                  # "asl" (default) | "agl" -- see below
w_exag = 8.0
n_points = 200                    # samples along the line (nearest column each)
shade = "speed"                   # see the shade table below
style = "wind_speed"              # optional: override the shade's default colour scale
theta_interval = 1.0              # K between theta contours
quiver_stride = [5, 10]           # (vertical, horizontal), in MODEL LEVELS
loc_extent = [lon0, lon1, lat0, lat1]   # locator inset map window
loc_rect = [x, y, w, h]                 # inset placement, axes fraction
tracers = true                    # also draw the air-mass-origin curtain on this cut

[[profiles]]                      # keys referenced by [[domains]].profiles
key = "vernal"
label = "Vernal"
waypoint = "vernal"               # a lookups.toml waypoint name, not coordinates
y_top_m = 4200.0
crest_m = 3300.0                  # optional reference line
humidity = "rh"                   # "rh" | "q" | omit for none  (default "rh")
wind_bars = true                  # speed bars + barbs at the tips (default true)
barb_interval_m = 250.0           # barbs every N metres of HEIGHT (default 250)
tracers = true                    # also draw the stacked source spectrum here
tracer_top_m = 2000.0             # m AGL for that spectrum (default: y_top_m)

[[timeheight]]                    # read by scripts/wrf_timeheight.py, not wrf_winds
key = "vernal_airport"
label = "Vernal airport"
station = "KVEL"                  # a tslist PREFIX, i.e. the .TS filename stem
domain = 2
fields = ["theta", "theta_change", "theta_grad", "speed"]
y_top_m = 1500.0                  # m AGL
stride_min = 5.0                  # minutes between drawn columns

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
variable name. A variable the run did not write is named-skipped, never fatal:

| key | needs | what it is for |
|---|---|---|
| `wind_speed_10m` | always | the default |
| `theta_2m`, `temp_2m` | always | |
| `pblh` | `PBLH` | zero at f00 — a real value, not a bug |
| `tsk_minus_t2` | `TSK` | **surface decoupling**: strongly negative is ground radiating under a decoupled layer, which says a pool is forming hours before θ looks unusual |
| `snow_depth` | `SNOWH` | the albedo/emissivity control on that whole process |
| `conv_10m` | `U10`/`V10` | 10 m convergence, diverging about zero; same map-factor operator as the convective `meso` family and the deficit transport |

Plus the **derived** fields in `brc_tools/nwp/wrf_derived.py`, which WRF carries the
ingredients for and never writes. They cost a further read, so only the keys a view
actually names are computed; a key whose ingredients the run lacks is named-skipped:

| key | needs | what it is for |
|---|---|---|
| `visibility_sfc` | `QCLOUD` | Stoelinga–Warner visual range in the lowest level, capped at 20 km |
| `fog_depth` | `QCLOUD` | depth of the **ground-based** layer below 1 km visibility. NaN where there is none, so clear ground is unpainted rather than drawn as shallow fog everywhere |
| `condensate_max` | `QCLOUD` | column-maximum suspended cloud water + ice |
| `cloud_low` / `cloud_mid` / `cloud_high` | `CLDFRA` | layer cloud amount on the ISCCP pressure bands |
| `cloud_base` | `CLDFRA` | lowest cloudy level, m AGL |
| `ceiling` | `CLDFRA` | lowest **broken-or-worse** layer that is *not* on the ground; a 5 m base is a surface obscuration and belongs to `fog_depth`, not here |
| `rh_2m`, `lcl_agl` | `Q2`/`T2`/`PSFC` | how close the near-surface air is to fogging |
| `rnet_sfc`, `hfx`, `lh`, `grdflx` | the flux fields | the surface energy budget that **builds** a radiative pool |
| `energy_residual` | as above | `Rn + G − H − LE`, on a deliberately tight ±10 W m⁻² scale, so the panel shows the budget *closing* |
| `lw_down`, `sw_down` | `GLW`, `SWDOWN` | the radiative forcing |
| `theta_grad_sfc` | `T` | bulk 0–100 m ∂θ/∂z: where the cold air is **trapped**, which is not where it is cold |
| `tke_max` | `QKE` | column-max TKE below 1 km — the decoupling diagnostic |
| `ust`, `tsk` | `UST`, `TSK` | friction velocity, skin temperature |
| `heat_deficit` | `T` | Whiteman valley heat deficit below `[diagnostics.heat_deficit].crest_m` |

**`GRDFLX`'s sign is measured, not assumed.** Against the Noah
(`sf_surface_physics = 2`) run this was built on, `Rn + G − H − LE` closes to a
median −0.4 W m⁻² and the opposite sign leaves ~120 W m⁻², so there `GRDFLX` is
positive **upward**. A large `energy_residual` means the run's land-surface scheme
uses the other convention — not that the budget is open.

**`TKE_PBL` is identically zero in an MYNN run**, so plotting it gives a blank panel
that looks like a result; `wrf_derived.turbulent_kinetic_energy` reads `QKE` (which
is *twice* the TKE) and halves it.

### Map context

`[map]` switches, all default **false**: `states`, `counties`, `roads` (Natural-Earth
major highways), `rivers`, `lakes`, `cities` (population-ranked place labels).

Named places come from two independent sources and it is worth using both:
`waypoint_group` names a curated group in `nwp/lookups.toml` — the places a Basin
study refers to deliberately, with elevations and station IDs — while `cities = true`
adds whatever else is large enough to orient a reader unfamiliar with the area.

Overlays need `BRC_TOOLS_BASEMAP_DIR` (the SLURM wrapper points at the staged group6
cache); a missing layer is skipped, never fatal.

### Choosing `w_exag` — one rule, not four numbers

**This is the single source of truth for `w_exag`.** `WRF-CONVECTIVE.md`, both
skills and both `--w-exag` help strings point here rather than restating a value;
they used to quote 5, 8–15, 10 and 100 for the same knob.

The rule:

```
w_exag  ≈  median |along|  ÷  median |w|     (in the layer you care about, ON THIS TRANSECT)
```

That puts the typical vector at **45°**, which is where a two-component vector is
most readable — flatter and the vertical motion is invisible, steeper and the
along-transect flow is.

**`|along|`, not `|V|`** — and the difference is not academic. The arrow's
horizontal component *is* `along2d`, so `|V|` only gives the right answer when the
flow happens to run along the cut. Measured on the green-river 600 m run, over the
lowest few hundred metres:

| transect | \|along\| as a fraction of \|V\| | `w_exag` from \|V\| | from \|along\| |
|---|---|---|---|
| Little Mtn → Split Mtn (flow crosses it) | 34–52 % | 57–108 | **29–36** |
| Ouray basin floor (flow crosses it) | 37–40 % | 93–109 | **37–41** |
| Wyoming Green R. basin (flow follows it) | 75–88 % | 102–149 | **90–112** |

A cut made deliberately *across* a valley is exactly the case where the two
disagree, so the older `|V|` form over-exaggerates by 2–3× on precisely the
sections it matters most for — and the symptom is a curtain of near-vertical
arrows that looks like vigorous overturning and is nothing of the sort. Values in
existing case TOMLs that were measured with the `|V|` form are high by about that
factor on their cross-valley cuts.

It is **not** the plot aspect, and the renderer's older docstring was wrong to
suggest it. The quiver is drawn with matplotlib's default `angles="uv"`, where the
arrow direction comes from the component ratio alone and the axes' data aspect does
not enter: `u = v` draws at 45° whether the panel spans 10 km or 200 km. That the
geometric value happened to match for the HRRR case is a coincidence of that case's
numbers.

The rule reproduces every value previously in circulation, which is why they
disagreed — they are different regimes, not different opinions:

| regime | typical \|along\| | typical \|w\| | `w_exag` |
|---|---|---|---|
| deep convective core, 600 m mesh | ~10 m s⁻¹ | ~2 m s⁻¹ | **~5** |
| convective afternoon boundary layer | ~10 m s⁻¹ | ~1 m s⁻¹ | **~10** |
| quiescent drainage night | ~2 m s⁻¹ | ~0.02 m s⁻¹ | **~100** |
| isobaric HRRR section | ~10 m s⁻¹ | ~0.1 m s⁻¹ | **~100** |

Put the case's usual regime in the TOML and switch with `--w-exag` for the other.
**A sweep crossing sunset crosses regimes**, so one value cannot serve both ends of
it; render the last hour and check before trusting the night frames.

The factor is printed in the quiver key, so a reader always knows the vertical has
been stretched and by how much.

### What the fill and the vectors mean

A curtain's colour and its arrows are **different measurements on the same plane**,
and the figure now says which:

| `shade` | fill is | note |
|---|---|---|
| `speed` | `\|V\| = √(u²+v²)` | magnitude only — a cross-valley gale and an along-valley jet look identical |
| `along` | in-plane component, **+ toward B** | the component the arrows draw |
| `normal` | the flow **crossing** the section, **+ into the page** | diverging scale; for a W→E transect this is the north–south component |
| `w` | vertical velocity | |
| `theta`, `theta_e`, `temp`, `refl` | the scalar named | |
| `theta_anom` | θ **minus the bottom cell of the lowest-terrain column** | derived, not stored. A fixed absolute θ scale cannot serve a sweep across a night — the floor itself cools several kelvin, sliding every frame's structure down the bar. This takes the bulk cooling out and leaves the stratification. A pure offset: it changes what the colours mean, not the shape of anything |
| `rh`, `qv`, `cloud`, `vis`, `tke`, `theta_grad` | humidity, vapour, suspended condensate, visual range, TKE, ∂θ/∂z | each needs its 3-D field sampled — see `load_plane(extras=...)`. A section asking for one that the run cannot supply is named-skipped |

Two things are drawn on every curtain because a signed field is uninterpretable
without them:

- an **orientation stamp** below the axes — `A→B 090° (W→E) | into page = N`;
- a note that the vectors are **in-plane only** (along-transect + exaggerated `w`),
  so the normal component is discarded from them, not folded in.

For a west-to-east cut, `shade = "normal"` is the one that shows cross-valley
exchange; `speed` cannot, because it has no sign.

### `vertical = "asl"` vs `"agl"` — ponding or a skin

The two frames answer different questions and the same night can look like one in
each, which is why both are offered rather than one being the right choice:

- **`asl`** (default) — height above sea level, terrain as a staircase across the
  bottom. A level surface is a horizontal line, so this shows whether cold air is
  **ponding**: filling a basin to a level, independent of the ground.
- **`agl`** — the terrain flattened out. A layer of constant *depth* becomes a
  horizontal band, so this shows whether the layer is **terrain-following**: a
  drainage skin running down a slope rather than a pool sitting in it.

`y_top_m` / `y_bottom_m` are read in whichever frame is selected. Put the locator
inset somewhere else on an `agl` panel — flattening the terrain removes the wedge
the inset normally hides in.

### The tight-z pattern

A section whose subject is a 250 m inversion under a 1100 m terrain drop is
unreadable on the axis that makes the *regional* sections comparable. The fix is a
**second `[[sections]]` entry over the same A→B line** with a cut-down
`y_bottom_m`/`y_top_m` and a finer `theta_interval` (0.25 K rather than 1 K), not a
compromise axis that serves neither. On the tight panel the high end of the line is
simply inside the terrain fill — that is the trade, made deliberately, because the
mountain is not the subject.

### Passive tracers — `--figure tracers`

For a run seeded with `tracer_opt` (WRF's `tracer_test1` package gives `tr17_1`
..`tr17_8`). The figures are all about the **share**, never the absolute
concentration: source patches differ in area by large factors, so a concentration
says more about patch size than about transport, while the share of the tagged air
at a point is what a layering question is asking.

Four products, from `tracers = true` on a `[[sections]]` or `[[profiles]]` entry and
`tracer_map = true` on a `[[domains]]` entry:

| product | reads |
|---|---|
| origin curtain | which source dominates, on the model's own cells. A stratified pool draws as horizontal bands of different hue; a well-mixed one as a single colour from the ground up |
| share curtain | one named source's fraction, for the sources in `[tracers].shares` |
| source spectrum | the stacked share against height at a waypoint, with θ on a twin axis so a band boundary can be tied to a stable layer |
| origin map | the dominant source in one model level, with barbs — the drainage pathways |

**Opacity carries the confidence.** An argmax over eight tracers is a
confident-looking statement even when the winner holds 13 % against a runner-up's
12 %, so every panel fades a cell toward the background as the dominant share falls:
vivid is air from one place, pale is a mixture that happens to have a largest term.
Air below `[tracers].floor` carries no tag at all and is drawn grey **and hatched** —
because a thoroughly mixed cell of any hue also fades to pale grey, and "mixed" and
"untagged" are different findings.

Without a floor the normalisation divides noise by noise and paints a crisp,
entirely spurious attribution over every part of the domain the plume never reached.

## Time–height sections

`scripts/wrf_timeheight.py` — a separate engine sharing the same case TOML, because
its product spans the whole run rather than one valid time.

```
sbatch scripts/wrf_timeheight.dtn.slurm --config <case.toml> [--run-dir <run>] \
       [--station KEY] [--start ...] [--end ...] [--stride-min 5] [--dpi 200]
```

Every other vertical figure here is a snapshot. A cold pool is a *process* — it
starts, deepens, sometimes gets scoured, and breaks up at a particular hour — and
the one question a sweep of snapshots cannot answer is **when**.

The data costs nothing. A run with a `tslist` writes per-station column profiles at
**model-timestep cadence**: on the run this was built for, 33 601 rows over 28 hours
(one column every 3 s) in a 24 MB text file per variable per station, against 900 MB
per hourly `wrfout` frame. `--stride-min` decides how many of those rows are drawn;
the raw axis has far more columns than a 12-inch figure has pixels.

Fields: `theta`, `theta_change` (against the first time in the window, at fixed
height — the cooling), `theta_grad`, `speed`, `u`, `v`, `w`, `qv`. Set
`[case].local_offset_h` to get a second time axis in local time — a diurnal figure
whose only axis is UTC makes the reader do the arithmetic that decides whether a
feature is before or after sunset.

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
3. Check the transect crosses the terrain you meant. A transect leaving the nest is
   now caught for you: the engine preflights every `[[sections]]` line with
   `wrf_section.section_coverage` and prints how far along it departs, the off-grid
   part is blanked rather than filled from the edge column, and a line that misses
   the nest entirely is skipped. It used to sample that edge column all the way out
   and draw a flat, entirely physical-looking curtain.
4. `sbatch scripts/wrf_winds.dtn.slurm --config <that TOML>`.

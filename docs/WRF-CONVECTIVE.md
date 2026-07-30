# WRF convective diagnostics

Engine: `scripts/wrf_convective.py` (+ `scripts/wrf_convective.dtn.slurm`).
Capability: `brc_tools/radar/`, `brc_tools/nwp/wrf_convective.py`,
`brc_tools/nwp/convective_env.py`, `brc_tools/nwp/wrf_tslist.py`,
`brc_tools/visualize/hodograph.py`.
Skill: `/wrf-convective`.

Three WRF figure engines share this repo and they are **not** interchangeable:

| engine | job | config lives |
|---|---|---|
| `wrf_figures.py` | pelican2013 publication set; pinned by an evidence packet | study repo |
| `wrf_winds.py` | drainage / basin winds, native-eta curtains | case repo |
| **`wrf_convective.py`** | **reflectivity, radar beams, soundings, swaths** | **case repo** |

Config and time selection are shared via `brc_tools/nwp/wrf_engine.py`, so a fix to
"sweep a run that is still writing" lands in both the winds and convective engines.

## Why this exists

Three things about convective verification make it different from plotting winds,
and each one is a way to be quietly wrong:

1. **A distant radar does not see what a fixed height AGL shows.** KGJX is 189 km
   from Vernal on Grand Mesa at 3046 m; its beam centre over the valley floor is
   ~3.5 km AGL at 0.0°, ~5.2 km at 0.5° and ~7.5 km at 1.2°. Across one 600 m nest
   a single beam surface spans **2.0 to 13.7 km AGL**. Comparing simulated
   reflectivity to what that radar saw is only meaningful on the matching beam
   surface — hence the `beam` family, and hence `brc_tools/radar/beam.py`.
2. **A 10-minute history stream aliases the feature.** A ≲3 km gust swath crossing
   a point at ~12 m/s transits it in ~4 minutes. The `aux` family reads the
   high-cadence auxiliary stream; `verify` reads `tslist`, written every model step.
3. **The maximum fields in that auxiliary stream are traps.** `WSPD10MAX`,
   `UP_HELI_MAX`, `REFD_MAX` and friends reset on the **history** write, not on the
   auxiliary stream's write, so their values there are partial maxima over the
   current history interval. `wrf_convective.aux_field` refuses them and points at
   `wrfout`. A swath read from them looks right and is wrong.

## Families

Select with `--figure` (repeatable); default is all of them.

| family | reads | produces |
|---|---|---|
| `surface` | `wrfout` | plan views: composite reflectivity, `WSPD10MAX` swath, updraft helicity, echo top, vertical vorticity at a chosen height AGL |
| `aux` | `auxhist<N>` | the same, at the auxiliary stream's cadence |
| `section` | `wrfout` | reflectivity / `w` / θ curtains on native eta levels along A→B lines |
| `beam` | `wrfout` | **`REFL_10CM` sampled on a named radar's beam surfaces** |
| `sounding` | `wrfout` | skew-T with parcel path + LCL/LFC/EL, and a height-banded hodograph with Bunkers and observed storm motions |
| `verify` | `tslist` | model surface traces at named stations over a window |
| `track` | `wrfout` | reflectivity-centroid track, as a **CSV** — this is what sizes a nested domain |

## Invocation

```bash
sbatch scripts/wrf_convective.dtn.slurm \
    --config <case.toml> [--run-dir <run>/wrf_run] \
    [--figure beam --figure section] \
    [--valid 2025-10-12_02:20 | --lead 200 | --every 1 | --hourly | --all] \
    [--domain 2] [--w-exag 5] [--output-dir <dir>] [--dpi 200]
```

DTN, not a login node: `lawson-group6` is read-only on the login nodes, and
`lawson-np` is the single node a WRF run occupies.

Times behave as in `wrf_winds.py`: a sweep takes the **union** across domains (so a
3 km parent on hourly output does not throw away a 600 m nest's 1-minute frames),
and with no time flag the latest time present on *every* requested domain is used.
`--figure aux` on its own sweeps the auxiliary stream's own times.

## Case TOML schema

Configuration only. A case names capability; it never defines it. In particular
**station and radar coordinates are not case config** — reference a `lookups.toml`
waypoint name and a radar ICAO id.

### `[case]`
| key | meaning |
|---|---|
| `slug` | output subdirectory under the output root |
| `label` | title prefix |
| `annotation` | small print on every figure |
| `run_dir` | run directory; `$VARS` expanded |
| `output_dir` | optional; else `$BRC_TOOLS_OUTPUT_DIR/<slug>`. Refused if inside the brc-tools or case checkout |

### `[map]`
`states`, `counties`, `roads`, `rivers`, `lakes` — booleans, default false.

### `[style.overrides.<var>]`
`cmap`, `label`, `vmin`, `vmax`, `extend`, `diverging`. The convective entries in
`brc_tools/visualize/style.py` are already set from measured values; override only
where a case genuinely differs.

### `[[domains]]` — one per view (a nest may appear more than once)
| key | meaning |
|---|---|
| `domain` | nest number |
| `tag` | names the output subdirectory; lets one nest carry a full-extent and a zoomed view |
| `extent` / `pad_deg` | `[lon0, lon1, lat0, lat1]`, or trim inward from the nest edge |
| `barb_stride` | wind-barb thinning |
| `waypoint_group` | a `lookups.toml` group |
| `vorticity_level_agl_m` | height for the `vert_vorticity` panel |
| `surface_vars` | style keys to plot from `wrfout` |
| `aux_fields` | WRF field names to plot from the auxiliary stream |
| `aux_stream` | stream number, default 2 |
| `sections` / `beams` / `soundings` | keys into the arrays below |

### `[[beams]]`
`key`, `site` (ICAO, from `brc_tools/radar/sites.py`), `elevations_deg`.
Elevations are the **nominal** angles; a real VCP scans −0.04 / 0.44 / 1.49 where
products say 0.0 / 0.5 / 1.2, and the engine computes heights from the tilt
actually scanned.

### `[[sections]]`
`key`, `label`, `a`/`b` as `[lat, lon]`, `termini`, `shade`
(`refl`|`w`|`theta`|`speed`), `style`, `n_points`, `y_top_m`, `w_exag`,
`theta_interval`, `quiver_stride`, `offset_km`, `waypoint_group`, `loc_extent`,
`loc_rect`.

`w_exag` is regime-dependent: a convective updraft resolves several m/s and wants
~5; a drainage night wants ~100. Getting it wrong makes every vector vertical.

### `[[soundings]]`
`key`, `label`, `waypoint` (a `lookups.toml` name), `parcel` (`sb`|`ml`|`mu`),
`p_top_hpa`, `t_range`, `hodograph_top_m`, `observed_motion_ms`,
`observed_motion_label`.

There is no default parcel in the capability layer: in a 300–500 J/kg environment
the parcel choice moves CAPE by more than the signal, so state it.

### `[[verify]]`
`key`, `label`, `domain`, `variable`
(`wind_speed_10m`|`wind_dir_10m`|`temp_2m`|`pressure_surface`), `window` as two
`YYYY-MM-DD_HH:MM` stamps, and `stations` — a list of `{ ts_prefix, label }`.
`ts_prefix` is the 4-character prefix in the run's `tslist`.

### `[track]`
`threshold_dbz`, `near_waypoint`, `radius_km`, `largest_cluster`.

Restrict with `near_waypoint`/`radius_km` for any statement about a swath or a
track: over a 213 × 171 km footprint holding several storms, the domain-wide answer
is not a swath at all — measured on the Ashley run, the 45 dBZ bounding box spans
159 km while the feature near the spotter is 22 km.

**`track` is not an object tracker.** It reports whichever above-threshold cluster
is largest near the point in each frame, so the result is radius-sensitive and the
series can jump when a different cluster takes over — the same Ashley frame gives
40.76 / −109.46 at a 60 km radius and 40.13 / −109.66 at 40 km. Read it as "where is
the strongest echo near here now", never as a displacement, and inspect the jumps
before sizing a nest from it.

## Worked example

`../ub-wx/experiments/20251011-ashley-rotating-cell/figures.toml` — a 600 m nest
with a full-extent view, an Ashley Valley zoom, KGJX beam surfaces at three
elevations, along/normal-to-motion reflectivity sections, soundings at the spotter
point and KVEL, four verification windows, and a centroid track.

## What goes wrong first

- **Everything is dark blue.** Reflectivity below ~5 dBZ must be masked, not
  painted; the engine does this via `_MASK_AT_OR_BELOW`. Clear air is most of a
  domain.
- **All section vectors vertical** → `w_exag` set for the wrong regime.
- **A swath 159 km wide** → you measured the whole domain. Pass `near`.
- **`aux` skips a field** with a message about the history write → that field is a
  running maximum in that stream. Read it from `wrfout`; this is deliberate.
- **`beam` skipped entirely** → the run has no `REFL_10CM` (needs
  `do_radar_ref = 1`).
- **Empty `verify` panel** → no `tslist` output, or the window is outside the run.

## Radar data — observed

Two modules, and for a historical case **only one of them works**:

`brc_tools/radar/iem.py` — **the working route.** Iowa State's IEM RIDGE archive
serves per-radar **Level-III** base reflectivity as georeferenced PNGs at ~4–5 minute
cadence, with a long historical reach. Verified on KGJX 2025-10-12. Set
`compare_observed = true` on a `[[beams]]` entry and the `beam` family renders the
observed field beside the model's, on the same colour scale and extent.

**It carries elevation 1 (0.5°) only.** A signature reported at 0.0° or 1.2° has no
observed counterpart for a 2025 date — state that rather than substituting 0.5°.
Values are quantised to 0.5 dBZ and already resampled onto a lat/lon grid, so this is
not raw polar data. The velocity product `N0S` is fetchable but its scaling is
unverified, and `read_ridge` refuses it rather than returning unscaled indices.

`brc_tools/radar/nexrad.py` — Level-II via MetPy's reader. Richer (all tilts, both
moments, raw polar) but **no archive serves it for October 2025**. Read the transport
table in `docs/nwp/NWP-SOURCE-MATRIX.md` before relying on it.

Worked example, Ashley Valley at 02:20Z, model-vs-observed on the *same* tilt:

| field | max dBZ | p95 | area > 35 dBZ |
|---|---|---|---|
| model column maximum | 47.6 | 35.1 | — |
| model on 0.0° beam (2.8–3.7 km AGL) | 46.7 | 30.4 | — |
| model on **0.5°** beam (4.3–5.5 km AGL) | 44.1 | 25.3 | 1.2 % |
| model on 1.2° beam (6.4–8.0 km AGL) | 11.2 | 6.0 | 0 |
| **observed 0.5° (IEM `N0B`, 02:18Z)** | **53.5** | **40.5** | **6.4 %** |

Note how much the answer moves with tilt: the column maximum and the 1.2° surface
differ by 36 dBZ over the same ground. That is the entire argument for this family.

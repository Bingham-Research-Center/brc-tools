# WRF figure engine — dataset-agnostic publication figures

A reusable engine for publication-quality WRF figures (terrain-following
cross-sections, multi-domain surface panels, difference maps, θ(z) profiles /
skew-T, crest-level upper-air, a nested-domain map, and a cold-pool heat-deficit
series). It renders **any** WRF run — 2, 3, or 4 nests, any region, variable set, or
time window — from a declarative TOML case description; nothing about a specific
study is hardcoded.

- Engine: `brc_tools/nwp/wrf_figures.py` (`CaseConfig`, `build_tasks`, `preflight`,
  the `task_*` figure functions, output routing).
- CLI: `scripts/wrf_figures.py --config <case.toml>`.
- Reader / derivations: `brc_tools/nwp/wrf_output.py` (already dataset-agnostic).
- Renderers: `brc_tools/visualize/{crosssection,surface,domains,profile,upperair,
  timeseries}.py` + `style.py` + `basemap.py` (optional Natural-Earth overlays). These
  consume plain numpy and are reused unchanged.

The **case description is data, not code** — a per-study TOML lives in that study's
repo (e.g. the pelican2013 case in `../wrf-nudge-ozone-air2026/cases/pelican2013.toml`),
never in brc-tools. brc-tools owns only the generalized engine + CLI.

## Running

```bash
export PYTHONPATH=~/gits/brc-tools               # package is not pip-installed in the env
export MPLCONFIGDIR=/scratch/general/vast/$USER/mpl
PY=~/software/pkg/miniforge3/envs/brc-tools-2026/bin/python

# everything for a case
"$PY" scripts/wrf_figures.py --config <case.toml>

# a subset (case keys / families / hours are all comma-separated or 'all')
"$PY" scripts/wrf_figures.py --config <case.toml> --case nam --figure section,surface --time 12,18

# a specific forecast lead (the 1-hour forecast), skipping figures already produced
"$PY" scripts/wrf_figures.py --config <case.toml> --case nam --figure surface --lead 1 --skip-existing
```

Families: `domains, section, upperair, surface, difference, profile, skewt,
heatdeficit` (or `all`). Heavy batches run on SLURM (per `docs/CHPC-REFERENCE.md`);
the case's own repo owns the sbatch wrapper. Soundings need a network node — run
`scripts/fetch_soundings.py` first and pass `--sounding-cache`.

The `upperair` family renders **two** maps per time: the crest-height θ + wind + T-adv
map on the inner nest, and a synoptic **temperature-advection map on a pressure surface**
(`upper_pressure_hpa`, default 600 hPa) computed on the outer nest — 600 hPa sits well
above the shallow inner nest, where a raw `grad(T)` on the 333 m mesh is dominated by
noise, so the coarse nest + a pre-gradient smooth gives the clean warm/cold-advection
pattern that caps the cold pool.

**Map reference overlays** (US highways, rivers incl. the Green River, lakes/reservoirs,
state borders) are opt-in per case via the `[map]` table and drawn on the surface /
upper-air / domains maps. The engine stays cartopy-free for offline nodes, so the
overlays are **fail-soft**: stage the Natural-Earth shapefiles once into a persistent
cache (`BRC_TOOLS_BASEMAP_DIR`, else `CARTOPY_DATA_DIR`, else a scratch dir) and every
later figure job reads them offline. A DTN is the only node with both internet and
read-write group storage, so `sbatch scripts/fetch_basemap.dtn.slurm` fetches straight
into durable storage in one shot (re-runnable to refresh); `python scripts/fetch_basemap.py`
also works on any network node. If a layer is not staged the figure simply renders
without it. Waypoint labels are decluttered and points outside a cropped panel are dropped.

### Time selection: `--time` (valid hour) vs `--lead` (forecast hour)
- `--time` filters on **valid hour-of-day** (`--time 12,18` keeps every output whose
  valid time is 12Z or 18Z).
- `--lead` selects by **forecast lead** in whole hours from the run's init:
  `--lead 1` renders the valid time at `init + 1 h`. Init is
  `wrf_output.init_time(run, innermost)` — the `SIMULATION_START_DATE` global attr of
  the earliest wrfout, falling back to the earliest valid time in the filenames.
  `--lead` **overrides** `--time`. It governs the per-time families (section,
  upperair, surface, focus skew-T, difference) and the θ(z) profile; the station RAOB
  skew-T stays at `sounding_hour` and the heat-deficit series always spans all times.
- **Idempotent re-runs:** `--skip-existing` skips any figure that already exists and
  is newer than every source wrfout it derives from (mtime) — so a wrfout rewritten by
  a later run regenerates its figure ("move to newer output"), while unchanged figures
  are left alone. Filenames encode only the valid hour (`…_13z.png`), so this is safe
  for hourly (or coarser) cadence; **sub-hourly output would collide within an hour**
  (e.g. 13:00 and 13:10 both map to `…_13z.png`) — not handled, use full re-render
  there.

### Output routing (outside the repo)
- per-case → `<run>/full-figures/<family>/…`
- cross-case (domains, profiles, differences, heat-deficit) →
  `$BRC_WRF_ARCHIVE/<slug>_pub_figures/compare/<family>/…`
- override with `--output-dir` (nests `<case>/<family>/`); a guard refuses any path
  inside the brc-tools checkout.

`BRC_WRF_ARCHIVE` (if set) overrides the TOML `archive_dir`; `--run <run_*>` picks a
specific run directory (default: newest `run_*`).

## Domain-awareness (from the data)

The engine never assumes a nest count. It discovers nests with
`wrf_output.discover_domains(run_dir)` (globs `wrfout_d0N_*`), treats the innermost as
`max(domains)` and outermost as `min(domains)`, and labels each panel from the wrfout
`DX` global attr via `wrf_output.grid_spacing_label(ds)` (e.g. `d02 (1 km)`,
`d03 (333 m)`).

## Preflight & named skips (fail loudly, not silently)

Before building tasks, `preflight(cfg, case)` probes each selected case and returns a
`PreflightReport` (`domains`, `innermost`/`outermost`, `point_ok`,
`usable_surface_vars`, `times`, `skips`, `warnings`). `build_tasks` prints a
consolidated report and only emits tasks that will succeed:

- **No wrfout files / missing run** → the case is skipped with a named reason.
- **Focus point outside the innermost domain** (`wrf_output.point_in_domain`) → a
  `[WARN]`, and the focus-point families (profile, focus skew-T, heat-deficit) are
  skipped by name — instead of silently plotting a misleading edge column.
- **A surface variable absent from any rendered domain** → that variable is dropped
  from the `surface` family with a named `[SKIP]` (e.g. `surface:snow — SNOWH absent
  in d01`), rather than a bare per-figure `[ERROR]` + traceback.
- **A requested `--lead` whose wrfout isn't written yet** → a named
  `[SKIP] <case>: lead 6h → …Z not available yet`, and no task is emitted — so
  targeting a lead WRF hasn't reached (an in-progress run) is safe, and re-running
  once that output lands picks it up.

This is the key robustness change: the shared `case_study.run_figure_pipeline` still
catches unexpected exceptions, but expected mismatches are now gated at build time.

## Case TOML schema

```toml
[case]
slug = "pelican2013"                 # used for the cross-case compare/ output dir
label = "Pelican 2013"               # figure titles / domains-map title
archive_dir = "…/wrf_archive"        # BRC_WRF_ARCHIVE overrides this
run_subdir = "full6h"                # <archive_dir>/<run.dir>/<run_subdir>/run_*/
annotation = "pelican2013 | brc-tools"
crest_m = 2200.0                     # crest height for upper-air / heat-deficit
profile_hours = [12]                 # hours for the θ(z) profile family
sounding_hour = 12                   # analysis hour for station skew-Ts
upper_pressure_hpa = 600.0           # pressure surface for the synoptic T-advection map
upper_adv_domain = "outer"           # compute that map on "outer" (clean) | "inner" nest
focus_point = { name = "Horsepool", lat = 40.144, lon = -109.467 }
surface_vars = [                     # multi-domain surface panels (order preserved)
  { key = "theta2m", style = "theta_2m",      wind = true  },
  { key = "t2",      style = "temp_2m",        wind = true  },
  { key = "wspd10",  style = "wind_speed_10m", wind = true  },
  { key = "snow",    style = "snow_depth",     wind = false },
  { key = "pblh",    style = "pblh",           wind = false },
]

[waypoints]                          # markers on maps + labels along cross-sections
Horsepool = { lat = 40.144, lon = -109.467 }
Vernal    = { lat = 40.455, lon = -109.530 }
# quote names with spaces: "Pelican Lake" = { lat = 40.1808, lon = -109.6810 }
# A waypoint within ~6 km of a section line is labelled on that section at its distance.

[soundings]
stations = ["KSLC", "KGJT", "KRIW"]  # RAOB proxies (from brc_tools.api.soundings)
ic_cases = ["gfs", "nam"]            # cases that get station skew-Ts

[runs]                               # case key -> archived run dir + label
gfs = { dir = "pelican2013_gfs_3_1_333m_75lev", label = "GFS 2-way" }
nam = { dir = "pelican2013_nam_3_1_333m_75lev", label = "NAM 2-way" }

[[differences]]                      # difference families (a minus b)
a = "gfs"; b = "nam"                 # (illustrative — see the study's case file for the real list)
tag = "GFS-NAM"
dir = "diff_gfs_nam"                 # output subdir (default: slug of tag)
feedback = false                     # true tightens the diff colour limit (small-signal)
sections = true                      # also emit EW/NS θ difference sections
limit = 4.0                          # optional fixed ±K scale (shares one scale across a family)

[map]                                # optional Natural-Earth reference overlays (fail-soft)
states = true                        # state / province borders
roads  = true                        # US highways (10m Major/Secondary Highway)
rivers = true                        # river centrelines (incl. the Green River)
lakes  = true                        # lakes / reservoirs

[style]                              # optional; fixed shared scales are the default
autoscale = false                    # true -> data-driven vmin/vmax (via shared_range)
# [style.overrides.theta_2m]         # or override one variable's fixed scale
# cmap = "RdYlBu_r"; vmin = 270; vmax = 290
```

Recognised `surface_vars` keys: `theta2m`, `t2`, `wspd10`, `snow`, `pblh`. `style`
values name entries in `brc_tools/visualize/style.py::VAR_STYLES`. A difference `limit`
is a symmetric ±K colour bound; omit it to fall back to the built-in default (or the
tighter `feedback` default). The `[map]` overlays need the shapefiles staged with
`scripts/fetch_basemap.py` (see above); an unstaged layer is silently skipped.

## Colour scales

Fixed shared scales (`VAR_STYLES`) are the default so figures across cases/domains/
hours stay directly comparable. A case may opt into per-variable overrides or
data-driven autoscale via the `[style]` table; `style.resolve_style(key, overrides,
autoscale)` applies the policy (autoscale sets `vmin`/`vmax` to `None`, letting the
renderers' `shared_range` path fill them in).

## Load-bearing seams (do not break)

- `brc_tools.visualize.grid` (`plot_grid_field`, `plot_vertical_section`) is imported
  by **brc-wrf** — signatures are frozen.
- `brc_tools.nwp.wrf_output` public signatures are extended only (the three helpers
  `discover_domains` / `grid_spacing_label` / `point_in_domain` are additive).
- `brc_tools.nwp.case_study.run_figure_pipeline` is imported by other case studies —
  unchanged; skips are handled at build time, not by editing it.

## Tests

`tests/test_wrf_figures.py` exercises the engine on a synthetic **non-pelican** run
(2 nests, shifted region, off-grid focus point, a domain missing `SNOWH`) written to
disk by `tests/_wrf_synthetic.write_synthetic_run`, asserting domain-aware task
assembly and named skips. `tests/test_wrf_output.py` covers the three new helpers and
`tests/test_style.py` covers `resolve_style`.

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
  timeseries}.py` + `style.py`. These consume plain numpy and are reused unchanged.

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
```

Families: `domains, section, upperair, surface, difference, profile, skewt,
heatdeficit` (or `all`). Heavy batches run on SLURM (per `docs/CHPC-REFERENCE.md`);
the case's own repo owns the sbatch wrapper. Soundings need a network node — run
`scripts/fetch_soundings.py` first and pass `--sounding-cache`.

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
focus_point = { name = "Horsepool", lat = 40.144, lon = -109.467 }
surface_vars = [                     # multi-domain surface panels (order preserved)
  { key = "theta2m", style = "theta_2m",      wind = true  },
  { key = "t2",      style = "temp_2m",        wind = true  },
  { key = "wspd10",  style = "wind_speed_10m", wind = true  },
  { key = "snow",    style = "snow_depth",     wind = false },
  { key = "pblh",    style = "pblh",           wind = false },
]

[waypoints]                          # markers overlaid on maps
Horsepool = { lat = 40.144, lon = -109.467 }
Vernal    = { lat = 40.455, lon = -109.530 }

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

[style]                              # optional; fixed shared scales are the default
autoscale = false                    # true -> data-driven vmin/vmax (via shared_range)
# [style.overrides.theta_2m]         # or override one variable's fixed scale
# cmap = "RdYlBu_r"; vmin = 270; vmax = 290
```

Recognised `surface_vars` keys: `theta2m`, `t2`, `wspd10`, `snow`, `pblh`. `style`
values name entries in `brc_tools/visualize/style.py::VAR_STYLES`.

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

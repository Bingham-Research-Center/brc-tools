# Handoff — make the WRF figure driver dataset-agnostic

**Task (next session):** `scripts/pelican_figures.py` renders the pelican2013 case
family well, but it hardcodes assumptions about *this* dataset (3 nests, this
region, these variables, this time window). Goal: separate the **pelican2013
config** from a reusable **engine** so the driver renders a *different* WRF run
(other domain count, region, levels, variables, time range) without editing task
functions — and fails *loudly* on a genuine mismatch instead of silently skipping.

The reader/derivations (`brc_tools/nwp/wrf_output.py`) and the renderers
(`brc_tools/visualize/*`) are already largely general; the coupling lives in the
**driver** and in a couple of style/threshold constants. Scope this to the driver
first.

## What is hardcoded to pelican2013 (audit)

`scripts/pelican_figures.py`:
- **Domain count = 3.** `task_surface` and `task_domains` iterate a literal
  `[(1,"d01 (3 km)"),(2,"d02 (1 km)"),(3,"d03 (333 m)")]`; `section`/`upperair`/
  `skewt`(Horsepool) assume d03 is the innermost and stations live in d01. A 2- or
  4-nest run breaks or mislabels. → discover domains via `glob wrfout_d0N`; pull the
  grid-spacing label from the wrfout `DX` global attr instead of the literal strings.
- **`task_domains` hardcodes `run_dir("nam")`** — dies if there is no `nam` case.
  → use the first available case.
- **Region/point constants:** `HORSEPOOL`, `CREST_M=2200`, `WAYPOINTS`
  (Horsepool/Vernal/Roosevelt), section EW/NS through basin centre. Off-region data
  → `extract_column` silently returns an edge cell; the crest mask/interp is wrong.
  → parameterise per case; **validate the point is inside the domain** and warn if not.
- **`SURFACE_VARS`** assumes `SNOWH`, `PBLH`, `T2`, `U10/V10`, `QVAPOR` exist. A run
  without them raises `KeyError`, which `run_figure_pipeline` swallows as a per-figure
  `[ERROR]` — so a whole variable silently vanishes. → probe variable presence and log
  an explicit skip, or gate `SURFACE_VARS` on what the file has.
- **`CASES`, `SOUNDING_STATIONS`, `IC_CASES`, `ARCHIVE`** are all pelican2013-specific.
- **Time window:** `list_valid_times` is data-driven (good), but `times_for` filters by
  integer hour and `profile`/station-`skewt` assume a `12`Z launch exists.
- **Difference families** name specific case pairs (`gfs`/`nam`, `nam`/`nam_oneway`,
  terrain pairs). Fine as pelican config; should move into the config, not the engine.

`brc_tools/visualize/style.py`:
- **`VAR_STYLES` fixed vmin/vmax/cmap** are tuned to this case's ranges (a fair-comparison
  choice). A different season/region/regime will clip. → allow per-case overrides or an
  opt-in autoscale; keep fixed scales the default for within-case comparison.

## Suggested shape

1. A `CaseConfig` (dataclass or a small TOML read at startup): `archive_dir`, `label`,
   `focus_point`, `crest_m`, `waypoints`, `sounding_stations`, `ic_cases`, `surface_vars`,
   `section_defs`, and the `difference` pairs. `CASES` becomes a dict of these.
2. Make the engine **domain-aware from the data**: enumerate present domains, label from
   `DX`, treat "innermost"/"outermost" by index, not literal 1/2/3.
3. **Preflight validation** helper: point-in-domain, variables-present, times-present →
   collect and print a clear report; skip with a reason rather than a bare `[ERROR]`.
4. Keep the cross-repo load-bearing seams intact: `brc_tools.visualize.grid`
   (`plot_grid_field`, `plot_vertical_section`) is imported by **brc-wrf**; do not change
   those signatures. `wrf_output.py` is already general — extend, don't special-case.

## How to prove it (acceptance)

Add a test/fixture exercising the engine on a **non-pelican shape**: a small synthetic (or
downsampled) wrfout with a *different domain count and region* — assert `build_tasks`
produces sensible tasks, points-outside-domain warn, and a missing `SNOWH` logs a named
skip rather than a silent drop. The existing `tests/` suite (152 passed, 2 skipped as of
2026-07-08) is the baseline; keep it green.

## Context / state at handoff (2026-07-08)

- pelican2013 full figure set is rendered and clean (5 cases × 8 families, 374 figs;
  `nam_terrain3s` fine-terrain case + `diff_terrain_fine` added; heat-deficit/profile
  5-series style fixed). Canonical doc: `docs/WRF-ANALYSIS-FIGURES.md`.
- Real soundings are wired: `brc_tools/api/soundings/` (IGRA2 default, Wyoming fallback)
  + station skew-Ts (KSLC/KGJT/KRIW proxies in d01). `docs/API-CLIENTS.md`.
- This robustness pass is **not** started — it is this file.

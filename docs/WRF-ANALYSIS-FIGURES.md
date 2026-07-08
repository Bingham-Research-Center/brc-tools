# WRF analysis figures — pelican2013 (moved)

The publication-figure system is now a **dataset-agnostic engine** in brc-tools plus a
**declarative case** in the study repo. This doc is a pointer.

- **Engine + generic CLI + TOML schema + preflight/skip semantics** →
  [`docs/WRF-FIGURE-ENGINE.md`](WRF-FIGURE-ENGINE.md)
  (`brc_tools/nwp/wrf_figures.py`, `scripts/wrf_figures.py --config <case.toml>`).
- **pelican2013 case config** (which runs, focus point, difference pairs, RAOB
  stations) → `../wrf-nudge-ozone-air2026/cases/pelican2013.toml` + its SLURM wrapper
  `../wrf-nudge-ozone-air2026/slurm/pelican_figures.slurm`.
- **pelican2013 science** (cases table, terrain-source ladder, findings, caveats) →
  `../wrf-nudge-ozone-air2026/experiments/pelican2013-cold-pool-figures.md`.

Study-specific figure configs and findings live with the study, never in brc-tools;
brc-tools owns only the reusable engine and renderers (`brc_tools/visualize/*`).

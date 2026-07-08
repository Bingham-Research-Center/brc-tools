#!/usr/bin/env python
"""Generate publication figures for a WRF case described by a TOML config.

This is the dataset-agnostic driver: all study-specific choices (which runs, the
focus point, crest height, waypoints, surface variables, difference pairs, RAOB
stations) live in ``--config <case.toml>``; the reusable engine is
``brc_tools.nwp.wrf_figures``.  Nests are discovered from the data and a genuine
mismatch (missing variable, off-grid focus point) is reported as a named skip
rather than a silent per-figure error.

Examples
--------
    # everything for the pelican2013 case (config lives in the experiment repo)
    python scripts/wrf_figures.py --config ../wrf-nudge-ozone-air2026/cases/pelican2013.toml

    # a subset
    python scripts/wrf_figures.py --config <case.toml> \
        --case nam --figure section,surface --time 12,18

Outputs route OUTSIDE the repo (per-case -> ``<run>/full-figures/<family>/``;
cross-case -> ``$BRC_WRF_ARCHIVE/<slug>_pub_figures/compare/<family>/``); override
with ``--output-dir``.  Run heavy batches on SLURM.  Soundings need a network node:
run ``scripts/fetch_soundings.py`` first and pass ``--sounding-cache``.  See
``docs/WRF-FIGURE-ENGINE.md``.
"""

from __future__ import annotations

import argparse

from brc_tools.nwp.case_study import run_figure_pipeline
from brc_tools.nwp.wrf_figures import FAMILIES, CaseConfig, Selection, build_tasks
from brc_tools.visualize.style import use_publication_style


def _list_arg(value: str) -> list[str] | None:
    return None if value == "all" else value.split(",")


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--config", required=True, help="path to the case TOML")
    ap.add_argument("--case", default="all", help="case key(s) from the config, or 'all' (comma-separated ok)")
    ap.add_argument("--figure", default="all", help="|".join(FAMILIES) + "|all (comma-separated ok)")
    ap.add_argument("--time", default="all", help="hour(s) or 'all' (comma-separated ok)")
    ap.add_argument("--output-dir", default=None, help="override output root (else routed by case)")
    ap.add_argument("--run", default=None, help="specific run_* dir name (default: latest); single-case use")
    ap.add_argument("--sounding-cache", default=None, help="parquet from fetch_soundings.py (offline obs)")
    args = ap.parse_args()

    cfg = CaseConfig.from_toml(args.config)
    selection = Selection(
        cases=_list_arg(args.case),
        families=_list_arg(args.figure),
        time=args.time,
        output_dir=args.output_dir,
        run_override=args.run,
        sounding_cache=args.sounding_cache,
    )
    use_publication_style()
    tasks = build_tasks(cfg, selection)
    print(f"wrf_figures: {cfg.label}: {len(tasks)} figure task(s)")
    run_figure_pipeline(tasks)
    print("done")


if __name__ == "__main__":
    main()

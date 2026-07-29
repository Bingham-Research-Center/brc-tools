---
name: wrf-basin-winds
description: Render basin-winds-style figures (10 m wind plan views + terrain-filled cross-sections along named transects, with locator insets) from a WRF run's wrfout files on CHPC SLURM — including a run that is still writing. Use when asked for better-than-quicklook WRF images for a case/time, or for the WRF version of /basin-winds.
---

# WRF basin-winds figures

The WRF counterpart of ub-wx's `/basin-winds`: per nest, a plan-view surface map
(10 m wind + barbs + terrain + towns + Natural-Earth overlays) plus terrain-filled
wind curtains along named A→B transects with the geographic locator inset. Same
renderers as the HRRR case (`brc_tools.visualize.nwp_maps`), fed by the wrfout
adapter `brc_tools/nwp/wrf_section.py`, so sections keep the model's **native eta
levels** instead of being flattened onto isobaric surfaces.

Engine + TOML schema: `docs/WRF-WINDS.md`. For a study's publication figure set
(grid-aligned EW/NS sections, difference maps, heat-deficit diagnostics) use
`/wrf-full-figures` instead — different engine, different job.

## Steps

1. **Find the run and its case TOML.** Configs live in the repo owning the case —
   e.g. `~/gits/ub-wx/experiments/20260424-ashley-drainage-120m/figures.toml`. A
   different run of the same case needs no edit: pass `--run-dir <...>/wrf_run`.
   New case → new TOML (schema + a worked example in `docs/WRF-WINDS.md`).
2. **Pick the time(s).** `--hourly` sweeps every whole hour written so far — the
   right choice for "show me the run so far"; `--all` adds sub-hourly times.
   `--valid YYYY-MM-DD_HH:MM` or `--lead <minutes-after-init>` pick one. With none
   of those it renders the latest valid time present on *every* requested domain,
   which is what you want for a single look at a running job (a 3 km parent on
   hourly output lags a 600 m nest on 5-minute output).
   - `ls <run>/wrfout_d0*_* | tail` to see how far the run has got.
   - Existing figures are overwritten, so re-running as the job advances is safe.
   - Ask the user which time only if the run offers a genuinely different choice;
     otherwise take the latest common one and say which you used.
   - **A sweep that crosses sunset crosses regimes**: one `w_exag` cannot serve
     both a convective afternoon and a drainage night. Check the last hour and say
     so if a second pass with `--w-exag` is warranted.
3. **Submit on the DTN, never a login node.** Two reasons this is not optional:
   `lawson-group6` is mounted **read-only** on the notchpeak login nodes, so
   figures reach group storage only from a compute or DTN node; and `lawson-np` is
   a single node, so if a WRF run is occupying it — the usual reason to want these
   figures — a job queued there waits for the very run it is meant to monitor.
   ```
   sbatch scripts/wrf_winds.dtn.slurm --config <case.toml> [--run-dir <run>] \
          [--valid ...|--lead ...] [--domain N] [--w-exag X] [--output-dir <dir>]
   ```
   Report the job id and the output path; check with `squeue -j <jobid>` and the
   `.out` on scratch. ~1 min per (nest × time) for a 600 m nest.
4. **Check the output.** Read one plan view and one section. The two things that
   go wrong first:
   - **All vectors vertical** on a section → `w_exag` is set for the wrong regime.
     A convective afternoon wants ~10; a quiescent drainage night wants ~100.
     Re-render with `--w-exag`, don't edit the TOML.
   - **Locator inset over the town labels** → move `loc_rect` into the panel's dead
     space (usually inside the terrain fill).
5. **Promote the keepers.** Scratch holds the mass output; copy the best few to
   `$UB_WX_FIGS_KEEP` / group6 — from the same job or a DTN, not the login node.

## Notes

- Reads **both** wrfout filename conventions, including `nocolons = .true.`
  (`..._21_00_00`). `brc_tools.nwp.wrf_output` — and therefore the
  `/wrf-full-figures` engine — assumes colons and will report "no wrfout" on a
  nocolons run.
- One nest can carry several views: give each `[[domains]]` entry its own `tag`
  (e.g. a full-extent `d02` plus a zoomed `d02_ashley`).
- Colour scales come from `brc_tools.visualize.style`, which is tuned for **winter
  cold pools**. Any warm-season case needs `[style.overrides.<var>]` in its TOML.
- Transect endpoints must lie inside the nest being cut. A line running off the
  grid silently samples the edge column for the rest of its length — sample `HGT`
  along a new transect before trusting it.
- Basemap overlays need `BRC_TOOLS_BASEMAP_DIR` (the SLURM wrapper points at the
  staged group6 cache); missing layers are skipped, never fatal.

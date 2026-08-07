---
name: wrf-convective
description: Render convective diagnostics from a WRF run on CHPC SLURM — composite reflectivity, surface mesoanalysis (theta-e, convergence, moisture-flux convergence), gust swaths, updraft helicity, reflectivity sampled on a real radar's beam surfaces with the observed scan beside it, skew-T with parcel path, hodographs, and station verification from tslist. Use when asked to diagnose a simulated storm, compare a run against radar, test a gust-swath width, or produce convective figures for a case.
---

# WRF convective diagnostics

Storm-scale diagnostics from a `wrfout` run, including the two things a fixed-height
plot cannot give you: **simulated reflectivity sampled on a named WSR-88D's beam
surfaces**, and the surface mesoanalysis showing what the storm is running into.

Engine + TOML schema: **`docs/WRF-CONVECTIVE.md`**. Method, and the ways a sweep
goes wrong: **`docs/VISUAL-SUITE-SOP.md`** — read it before a first sweep on a new
case.

This is **not** the drainage-wind engine (`/wrf-basin-winds`) nor the pelican
publication set (`/wrf-full-figures`) — three engines, three jobs, and only this one
knows about radar beams.

## Families

`--figure` is repeatable; the default is **all eight**, which is almost never what
you want at a sub-hourly cadence.

| `--figure` | reads | answers |
|---|---|---|
| `surface` | `wrfout` | where is the storm — composite reflectivity, gust swath, updraft helicity, echo top, vertical vorticity |
| `meso` | `wrfout` | what is it running into — θₑ, dewpoint, dewpoint depression, 10 m convergence, moisture-flux convergence, θₑ gradient |
| `aux` | `auxhist<N>` | the same, at the high-cadence stream's interval — the only way to see a feature a 10-minute history aliases |
| `section` | `wrfout` | vertical structure — reflectivity / `w` / θ curtains on native eta levels |
| `beam` | `wrfout` | **what the radar would have seen** — reflectivity on real beam surfaces, optionally with the observed scan beside it |
| `sounding` | `wrfout` | the environment — skew-T with parcel path and LCL/LFC/EL, plus a height-banded hodograph |
| `verify` | `tslist` | did it happen at the right time at a real station (every model step, ~3 s) |
| `track` | `wrfout` | where did the strongest echo go — a **CSV**, not a figure; this is what sizes a nest |

## Steps

**Do not guess the case, the time window, the cadence or the radar.** Each changes
what the job costs and what it can claim. Ask, then say back what you chose.

1. **Case, config and run** *(ask the user)*. The case TOML lives in the repo that
   owns the case, never in brc-tools. A different run of the same case needs no
   edit: `--run-dir <...>/wrf_run`. New case → new TOML (`docs/WRF-CONVECTIVE.md`).
   - `ls <run>/wrfout_d0*_* | tail` shows how far the run has got. Report it.

2. **Families** *(ask the user)*, from the eight above — not everything. Frame them
   as questions, not flags. Worth saying out loud:
   - `verify` first if there is an outflow or boundary to **time**; `tslist` is the
     only stream fine enough to resolve a passage the history aliases.
   - `beam` for anything to be compared against a real radar.
   - `meso` when the question is *why here* rather than *where*.
   - `track` writes a CSV, and is radius-sensitive — see Notes.

3. **Times and cadence** *(ask the user)*. This is the choice that sizes the job.
   - one time: `--valid YYYY-MM-DD_HH:MM` or `--lead <minutes after init>`;
   - a window: `--start` / `--end` plus `--every MIN` (`--hourly`, `--all`).
   - With no time flag it takes the latest time on *every* requested domain.
   - **Convert the answer into a figure count before submitting.** At ~2–4 min per
     nest-time for a 600 m nest, an unbounded 1-minute sweep of a 5 h run is 301
     times per domain — thousands of figures. `--figure aux` on its own sweeps the
     auxiliary stream's own (much denser) times.

4. **`--dry-run` first.** Prints the exact figure list, writes nothing. Report the
   count and get a go-ahead before submitting.

5. **Submit on the DTN, never a login node.** `lawson-group6` is read-only on the
   notchpeak login nodes, and `lawson-np` is a single node — a figure job queued
   there waits for the very run it is meant to diagnose.
   ```
   sbatch scripts/wrf_convective.dtn.slurm --config <case.toml> \
          [--figure beam --figure meso] \
          [--valid ... | --start ... --end ... --every MIN] \
          [--domain 2] [--output-dir <dir>]
   ```
   Report the job id and the output path.

6. **Check the exit code, then the `.err`, then the `[tally]` line.** Per-figure
   failures are caught so one bad panel cannot lose a run, but **any** failure exits
   non-zero and the tally is printed last. `--allow-errors` opts out. Never report
   success from the `.out` alone.

7. **Open one figure from every family before sweeping further.** One *per family*,
   not one in total: a family that was never smoke-tested is how a whole submitted
   job has been lost before. The five that go wrong first are the first five Notes
   below.

8. **Coverage, then re-runs.** `--report` summarises every `manifest_<jobid>.json`
   in the output root, per family and per status — the answer to "do we have all the
   plots?", which `find` cannot give. `--skip-existing` makes a re-run cheap and is
   safe against a still-writing run.

9. **Promote the keepers and write the finding.** Copy the few worth keeping to
   persistent group storage, from the job or a DTN — the brc-tools default is
   `$BRC_TOOLS_OUTPUT_DIR` (`lawson-group6/jrlawson/brc-tools-output`); a ub-wx case
   has its own `$UB_WX_FIGS_KEEP`, which is **unset outside that repo**, so do not
   reach for it by default. **No figure images in git.** Put the finding and its
   caveats in the case's `notes.md`.

## Notes — what goes wrong first

- **Everything dark blue / a pale wash over the whole domain** → a presentation
  floor is not applying. Clear air must be masked, not painted; reflectivity is
  masked below 5 dBZ and updraft helicity below 5 m² s⁻².
- **All section vectors vertical** → `w_exag` set for the wrong regime. One rule:
  `typical |u| ÷ typical |w|`, which puts the typical vector at 45°. A deep
  convective core wants ~5, a drainage night ~100. It is **not** the plot aspect.
  Derivation and table: `docs/WRF-WINDS.md`, which owns this knob. Re-render with
  `--w-exag`.
- **A swath 159 km wide** → you measured the whole domain. Over a 213 × 171 km
  footprint holding several storms the domain-wide answer is not a swath at all.
  Pass `near_waypoint`/`radius_km` in `[track]`.
- **`aux` skips a field** with a message about the history write → that field is a
  running maximum in that stream. `WSPD10MAX`, `UP_HELI_MAX`, `REFD_MAX` reset on
  the **history** write, so in a 1-minute stream they are partial maxima over the
  current 10-minute window. Read them from `wrfout`. Do not reach past the guard.
- **`beam` skipped entirely** → the run has no `REFL_10CM` (needs
  `do_radar_ref = 1`). **Empty `verify` panel** → no `tslist`, or the window is
  outside the run.
- **A `meso` panel named-skipped** → the run did not write an input it needs
  (`Q2`, `PSFC`, `T2`, `U10`/`V10`). Everything in that family is derived.
- Reads **both** `wrfout` filename conventions, including `nocolons = .true.`.
  Basemap overlays need `BRC_TOOLS_BASEMAP_DIR`; a missing layer is skipped.

## Claims discipline

Figures are how a forbidden claim gets made by accident. These hold for every case:

- **Quote the surface with every number.** A reflectivity value without its
  surface — column maximum, which beam tilt, what accumulation window — is not a
  measurement. On the Ashley run the same ground reads 47.6 dBZ as a column
  maximum, 44.1 on the 0.5° beam and 11.2 on the 1.2°: a 36 dBZ spread over
  identical ground. Never let a column maximum stand in for a beam value.
- **Never compare simulated reflectivity to a distant radar at a fixed height
  AGL.** Across one 600 m nest a single KGJX beam surface spans 2.0–13.7 km AGL.
  That claim belongs on a beam surface or nowhere.
- **Nominal elevation angles are not scanned angles.** Products reported at
  0.0 / 0.5 / 1.2° are scanned at −0.04 / 0.44 / 1.49°. Give the engine the nominal
  angle; it computes heights from the tilt actually scanned.
- **Check what the archive actually served.** Observed radar comes from IEM RIDGE
  Level-III, **elevation 1 (0.5°) only**; a signature at 0.0° or 1.2° has *no*
  observed counterpart for a 2025 date, and the panel is annotated `MODEL ONLY`
  when so. Say that rather than substituting 0.5°. Level-II would give every tilt
  but no archive serves it for October 2025 — see `docs/nwp/NWP-SOURCE-MATRIX.md`.
- **Model or measurement, on the figure.** Titles lead with `WRF`, `OBSERVED`, or
  `WRF vs OBS`. Carry that into the prose: "the model produced" and "the radar
  observed" are different sentences, and a `verify` panel that resolved no station
  is a model trace, not a verification.
- **Width, not peak, is usually the test.** A gust field strong at one point and
  quiet 3 km away is a narrow swath; a 20 km-wide field is a negative result even
  if its peak matches a report.
- **A case's own registry may forbid more.** Check the case `experiment.toml` /
  `notes.md` before writing a caption — an unofficial spotter report is a target,
  never a verification datum, and a resolution the run cannot represent is not
  evidence of absence.

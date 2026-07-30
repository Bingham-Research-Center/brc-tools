---
name: wrf-convective
description: Render convective diagnostics from a WRF run on CHPC SLURM — composite reflectivity, gust swaths, updraft helicity, reflectivity sampled on a real radar's beam surfaces, skew-T with parcel path, hodographs, and station verification from tslist. Use when asked to diagnose a simulated storm, compare a run against radar, test a gust-swath width, or produce convective figures for a case.
---

# WRF convective diagnostics

Storm-scale diagnostics from a `wrfout` run: reflectivity plan views and native-eta
cross-sections, **simulated reflectivity sampled on a named WSR-88D's beam
surfaces**, skew-T with a parcel path and LCL/LFC/EL, height-banded hodographs, and
surface verification from the `tslist` traces.

Engine + TOML schema: `docs/WRF-CONVECTIVE.md`. This is **not** the drainage-wind
engine (`/wrf-basin-winds`) nor the pelican publication set (`/wrf-full-figures`) —
three engines, three jobs, and only this one knows about radar beams.

## Steps

1. **Find the run and its case TOML.** Configs live in the repo owning the case,
   e.g. `~/gits/ub-wx/experiments/20251011-ashley-rotating-cell/figures.toml`. A
   different run of the same case needs no edit: pass `--run-dir <...>/wrf_run`.
   New case → new TOML (schema + a worked example in `docs/WRF-CONVECTIVE.md`).

2. **Pick the families, not everything.** `--figure` is repeatable and rendering
   all seven at a 1-minute cadence is a lot of figures for no benefit.
   - `--figure verify` first if the case has an outflow or boundary to time. It
     reads `tslist` (every model step, 3 s on a 600 m nest) and is the only stream
     that can resolve a passage a 10-minute history aliases.
   - `--figure beam` for anything compared against a real radar.
   - `--figure track` emits a **CSV**, not a figure — it is what sizes a nest.

3. **Pick the time(s).** `--valid YYYY-MM-DD_HH:MM` or `--lead <minutes>` for one;
   `--every 1` / `--hourly` / `--all` to sweep. With none of those it renders the
   latest time present on *every* requested domain, which is the right default for
   a job still writing.
   - `ls <run>/wrfout_d02_* | tail` to see how far the run has got.
   - Say which time you used. Ask only if the run offers a genuinely different
     choice.

4. **Submit on the DTN, never a login node.** `lawson-group6` is read-only on the
   notchpeak login nodes, and `lawson-np` is a single node — a figure job queued
   there waits for the very run it is meant to diagnose.
   ```
   sbatch scripts/wrf_convective.dtn.slurm --config <case.toml> \
          [--figure beam] [--valid ...|--every 1] [--domain 2] [--output-dir <dir>]
   ```
   Report the job id and the output path; check with `squeue -j <jobid>` and the
   `.out` on scratch. ~2-4 min per (nest × time) for a 600 m nest.

5. **Read one figure per family before sweeping.** The four things that go wrong
   first are in the Notes below.

6. **Promote the keepers.** Scratch holds the mass output; copy the best few to
   `$UB_WX_FIGS_KEEP` — from the job or a DTN, not the login node. **No figure
   images in git.**

## Notes

- **Never compare simulated reflectivity to a distant radar at a fixed height
  AGL.** Across one 600 m nest a single KGJX beam surface spans **2.0 to 13.7 km
  AGL**; the `beam` family exists for exactly this and prints the span in the
  annotation. If a case makes claims about what a radar saw, that claim belongs on
  a beam surface or nowhere.
- **Nominal elevation angles are not scanned angles.** Products reported at
  0.0 / 0.5 / 1.2° are scanned at −0.04 / 0.44 / 1.49°. Ask for the nominal angle;
  the engine resolves it and computes heights from the tilt actually scanned.
- **A `*_MAX` field skipped from the auxiliary stream is correct behaviour.**
  `WSPD10MAX`, `UP_HELI_MAX`, `REFD_MAX` reset on the **history** write, so in a
  1-minute stream they are partial maxima over the current 10-minute window. Read
  them from `wrfout`. Do not "fix" this by reaching past the guard.
- **Width, not peak, is usually the test.** A gust field strong at one point and
  quiet 3 km away is a narrow swath; a 20 km-wide field is a negative result even
  if its peak speed matches a report. Always pass `near`/`radius_km` in `[track]`
  and never quote a domain-wide extent as a swath width.
- **Colour limits are set from measured values**, not Plains intuition — Basin CAPE
  and shear ranges are far narrower. Retune in `[style.overrides.<var>]`, not in the
  shared table.
- **All section vectors vertical** → `w_exag` is set for the wrong regime
  (convective ~5, drainage night ~100). Re-render with `--w-exag`.
- **Everything dark blue** → the reflectivity mask floor is not applying; clear air
  must be masked, not painted.
- Reads **both** `wrfout` filename conventions including `nocolons = .true.`.
- Basemap overlays need `BRC_TOOLS_BASEMAP_DIR` (the SLURM wrapper points at the
  staged group6 cache); missing layers are skipped, never fatal.
- Fetching real NEXRAD volumes: check the transport table in
  `docs/nwp/NWP-SOURCE-MATRIX.md` first. Several obvious routes do not work, and
  the archive that does is date-limited.

## Claims discipline

A case's `experiment.toml` may forbid specific claims, and figures are how forbidden
claims get made by accident. For the Ashley rotating-cell case specifically: nothing
about a funnel (600 m cannot represent one, and its absence is not evidence); the
unofficial 30 m/s spotter report is a **target, never a verification datum**; and no
observed velocity couplet may be described as low-level, because nothing below
~3 km AGL over the Basin was sampled at all. Check the case registry before writing
a caption.

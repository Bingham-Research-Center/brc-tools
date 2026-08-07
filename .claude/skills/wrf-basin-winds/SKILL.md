---
name: wrf-basin-winds
description: Render basin-winds figures from a WRF run on CHPC SLURM — 10 m wind and cold-pool plan views, terrain-filled cross-sections along named transects (including the wind component crossing the section), theta/humidity profiles with a wind panel, and 3-D isentrope cold-pool views — including from a run that is still writing. Use when asked for better-than-quicklook WRF images for a case/time, for drainage or cold-pool diagnosis, or for the WRF version of /basin-winds.
---

# WRF basin-winds figures

Sensible-weather and cold-pool diagnostics from a `wrfout` run. Sections keep the
model's **native eta levels** rather than being flattened onto isobaric surfaces —
for a drainage layer tens of metres deep that is the difference between seeing the
feature and interpolating it away.

Engine + TOML schema: **`docs/WRF-WINDS.md`**. Method, and the ways a sweep goes
wrong: **`docs/VISUAL-SUITE-SOP.md`** — read it before a first sweep on a new case.

Three WRF engines, three jobs. Storm diagnosis (reflectivity, radar beams,
soundings) is `/wrf-convective`; a study's publication set is `/wrf-full-figures`.
Using the wrong one wastes a job and produces a misleading figure.

## Families

`--figure` is repeatable; the default is all five.

| `--figure` | answers |
|---|---|
| `topdown` | what does the surface look like — wind, θ₂ₘ, PBLH, surface decoupling, snow, 10 m convergence, and the derived fog / cloud / surface-energy-budget fields |
| `section` | what is the vertical structure along this line — terrain-filled curtain on native eta levels |
| `profile` | how deep is the stable layer here, and is the air above it dry enough to mix down |
| `view3d` | how far has the cold pool filled the basin |
| `tracers` | **where did this air come from** — dominant-source curtains, per-source share curtains, a stacked source spectrum at a point, and an origin map. Needs a run seeded with `tracer_opt`; named-skipped otherwise |

A sixth job, and a **separate engine** because it spans the whole run rather than
one valid time: `scripts/wrf_timeheight.py` draws time–height sections at `tslist`
stations from the per-station column profiles, at model-timestep cadence. That is
the family that answers *when* — onset, deepening, break-up. Same TOML, its own
`[[timeheight]]` entries, its own DTN wrapper (`wrf_timeheight.dtn.slurm`).

## Steps

**Do not guess the case, the time window or the cadence.** Every one of them
changes what the job costs and what it answers, and none is recoverable from the
run directory alone. Ask, then say back what you chose.

1. **Case, config and run** *(ask the user)*. The case TOML lives in the repo that
   owns the case, never in brc-tools. Ask which case; if they name a run rather
   than a case, `--run-dir <...>/wrf_run` reuses one config across runs. New case
   → new TOML (schema + worked example in `docs/WRF-WINDS.md`).
   - `ls <run>/wrfout_d0*_* | tail` shows how far the run has got. Report that.

2. **Families** *(ask the user)* — all four above, or a subset. Say what each one
   would answer for *their* question rather than listing flags.

3. **Times and cadence** *(ask the user)*. This is the choice that sizes the job.
   - one time: `--valid YYYY-MM-DD_HH:MM` or `--lead <minutes after init>`;
   - a window: `--start` / `--end` plus `--every MIN` (`--hourly` = `--every 60`,
     `--all` = the run's native interval).
   - With no time flag it renders the latest time present on *every* requested
     domain — a reasonable default against a running job, but say so explicitly.
   - **Convert their answer into a figure count before submitting**: roughly
     (times × views × families). At ~1 min per nest-time for a 600 m nest, a
     15-minute cadence over 12 h on two views is already ~100 minutes of work.
   - **A window crossing sunset crosses regimes.** One `w_exag` cannot serve a
     convective afternoon and a drainage night — see step 7.

4. **`--dry-run` first.** It prints the exact figure list and writes nothing —
   no PNGs, no manifest. Report the count back to the user and get a go-ahead
   before submitting. This is cheaper than discovering the count from the queue.

5. **Submit on the DTN, never a login node.** Two reasons, neither optional:
   `lawson-group6` is mounted **read-only** on the notchpeak login nodes, so
   figures reach group storage only from a compute or DTN node; and `lawson-np` is
   a single node, so a job queued there waits for the very run it is meant to
   monitor.
   ```
   sbatch scripts/wrf_winds.dtn.slurm --config <case.toml> [--run-dir <run>] \
          [--figure section --figure profile] \
          [--valid ... | --start ... --end ... --every MIN] \
          [--domain N] [--w-exag X] [--output-dir <dir>]
   ```
   Report the job id and the output path.

6. **Check the exit code, then the `.err`, then the `[tally]` line.** A per-figure
   failure is caught so one bad panel cannot lose a run, but **any** failure now
   exits non-zero and the tally is the last thing printed. `--allow-errors` opts
   out when some families are expected to fail. Do not report success from the
   `.out` alone.

7. **Open one figure from every family before sweeping further.** Not one figure —
   one *per family*. A family that was never smoke-tested is how a whole submitted
   job has been lost before. What to look at:
   - **All section vectors vertical** → `w_exag` set for the wrong regime. The rule
     is `typical |u| ÷ typical |w|` (`docs/WRF-WINDS.md`); re-render with
     `--w-exag`, do not edit the TOML.
   - **A curtain that is flat and featureless over part of its length** → the
     transect leaves the nest there. It is blanked, not fabricated, and the
     preflight says how far along it departs.
   - **Locator inset over the town labels** → move `loc_rect` into the panel's dead
     space, usually inside the terrain fill.
   - **A plan view that is uniformly one colour** → the scale is tuned for winter
     cold pools; a warm-season case needs `[style.overrides.<var>]`.

8. **Coverage, then re-runs.** `--report` summarises every `manifest_<jobid>.json`
   in the output root, per family and per status — this is the answer to "do we
   have all the plots?", which `find` cannot give because it cannot distinguish a
   figure that failed from one never asked for. `--skip-existing` makes a re-run
   cheap; a figure older than any file it derives from regenerates, so it is safe
   against a still-writing run.

9. **Promote the keepers and write the finding.** Copy the few worth keeping to
   persistent group storage, from the job or a DTN, not the login node — the
   brc-tools default is `$BRC_TOOLS_OUTPUT_DIR` (`lawson-group6/jrlawson/brc-tools-output`);
   a ub-wx case has its own `$UB_WX_FIGS_KEEP`, which is **unset outside that
   repo**, so do not reach for it by default. **No figure images in git.** Put the
   finding, with its caveats, in the case's `notes.md`.

## Reading a cross-section

The fill and the arrows are **different measurements on the same plane**, and which
fill was used is a real choice, not a default to accept:

- `shade = "speed"` is `|V|` — a **magnitude with no direction**, so a cross-valley
  gale and an along-valley jet look identical.
- `shade = "along"` is the in-plane component, + toward B — what the arrows draw.
- `shade = "normal"` is the flow **crossing** the section, + into the page, on a
  diverging scale. For a west-to-east transect this is the north–south component,
  and it is the only fill that shows cross-valley exchange.

Every curtain carries an orientation stamp (`A→B 090° (W→E) | into page = N`) and
says its vectors are in-plane only. Quote the fill when describing one: "12 m s⁻¹"
off a `speed` curtain says nothing about direction.

## Notes

- Reads **both** wrfout filename conventions, including `nocolons = .true.`
  (`..._21_00_00`). `brc_tools.nwp.wrf_output` — and therefore the
  `/wrf-full-figures` engine — assumes colons and reports "no wrfout" on a
  nocolons run.
- One nest can carry several views: give each `[[domains]]` entry its own `tag`
  (e.g. a full-extent `d02` plus a zoomed `d02_ashley`).
- **Context is opt-in per case**: `[map]` switches `roads`, `counties`, `cities`
  and friends, and `waypoint_group` names a curated `lookups.toml` group. A figure
  for anyone who does not already know the basin should have terrain, roads and
  named towns on it. Overlays need `BRC_TOOLS_BASEMAP_DIR` (the SLURM wrapper
  points at the staged group6 cache); a missing layer is skipped, never fatal.
- **Profiles are not skew-Ts, deliberately.** A skew-T is built to read a parcel
  path; here the question is how deep the stable layer is, which θ-versus-height
  answers directly. Humidity rides on a twin axis because θ alone cannot tell a
  dry residual layer from a moist one at the same temperature — and which it is
  decides whether the layer mixes out.
- `pblh` is 0 at f00. That is a real value, not a missing field.
- **Say which time you rendered, every time.** A figure the user did not choose
  the time for is a figure they cannot check.

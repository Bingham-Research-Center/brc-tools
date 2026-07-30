# SOP: producing a suite of WRF visuals, and the ways it goes wrong

Written 2026-07-30 after building the convective engine and rendering the Ashley
rotating-cell case. It is a review of the *method*, not a schema — each engine's
schema lives in its own doc (`WRF-FIGURE-ENGINE.md`, `WRF-WINDS.md`,
`WRF-CONVECTIVE.md`).

The pattern is settled and works: **capability in `brc-tools`, configuration in the
case repo, figures outside every checkout, heavy work on a DTN.** What follows is
the operating procedure plus an honest list of the gaps still in it.

---

## The procedure

1. **Pick the engine by the question**, not by the case. Three exist and they are
   not interchangeable — see the table in the top-level `README.md`. Using the
   publication engine for storm diagnosis, or the winds engine for a radar
   comparison, wastes a job and produces a misleading figure.
2. **Write or find the case TOML** in the repo that owns the case. Configuration
   only: which fields, levels, limits, endpoints, stations. If you find yourself
   needing a *definition* — what a field is, where a station is, how a beam height
   is computed — it belongs in `brc-tools`.
3. **Render one time, one family first — for EVERY family you intend to sweep.**
   `--valid <t> --figure <one>`. Look at the output. Most mistakes are visible in the
   first figure and cost a whole sweep if they are not caught there. This is not
   optional advice: error 10 below reached a submitted job precisely because one of
   seven families was never smoke-tested.
4. **Narrow before you sweep.** `--figure` to select families, `--domain` to select
   nests, `--start`/`--end` to bound the window. A 1-minute sweep of a 5 h run is
   301 times per domain; unbounded, that is thousands of figures.
5. **Submit to the DTN** (`scripts/*.dtn.slurm`). `lawson-group6` is read-only on
   the notchpeak login nodes, and `lawson-np` is the single node a WRF run occupies.
6. **Check the `.err` before assuming success.** Family-level failures are caught
   and printed per figure, so a job can exit 0 having rendered nothing useful.
7. **Promote the keepers** to `$UB_WX_FIGS_KEEP`. Scratch is the mass output; no
   figure images in git.
8. **Write the finding, with its caveats, into the case's `notes.md`.**

## Worked invocation — the Ashley suite

```bash
CFG=$UB_WX/experiments/20251011-ashley-rotating-cell/figures.toml
OUT=$UB_WX_SCRATCH/figures/20251011-ashley-rotating-cell

# history sweep: model families across the whole run at 10-minute cadence
sbatch scripts/wrf_convective.dtn.slurm --config $CFG --output-dir $OUT \
    --figure surface --figure section --figure beam --figure sounding --every 10

# high-cadence windows: only the inner nest carries auxhist2
sbatch scripts/wrf_convective.dtn.slurm --config $CFG --output-dir $OUT \
    --figure aux --domain 2 --every 1 --start 2025-10-12_01:00 --end 2025-10-12_02:00
sbatch scripts/wrf_convective.dtn.slurm --config $CFG --output-dir $OUT \
    --figure aux --domain 2 --every 1 --start 2025-10-12_02:10 --end 2025-10-12_02:55

# window products: verification panels and the centroid table
sbatch scripts/wrf_convective.dtn.slurm --config $CFG --output-dir $OUT \
    --figure verify --figure track --every 10
```

---

## Errors found in the method itself

These were real, and each one produced a plausible-looking wrong answer or a dead
job. All are fixed; they are recorded because the *class* of mistake will recur.

| # | Error | Why it mattered | Status |
|---|---|---|---|
| 1 | An absent per-domain stream was **fatal** to a sweep | `auxhist2_interval = 0, 1` writes the high-cadence stream on the inner nest only, so listing the parent for context killed the whole 1-minute job | fixed — domain is skipped, fatal only if no domain has the stream |
| 2 | No time-window flags | A 1-minute sweep could only be "all 301 frames" or one time | fixed — `--start`/`--end` |
| 3 | `track` ran per **view**, not per nest | Two views of d02 overwrote one CSV and doubled the count | fixed — deduped by domain |
| 4 | Soundings carried `valid_time=None` | Every skew-T was unstamped | fixed |
| 5 | Reflectivity below 5 dBZ was **painted, not masked** | Clear air — most of a 213 × 171 km footprint — read as data | fixed |
| 6 | The output guard rejected any ancestor holding a `.git` | A stray `/tmp/.git` on CHPC vetoed every legitimate scratch path | fixed — checks only the brc-tools and case checkouts |
| 7 | `shade_cin` without a dewpoint | The whole stable layer above the EL shaded as inhibition | fixed |
| 8 | `parcel_levels` reversed both interpolation arrays | LCL/LFC/EL all reported the surface height | fixed |
| 9 | Beam titles clipped | The tilt — the one thing that makes the figure meaningful — was cut off | fixed |
| 10 | `render_aux` passed borrowed coordinates into `plan_dataset`'s `extra` | `plan_dataset` builds `latitude`/`longitude` as coords itself, so xarray rejected the dataset and the whole 1-minute job died. **Found only when the suite was first run** — the family had never been smoke-tested, unlike the other six | fixed |

## Gaps still open

Ordered by how likely they are to bite.

1. **No idempotence.** `wrf_figures.py` has `--skip-existing` (compares PNG mtime
   against every source file); the winds and convective engines do not. Re-running a
   sweep after adding one family re-renders everything. **Recommended:** lift
   `_skip_existing` into `wrf_engine.py` and thread it through both engines.
2. **No manifest of what was produced.** The pelican study keeps
   `archive-inventory.md` by hand as its SSOT. A sweep that renders 400 figures
   across four jobs leaves no machine-readable record of which times, families and
   domains actually succeeded — so "do we have all the plots?" can only be answered
   by `find`. **Recommended:** emit a `manifest.json` per job (config hash, run dir,
   times, families, per-figure success/skip/error) and a `--report` mode that
   summarises coverage.
3. **Silent per-figure failure.** Each family catches exceptions and prints `[ERR]`,
   which is right for robustness, but the exit code is 0 as long as *something*
   rendered. A job that failed 300 of 400 figures looks like a success. **Recommended:**
   return a non-zero exit when the error count exceeds a threshold, and print an
   error tally at the end.
4. **`verify` ignores the time selection.** It renders its own configured windows
   regardless of `--valid`/`--every`, which is defensible (they are window products)
   but surprising: `--valid X --figure verify` silently ignores `X`. **Recommended:**
   say so in the log line.
5. **No cross-nest consistency check.** Nothing verifies that a figure labelled d02
   and one labelled d01 at the same valid time actually came from the same run, or
   that a `[[sections]]` A→B line lies inside the nest being cut. A transect running
   off-grid samples the edge column for the rest of its length — silently. `WRF-WINDS.md`
   warns about this in prose; it should be a preflight check.
6. **Colour limits are global, not per-window.** The convective styles are set from
   this run's measured maxima, which is right for comparability but means a quiet
   frame at 23:10Z is nearly blank on the same scale that resolves the 02:20Z core.
   Acceptable, but worth a `[style.overrides]` per sweep if a reader is comparing
   early and late frames.
7. **Observed-radar coverage is tilt-limited and that is easy to forget.** IEM RIDGE
   gives 0.5° only. The engine renders an observed panel *only* for tilts it has, so
   a 1.2° model figure appears with no counterpart — correct, but a reader may not
   notice the absence. **Recommended:** annotate the model panel when no observed
   counterpart exists at that tilt.
8. **No `--dry-run`.** There is no way to ask "what would this render?" before
   committing a job. With four families × three views × 31 times the answer is not
   obvious. **Recommended:** print the planned figure list and exit.
9. **Two `_MASK_AT_OR_BELOW` / `_SURFACE_FIELDS` tables live in the script**, not the
   package, so they are untested and unavailable to other callers. **Recommended:**
   move to `nwp/wrf_convective.py` with tests.
10. **`REFD_COM` and `REFD_MAX` both map to the `refl_comp` style**, and the
    collision fallback names the second `refd_max`, which has no style and is
    therefore skipped with a confusing message. Minor, but it means a run writing
    both silently plots only one.

## The rule that has earned its place

Every one of errors 5–9 above produced a figure that *looked* right. The only
reliable defence has been **rendering one time and actually opening the file** before
sweeping, and stating the physical surface (tilt, height, layer, accumulation window)
in the figure itself. On the Ashley case the same ground reads 47.6 dBZ as a column
maximum, 44.1 on the 0.5° beam surface and 11.2 on the 1.2° surface. A reflectivity
number without its surface is not a measurement, and a figure that does not print its
surface invites the reader to invent one.

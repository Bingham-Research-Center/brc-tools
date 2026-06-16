# Hand-off to brc-wrf — WRF run side

Mirror of `../brc-wrf/brc-docs/BRC-TOOLS-LINK-HANDOFF.md` (which runs brc-wrf →
brc-tools). Paste the block below into a fresh Claude Code session started in
`~/gits/brc-wrf`. Paths inside it are **relative to the brc-wrf repo root**
(sibling checkout); every path and command was resolution-checked on 2026-06-15.

## What brc-tools changed (2026-06-15, branch `feat/wrf-input-staging`)

- `docs/WRF-INPUT-STAGING.md`: added a state banner; **stripped the WRF-run Slurm
  profile from §5b** (it now points runs back to brc-wrf — the DTN *staging* job
  stays, it's ours); added a mixed-manifest warning; reconciled the
  "pre-contract manifest" ↔ "reconstructed legacy contract" vocabulary; relabeled
  run-benchmark microtasks **#26/#27 as brc-wrf-owned**.
- New `docs/WRF-GEFS-NAM-FIELD-MAP.md` — DRAFT two-stream field map (NOT proven).
- New `docs/walkthroughs/wrf-staging.md` — the brc-tools staging boundary spoke.

## Paste prompt (optimised for AI ingest)

```text
You are a Claude Code session in ~/gits/brc-wrf, picking up the WRF RUN side after a
brc-tools docs/contract pass (2026-06-15). brc-tools owns GRIB staging ONLY; WPS,
real.exe, wrf.exe, and the Slurm RUN profile are yours.

GROUND TRUTH (do not re-derive):
- NAM-only single-stream is PROVEN end-to-end (WPS -> real.exe -> wrf.exe, Jan-2013 Basin).
- GEFS+NAM two-stream is NOT proven.
- STOP POINTS: no sbatch / WPS / real.exe / wrf.exe without explicit human approval.

READ (batch, in order):
- brc-docs/BRC-WRF-STATE-PLAYBOOK.md
- brc-docs/BRC-WRF-FIRST-CASE.md
- ../brc-tools/docs/WRF-INPUT-STAGING.md
- ../brc-tools/docs/WRF-GEFS-NAM-FIELD-MAP.md
- ../brc-tools/docs/walkthroughs/wrf-staging.md

CHEAP CHECKS FIRST (no model runs; only local file hashing / metadata):
  python ../brc-tools/scripts/stage_wrf_inputs.py --verify-manifest \
    /scratch/general/vast/$USER/wrf_inputs/<case>/manifest_<case>.json
  python brc-cases/wrf_case.py validate brc-cases/jan2013_basin_nam.case.yaml --strict-files

PICK ONE GOAL:

(A) Close brc-tools handoff issue 4 — prove a FRESH contract validates:
    1. Have brc-tools stage a fresh NAM-only case; get contract_<case>.json on scratch
       (python ../brc-tools/scripts/stage_wrf_inputs.py --plan ... first, then the DTN job).
    2. Point the case yaml's forcing.contract_path at that fresh contract, NOT the reconstructed
       fallback brc-cases/jan2013_basin_nam.contract.json.
    3. python brc-cases/wrf_case.py validate <case>.yaml --strict-files   # must pass clean
    4. Once it passes, retire the reconstructed-legacy contract fallback.

(B) Attempt the two-stream GEFS+NAM proof (field map: ../brc-tools/docs/WRF-GEFS-NAM-FIELD-MAP.md):
    1. Build Vtable.GEFS: _pres + _abv700mb split, SPECHUMD (no RH on pressure), height-level 10m
       winds. Resolve bgrnd-soil vs NAM-fill (the open question in the field map).
    2. ungrib the staged gefs_reforecast/ dir; confirm intermediate files hold all expected fields.
    3. metgrid fg_name='GEFS','NAM' (NAM as filler), interval_seconds=10800 (3h reforecast cadence).
    4. STOP — show the met_em field list + any missing-mandatory-field warning BEFORE real.exe.
    5. On approval: real.exe, then wrf.exe -> SUCCESS COMPLETE WRF; quicklook vs the NAM-only baseline.

THEN (brc-wrf-owned benchmarks, formerly brc-tools #26/#27):
    Scaling: sweep --ntasks {16,28,56}, find the knee. Memory: right-size --mem.
    Update brc-docs/BRC-WRF-STATE-PLAYBOOK.md with the result.

Leave a breadcrumb per step: command, evidence, owner repo, stop point. Absolute /scratch paths are
CHPC-local and fine here; never hand an absolute path to a different machine (CLAUDE.md convention).
```

## Verified (2026-06-15)

- All 5 READ paths + the stage script resolve from `~/gits/brc-wrf`.
- `wrf_case.py validate <case_file> --strict-files` is the real validator CLI.
- `--verify-manifest` and `--plan` are real `stage_wrf_inputs.py` flags.

# NWP roadmap — HRRR/RRFS → BasinWX ingest

## Status (as of 2026-08-07)

The original phase plan (0–6: environment audit → HRRR-first helpers → Synoptic
history → model/obs alignment → adjacent products → tests/docs) is **complete**.
Rollout to BasinWX is staged; stage-by-stage status lives in **GitHub issue #10**
— this doc records what exists in the repo, #10 records what is deployed.

### What was built
- **NWPSource** (`brc_tools/nwp/source.py`): Herbie-backed fetch (HRRR/GEFS/RRFS
  and more), parallel downloads, canonical alias namespace, waypoint extraction.
- **`brc_tools/nwp/`** is now ~25 modules: `alignment.py`, `derived.py`,
  `case_study.py`, `point_extract.py`, `aviation.py`, `forecast_funnel.py`,
  `convective_env.py`, the `wrf_*` adapters/engines, and `lookups.toml`
  (10 `[models.*]` tables; source of truth for models, regions, waypoints,
  aliases).
- **Per-source download decisions** (Herbie-native vs direct GET) live in
  `docs/nwp/NWP-SOURCE-MATRIX.md`, enforced by `tests/test_source_matrix.py`.
- **ObsSource** (`brc_tools/obs/source.py`): SynopticPy wrapper sharing the alias
  namespace; event scanner in `brc_tools/obs/scanner.py`.
- **Verification** (`brc_tools/verify/deterministic.py`): RMSE, bias, MAE,
  correlation, `paired_scores`.
- **Observation helpers** (`brc_tools/download/`): `download_funcs.py` (Synoptic
  metadata/time series, JSON filename generation), `get_map_obs.py` (production
  obs download/shape/save/upload), `hrrr_access.py`/`hrrr_config.py`.
- **Test suite**: 665 passed / 6 skipped across ~50 test files
  (`pytest tests/`, env `brc-tools-2026`).

### Operational today
- **HRRR → BasinWX exports**: `scripts/export_hrrr_surface_layers.py`,
  `scripts/export_hrrr_waypoint_forecast.py`,
  `scripts/export_hrrr_kvel_crosswind.py`, driven by the cron wrappers
  `scripts/cron/run_hrrr_*.sh`. Cron host + deployment detail:
  `docs/CHPC-REFERENCE.md`.
- **Obs cron**: `brc_tools/download/get_map_obs.py` writes to
  `~/.cache/brc-tools/map_obs` (moved out of the repo-local `data/` default).
- **Rollout stages** (open PR lane, website-side dependencies): see GitHub #10.

### Known limits / remaining
- **HRRR sub-hourly**: `NWPSource.normalize_coords` discards the GRIB time axis,
  so `product="subh"` collapses to hourly through NWPSource;
  `brc_tools/nwp/aviation.py` calls Herbie directly to preserve the 15-min axis.
  Folding that back into NWPSource is open.
- **RRFS**: `[models.rrfs]` is configured in `lookups.toml`; operational use —
  status: see GitHub #10.
- **Lagged-ensemble / GEFS probability workflows**: deferred until the
  single-run lane is fully deployed.

## Design decisions that still govern this lane
- **Herbie first**: prefer Herbie model templates over hand-rolled fetches;
  record each source's decision in `docs/nwp/NWP-SOURCE-MATRIX.md`.
- **UTC internally**; convert only at display.
- **Raw access stays separate from analysis logic** (download/open helpers vs
  derived metrics/verification).
- **Composable helpers over one pipeline** — functions an agent can mix and
  match (see `docs/CASE-STUDY-GUIDE.md`).

---

## Archive: branch survey 2026-04-06

Pre-merge branches preserved in case prototype code needs mining. Use
`git show <branch>:<path>` rather than checking out.

| Branch | Repo | Value | Caveat |
| --- | --- | --- | --- |
| `feat/hrrr-road-poc-minimal` | `brc-tools` | Reusable HRRR helpers; US-40 sequence (Duchesne → Myton → Roosevelt → Vernal) | Not merged |
| `origin/chore/hrrr-road-ops-docs` | `brc-tools` | Website contract, cron, upload route spec | Mostly docs/ops |
| `origin/feat/hrrr-road-forecast-core` | `brc-tools` | Earlier full road-forecast implementation | Superseded by minimal branch |
| `origin/recovery/brc-tools-hrrr-direct-main-2026-03-02` | `brc-tools` | Historical recovery point | Reference only |
| `origin/feat/rwis-surface-snow-decisions` | `ubair-website` | RWIS / surface-status / visibility logic | No HRRR forecast endpoint |

# `in_progress/` — mining archive

Old exploratory code kept deliberately so patterns can be lifted into
`brc_tools/` when needed. **Do not edit these files** — treat them as
read-only snapshots. To reuse a pattern, extract it into the library
and reference the source commit in the new module.

## Status key
- **mine** — contains ideas or code worth lifting. Named below with the idea.
- **stale** — superseded by current library; kept only for history.
- **broken** — runs network/import side-effects at module load; excluded from `pytest` via `pyproject.toml` `testpaths = ["tests"]`.

## Index

### Top level
| File                     | Status  | Mine for |
|--------------------------|---------|----------|
| `download_hrrr.ipynb`    | mine    | Early Herbie→xarray patterns, region subsetting. Most ideas now in `brc_tools/nwp/source.py`; re-check before extending NWPSource. |
| `download_rrfs.ipynb`    | mine    | RRFS-specific Herbie quirks. Compare against `lookups.toml` RRFS entries. |
| `download_aqm.ipynb`     | mine    | AQM exploration; nothing in `brc_tools/` yet (see WISHLIST "Move AQM code"). Starting point if you need AQM. |
| `xsection.ipynb`         | mine    | Cross-section prototype. WISHLIST Priority 3. Mine pressure-level interpolation logic. |

### `aqm/`
Pre-library AQM exploration — patterns to lift when `brc_tools/models/aqm.py` is built (WISHLIST item).

| File                        | Status  | Mine for |
|-----------------------------|---------|----------|
| `aqm_explorer.py`           | mine    | Main AQM exploration code path. |
| `updated-aqm-explorer.py`   | mine    | Later iteration; diff against `aqm_explorer.py` to see what changed. |
| `simple_aqm_explorer.py`    | mine    | Minimal variant — good starting scaffold. |
| `aqm-demo.py`               | stale   | Thin demo; use explorer variants instead. |
| `aqm-claude-demo2.py`       | stale   | LLM-generated fragment; not self-contained. |
| `ext_herbie_tests.ipynb`    | mine    | Herbie edge-case experiments. |
| `hrrr_test.py`              | broken  | Runs `xr.merge` at import; excluded from test discovery. Mine for HRRR product query patterns only. |

### `notebooks/`
Gemini/o3-mini prompt experiments from a previous exploration phase. Most are redundant with current library; a few have novel ideas.

| File                             | Status  | Mine for |
|----------------------------------|---------|----------|
| `hrrr_height_cross_section.py`   | mine    | Height-based vertical slicing — directly relevant to WISHLIST "Cross-section plotting". |
| `hrrr_native_levels.py`          | mine    | Native-level HRRR access (vs pressure interpolation). Niche but useful. |
| `hrrr_drybulb_option.py`         | mine    | Dry-bulb temperature handling — worth checking before extending derived fields. |
| `kvel_wind.ipynb`                | stale   | Early KVEL exploration; superseded by `scripts/case_study_kvel_westerly.py` and `case_study_kvel_foehn.py`. |
| `synoptic_raw_download.ipynb`    | stale   | Raw SynopticPy usage; superseded by `ObsSource`. |
| `gemini_parallel-aqm.py`         | stale   | Parallelism experiment. |
| `gemini_refactored-aqm.py`       | stale   | Refactor attempt. |
| `gemini_rrfs_no_herbie.py`       | stale   | RRFS-without-Herbie — interesting only if Herbie is ever dropped. |
| `gemini_tryhard_{gfs,hrrr,nam,rrfs}.py` | stale | Prompt-engineering attempts; nothing in them that isn't in current NWPSource. |
| `o3_mini_high_rrfs.py`           | stale   | Similar territory. |

## Workflow for extracting code
1. Find the pattern you need (grep this index first, then the files).
2. Write the new module in `brc_tools/`.
3. Add a commit message referencing the source file, e.g. `feat(nwp): add cross-section helper (adapted from in_progress/notebooks/hrrr_height_cross_section.py)`.
4. Do **not** delete the source file; leave the archive intact for future miners.

## Before writing new exploration code
Check whether it belongs in `scripts/` as a case study or directly in `brc_tools/` as a library function. Only fall back to `in_progress/` when the direction is genuinely unclear.

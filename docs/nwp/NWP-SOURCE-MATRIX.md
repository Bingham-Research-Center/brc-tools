# NWP source matrix — Herbie vs. direct download

How brc-tools obtains each NWP source, the per-source idiosyncrasies, and where we
use **Herbie** vs. a **hand-rolled fetch** (and why). This is the answer to the
recurring "are we reinventing the wheel?" question. Machine-readable companion:
`brc_tools/nwp/lookups.toml` (the model registry); staging detail in
`docs/WRF-INPUT-STAGING.md`.

Herbie version evaluated for current WRF-staging work: **2026.3.0** (env
`brc-tools-2026`). Do not run this lane from an inherited shell env; force:

```bash
conda run -n brc-tools-2026 python ...
conda run -n brc-tools-2026 pytest ...
```

Earlier RAP wheel checks used `clyfar-nov2025` / Herbie **2025.11.3**; keep
those results as historical evidence only unless they are refreshed under
`brc-tools-2026`.

## Matrix

| Source (`lookups` key) | Role | brc-tools entry point | Mechanism | Herbie-native? | Key idiosyncrasies |
|---|---|---|---|---|---|
| `hrrr` | operational forecast | `NWPSource.fetch()` | **Herbie** `model="hrrr"` | ✅ yes | `subh` (15-min) resolves as hourly through NWPSource — `normalize_coords` drops the GRIB time axis; call Herbie directly if 15-min is needed |
| `gefs` | operational ensemble | `NWPSource.fetch()` | **Herbie** `model="gefs"` | ✅ yes | 0–360° lon → shift-then-sel crop; product breakpoint `atmos.25`→`atmos.5` above f240 |
| `rrfs` | experimental | `NWPSource.fetch()` | **Herbie** `model="rrfs"` | ✅ yes | evolving product names |
| `gefs_reforecast` | WRF forcing (historical ens) | `wrf_staging.stage_reforecast()` | **Herbie** `Herbie.download()`, `model="gefs_reforecast"` | ✅ yes | per-variable file layout; 700 hPa pressure split (`_pres` / `_pres_abv700mb`); specific humidity only; 10 m winds = `ugrd_hgt`; **no land-sea mask, no snow**; members c00/p01–p04; `Days:1-10`/`10-16` buckets |
| `nam_analysis` | WRF forcing/filler (2013) | `wrf_staging.stage_nam_analysis()` | **Direct NCEI HTTP GET** (`requests`) | ❌ **no** | Herbie `nam` has only `aws`/`nomads` (operational, recent) — no NCEI-historical `namanl_218`. grib1 `.grb`; 6-hourly; whole file; carries land-mask/SST/skin/4-layer soil/snow |
| `rap_analysis` | WRF forcing (Pelican hot-swap) | `wrf_staging.stage_rap_analysis()` → shared `stage_nam_analysis` | **Direct NCEI HTTP GET** (`requests`) | ⚠️ **intended but broken upstream** (see below) | grib2 `.grb2`; hourly; whole file; ~12 MB/cycle |
| `era5` | WRF forcing candidate | _not implemented_ | Would require CDS/Copernicus tooling or another reviewed source path | n/a locally | Blocked locally: no `era5` model in `lookups.toml`, no `cdsapi`/`ecmwfapi` in `brc-tools-2026`, and no CDS credentials configured; WPS-side `Vtable.ECMWF` exists in brc-wrf |
| `gfs_analysis` | WRF forcing (Pelican hot-swap, 2nd source) | `wrf_staging.stage_gfs_analysis()` → shared `stage_nam_analysis` | **Direct NCEI HTTP GET** (`requests`) | ❌ **no** | Herbie `gfs` has only `aws`/`nomads` (operational, recent) — no NCEI-historical `gfsanl_4`. grib2 `.grb2`; grid-004 0.5°; 6-hourly `_000` (grid-4 also ships `_003`/`_006` → optional 3-hourly LBCs); whole file ~52 MB/cycle; **field-complete for `real.exe`** (4-layer soil T/moisture, land-sea mask, skin temp, snow/ice, 26-level HGT/TMP/RH/UGRD/VGRD — confirmed from the live `.inv` 2026-06-30; the layered soil + real-ready 3D atmosphere RAP lacked); `Vtable.GFS`, humidity = RH; only gap vs NAM is `snod` (snow depth). NCEI product: https://www.ncei.noaa.gov/products/weather-climate-models/global-forecast |
| _Synoptic obs_ | observations | `ObsSource` | SynopticPy (obs ≠ NWP) | n/a | UTC-strip, alias rename, waypoint injection |
| _FlightAware_ | aviation | `brc_tools/api/flightaware` | AeroAPI client | n/a | paid API |

## The RAP wheel: Herbie aims at it, but is broken in 2025.11.3

Herbie ships templates pointed at exactly our file:
- **`rap_historical`** (product `analysis`) builds
  `…/rapid-refresh/access/historical/analysis/{YYYYMM}/{YYYYMMDD}/rap_130_{YYYYMMDD_HHMM}_{fxx:03d}.grb2`
  — **byte-identical to our `[models.rap_analysis].url_template`.** It also carries RUC2/RUC
  fallbacks for pre-2012 dates.
- **`rap_ncei`** (product `rap-130-13km`) targets the `…/access/rap-130-13km/analysis/…` subdir.

Live resolution test (2026-06-29, Herbie 2025.11.3) for `2013-02-02 12Z`, `fxx=0`:

| Herbie call | Result |
|---|---|
| `model="rap_historical", product="analysis"` | **raises `ValueError: Invalid suffix 'grb.inv'`** |
| `model="rap_ncei", product="rap-130-13km"` | `grib=None` (no 2013 file under `rap-130-13km/`) |
| `model="nam", product="awphys"` | `grib=None` (operational sources don't reach 2013) |

The `rap_historical` failure is an **upstream typo** in `herbie/models/rap.py`:
`IDX_SUFFIX = [".inv", ".grb2.inv", "grb.inv"]` — the third entry is missing its leading dot
(`grb.inv` → should be `.grb.inv`), which Herbie rejects before it probes the file.

**So out of the box Herbie does not retrieve RAP-130 2013 analysis** — our direct GET works where
Herbie currently fails, and uses the same URL Herbie *intends*. (Independently confirmed by curl:
all 7 cycles 12–18Z → HTTP 200, ~12 MB; bogus cycle → 404.)

## Why the analysis sources use direct GET (not Herbie)

Beyond the bug, `nam_analysis`, `rap_analysis`, and `gfs_analysis` deliberately share one
**whole-file analysis** path (`stage_nam_analysis`, source-generic) because:
- **One path, one set of guarantees:** per-cycle locking, `BRC_TOOLS_HTTP_IPV4_ONLY` (NCEI IPv6-hang
  workaround), GRIB validation, manifest/contract — identical for NAM, RAP, and GFS.
- **Offline `--plan` is deterministic:** URLs/paths are templated from `lookups.toml`; no Herbie
  inventory probing.
- **No byte-range/`.idx` machinery:** WPS wants whole analysis files; we never subset.
- Herbie genuinely lacks NAM-NCEI-historical, so NAM had to be direct anyway; RAP and GFS ride the same
  path for uniformity.
- **GFS analysis chosen over NCAR-RDA FNL (`ds083.2`):** the auth-free NCEI archive needs no RDA
  account/`cdsapi`, and grid-004 (0.5°) is *finer* than 2013 FNL (1°). Field adequacy and `Vtable.GFS`
  were confirmed from the live `.inv` (no GRIB body downloaded) — it carries the 4-layer soil + full 3D
  atmosphere RAP lacked, so it should clear the `NUM_METGRID_SOIL_LEVELS=0` block that stopped RAP.

## Wheel check / recommendations

- **HRRR / GEFS / RRFS / GEFS-reforecast** — correctly on Herbie; no change. ✅
- **NAM analysis (2013)** — Herbie has no NCEI-historical NAM; direct GET is the only option. ✅
- **RAP analysis (2013)** — mild reinvention *by necessity*: Herbie's `rap_historical` is the intended
  wheel but is broken (IDX_SUFFIX typo) in 2025.11.3, and our URL matches its intent. Options:
  1. **Keep direct GET** (works today; uniform with NAM) — current choice.
  2. **File an upstream Herbie issue** for the `'.grb.inv'` typo (cheap; helps everyone).
  3. Revisit a Herbie-backed RAP path once fixed (would gain RUC2 pre-2012 fallback for free).

## Herbie currency (checked 2026-06-30)

| | Version | When |
|---|---|---|
| Required WRF-staging env (`brc-tools-2026`) | **2026.3.0** | Mar 2026 |
| Inherited env observed in Codex (`clyfar-nov2025`) | **2025.11.3** | Nov 2025 |
| Latest (conda-forge + PyPI) | **2026.3.0** | Mar 2026 |

What updating `2025.11.3 → 2026.3.0` would buy:
- **2026.3.0** — RRFS template fixed to the current S3 bucket layout (#511). **We use `rrfs`** — the
  pinned version may already mis-resolve it.
- **2026.1.0** — Pandas 3.0 inventory parsing; drops Py3.10 / adds 3.14; new NOAA AIWP models
  (AIGFS, AIGEFS, HGEFS).
- **2025.12.0** — full-file downloads moved `urllib` → `requests` (fixes SSL-cert issues, #246).
- **Does NOT fix** the `rap_historical` `IDX_SUFFIX` typo — still `"grb.inv"` on the default branch at
  2026.3.0, so a Herbie-backed RAP path stays blocked regardless.

**Recommendation:** use `brc-tools-2026` for all WRF-staging work. File an upstream issue
for the `rap_historical` typo if RAP Herbie support matters later. Env recipe →
`docs/ENVIRONMENT-SETUP.md`.

## Enforcement

Adding any `[models.*]` to `lookups.toml` **must** add a row here (with its Herbie-vs-direct decision) —
guarded by `tests/test_source_matrix.py`, which fails if a lookups model is undocumented. This enforces
the *process* (record the wheel-check), not an automated Herbie lookup: Herbie model names don't map 1:1
to ours (our `nam_analysis`/`rap_analysis` vs Herbie `nam`/`rap_historical`/`rap_ncei`), so a
name-collision check would mislead. The human decision lives here.

## Resources — Brian Blaylock's Herbie (check these FIRST)

- **Docs** (extensive: tutorials, gallery, per-model notes, FAQ): https://herbie.readthedocs.io
- **Source + issues:** https://github.com/blaylockbk/Herbie
- **Model templates** = the on-rails, hardened access patterns: `herbie/models/*.py` in the installed
  package — read the relevant one before hand-rolling any NOAA download. Herbie grew from Blaylock's
  University of Utah HRRR-archive work, so its coverage of NOAA/NCEI archives is deep.

> Maintenance: re-run the live probes in "The RAP wheel" after each Herbie upgrade; if `rap_historical`
> starts resolving and the RRFS path is confirmed, reconsider the direct-GET choices.

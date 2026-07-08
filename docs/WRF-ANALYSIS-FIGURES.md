# WRF analysis figures — pelican2013 cold-pool cases

Publication-quality matplotlib figures (300 DPI PNG, Helvetica-family font, fixed
shared colour scales) for the four archived pelican2013 WRF runs. Complements the
150-DPI `brc-wrf` quicklooks; the scientific focus is **cold-pool representation**
and its sensitivity to forcing (GFS vs NAM), nest feedback (2-way vs 1-way),
grid resolution (3 km → 1 km → 333 m), terrain-source resolution (~900 m default
vs ~9 km coarse vs ~30 m fine), and short-range evolution (f02 vs f05).

## The cases
All share the d01=3 km / d02=1 km / **d03=333 m** nest (75 eta levels) over the
Uinta Basin, 2013-02-02 **12→18 UTC** hourly. Under
`$BRC_WRF_ARCHIVE` (default `…/lawson-group6/jrlawson/wrf_archive/`):

| key | dir | forcing | feedback | terrain source |
|---|---|---|---|---|
| `gfs` | `pelican2013_gfs_3_1_333m_75lev` | GFS | 2-way | default (`gmted2010_30s`, ~900 m) |
| `nam` | `pelican2013_nam_3_1_333m_75lev` | NAM | 2-way | default (`gmted2010_30s`, ~900 m) |
| `nam_oneway` | `pelican2013_nam_3_1_333m_75lev_oneway` | NAM | 1-way (feedback=0) | default (`gmted2010_30s`, ~900 m) |
| `nam_terrain5m` | `pelican2013_nam_3_1_333m_75lev_oneway_terrain5m` | NAM | 1-way (feedback=0) | `gmted2010_5m` (**5 arc-min ≈ 9 km, coarse**) |
| `nam_terrain3s` | `pelican2013_nam_3_1_333m_75lev_oneway_terrain3s` | NAM | 1-way (feedback=0) | USGS 3DEP **1-arcsec ≈ 30 m, fine** |

**Terrain-source ladder & a naming caveat.** `nam_terrain5m` is a deliberate
terrain-*resolution* sensitivity point, **not** a refinement. WPS `geog_data_res`
tokens are angular, so `gmted2010_5m` is **5 arc-minutes (~9 km)** — about 10×
*coarser* than the `default` (`gmted2010_30s`, ~900 m) the other three use. Measured
on d03 its terrain is ~2.2× smoother (mean |neighbour ΔHGT| 2.36 vs 5.30 m/cell). It
was staged under the misleading name `hires_terrain` (someone read "5m" as 5 *metres*)
and renamed `terrain5m` on 2026-07-07 to match its sibling `terrain3s`. The genuine
**fine** run — USGS 3DEP **1-arcsec (~30 m)**, archived under
`pelican2013_nam_3_1_333m_75lev_oneway_terrain3s` — **landed 2026-07-07** and is now
registered as `nam_terrain3s`. The `difference` family emits two terrain maps, both
same-ICs/same-nesting so each isolates only the terrain source: `diff_terrain/`
(`nam_oneway` − `nam_terrain5m`, default 900 m vs coarse 9 km) and `diff_terrain_fine/`
(`nam_oneway` − `nam_terrain3s`, default 900 m vs fine 30 m; also EW/NS θ sections since
the terrain signal is strongest in the vertical). On d03 the fine-vs-default terrain is
nearly co-registered (mean HGT 1559 vs 1560 m over the 150×150 d03 grid) — both sources
get resampled onto the same 333 m mesh, so the fine diff is modest, a real but small
sensitivity.

## Modules
- `brc_tools/nwp/wrf_output.py` — reads wrfout (xarray, `netcdf4` engine) and derives
  theta / pressure / geometric height / destaggered earth-relative winds; builds
  `WRFColumn`, `WRFSection`, `DomainOutline`; cold-pool diagnostics
  (`delta_theta_crest_floor`, `cold_pool_heat_deficit`). Owns I/O + physics; hands
  plain numpy to the renderers (same contract as `visualize/grid.py`).
- `brc_tools/visualize/style.py` — `use_publication_style()` + the `VAR_STYLES`
  registry (fixed vmin/vmax/cmap per variable for fair comparison) + `diff_style`.
- `brc_tools/visualize/crosssection.py` — terrain-filled height-ASL θ + in-plane-wind
  sections with locator (A–B / C–D) and shallow-layer insets, plus difference mode.
- `brc_tools/visualize/{domains,surface,profile,upperair}.py` — nested-domain map;
  multi-domain surface panels + 2-D difference maps; θ(z) profiles + MetPy skew-T;
  crest-height surfaces with wind + temperature advection.
- `brc_tools/visualize/planview.py::add_map_features` — extended (counties / rivers /
  roads / terrain), offline-guarded.

## Running
```bash
export PYTHONPATH=~/gits/brc-tools               # package is not pip-installed in the env
export MPLCONFIGDIR=/scratch/general/vast/$USER/mpl
PY=~/software/pkg/miniforge3/envs/brc-tools-2026/bin/python

# everything (all cases / families / times)
"$PY" scripts/pelican_figures.py

# a subset
"$PY" scripts/pelican_figures.py --case nam --figure section,surface --time 12,18
```
Families: `domains, section, upperair, surface, difference, profile, skewt,
heatdeficit` (or `all`). Heavier batches: `sbatch scripts/pelican_figures.slurm`
(`--account=lawson-np`, 96 GB).

### Output routing (outside the repo)
- per-case → `<run>/full-figures/<family>/…` (sibling of `quicklooks/`)
- cross-case (domains, profiles, differences, heat-deficit) →
  `$BRC_WRF_ARCHIVE/pelican2013_pub_figures/compare/<family>/…`
- override with `--output-dir` (nests `<case>/<family>/`); a guard refuses any path
  inside the repo checkout.

### Soundings (two-phase — compute nodes lack outbound network)
1. On a **login/DTN node**: `python scripts/fetch_soundings.py --time "2013-02-02 12"
   --stations KSLC,KGJT,KRIW,KDPG --out /scratch/general/vast/$USER/soundings_20130202_12z.parquet`
   (needs `PYTHONPATH=~/gits/brc-tools`). Fetch + provider normalisation live in the
   reusable `brc_tools.api.soundings` client (**IGRA2 default**, Wyoming fallback; UWyo
   is offline as of 2026-07). See `docs/API-CLIENTS.md`.
2. Pass `--sounding-cache <parquet>` to the driver / slurm for the skew-T obs overlay.

**Proxy RAOB stations** (the basin launches no sonde). All four operational sites
overlapping a domain sit in **d01** (from the IGRA2 inventory): `KSLC` (Salt Lake City),
`KGJT` (Grand Junction), `KRIW` (Riverton WY), `KDPG` (Dugway UT). On the 2013-02-02
case date three launched at 12Z (KSLC/KGJT/KRIW); **KDPG did not**. The `skewt` family
therefore emits, per driving analysis (GFS, NAM only — the NAM feedback/terrain variants
share d01 away from the nest): a basin-core **Horsepool** model skew-T (d03, model-only)
plus **station** skew-Ts (model d01 column *at* KSLC/KGJT/KRIW overlaid on that site's
RAOB) — the model-vs-analysis IC check. Model T tracks the KSLC RAOB near-perfectly at
12Z; the model is drier than obs at 600–700 hPa.

## Selected findings (from the smoke runs)
- **GFS vs NAM initial conditions diverge strongly**: at 12Z the Horsepool floor θ is
  285 K (GFS) vs 274.5 K (NAM), and the floor→crest inversion is 6.7 K (GFS) vs 15.5 K
  (NAM) — NAM's cold pool is ~2.3× stronger.
- **2-way ≈ 1-way** at the basin core: the NAM heat-deficit series is identical to two
  decimals; feedback barely changes the pool there.
- **Evolution**: GFS erodes the pool over the morning (6.5→2.9 MJ m⁻²) while NAM
  persists (~4.5–5.6); crest-level **warm-air advection up to 2.7 K/h** caps the pool.

## Caveats / open items
- **Terrain fidelity**: the three default runs built d03 with `geog_data_res='default'`
  (`gmted2010_30s`, ~900 m topography) — coarser than the 333 m grid, so the model floor
  is smoothed. Figures deliberately use wrfout `HGT` ("what the model saw"). The
  terrain-source axis is now bracketed at both ends: `nam_terrain5m` adds a **coarse**
  (~9 km) endpoint and `nam_terrain3s` (USGS 3DEP 1-arcsec) the genuine **fine** (~30 m)
  endpoint — both landed and registered here (`nam_terrain3s` on 2026-07-07).
- **In-basin soundings**: only 12Z is an operational RAOB, and the proxies (KSLC/KGJT/
  KRIW) sit *outside* the basin in d01 — they verify the synoptic/driving environment,
  not the basin pool (that is what the model-only Horsepool skew-T is for). The
  UBWOS-2013 Ouray/Horsepool radiosondes plug in via `profile.PlaceholderFileSounding`
  / `CachedSounding` once the user locates them.
- **Env**: `netcdf4`, `metpy`, `siphon` added (see `environment.yml` / the `wrf` extra
  in `pyproject.toml`).
```

# WRF analysis figures — pelican2013 cold-pool cases

Publication-quality matplotlib figures (300 DPI PNG, Helvetica-family font, fixed
shared colour scales) for the three archived pelican2013 WRF runs. Complements the
150-DPI `brc-wrf` quicklooks; the scientific focus is **cold-pool representation**
and its sensitivity to forcing (GFS vs NAM), nest feedback (2-way vs 1-way),
resolution (3 km → 1 km → 333 m), and short-range evolution (f02 vs f05).

## The three cases
All share the d01=3 km / d02=1 km / **d03=333 m** nest (75 eta levels) over the
Uinta Basin, 2013-02-02 **12→18 UTC** hourly. Under
`$BRC_WRF_ARCHIVE` (default `…/lawson-group6/jrlawson/wrf_archive/`):

| key | dir | forcing | feedback |
|---|---|---|---|
| `gfs` | `pelican2013_gfs_3_1_333m_75lev` | GFS | 2-way |
| `nam` | `pelican2013_nam_3_1_333m_75lev` | NAM | 2-way |
| `nam_oneway` | `pelican2013_nam_3_1_333m_75lev_oneway` | NAM | 1-way (feedback=0) |

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
   --out /scratch/general/vast/$USER/soundings_20130202_12z.parquet`
2. Pass `--sounding-cache <parquet>` to the driver / slurm for the skew-T obs overlay.

## Selected findings (from the smoke runs)
- **GFS vs NAM initial conditions diverge strongly**: at 12Z the Horsepool floor θ is
  285 K (GFS) vs 274.5 K (NAM), and the floor→crest inversion is 6.7 K (GFS) vs 15.5 K
  (NAM) — NAM's cold pool is ~2.3× stronger.
- **2-way ≈ 1-way** at the basin core: the NAM heat-deficit series is identical to two
  decimals; feedback barely changes the pool there.
- **Evolution**: GFS erodes the pool over the morning (6.5→2.9 MJ m⁻²) while NAM
  persists (~4.5–5.6); crest-level **warm-air advection up to 2.7 K/h** caps the pool.

## Caveats / open items
- **Terrain fidelity**: d03 was built with `geog_data_res='default'` (~900 m topography)
  — coarser than the 333 m grid, so the model floor is smoothed. Figures deliberately
  use wrfout `HGT` ("what the model saw"). A finer-GEOG geogrid re-run is a **brc-wrf**
  follow-up (out of brc-tools scope).
- **In-basin soundings**: only 12Z is an operational RAOB, and KSLC/KGJT sit *outside*
  the basin (they verify the synoptic/valley environment, not the basin pool). The
  UBWOS-2013 Ouray/Horsepool radiosondes plug in via
  `profile.PlaceholderFileSounding` / `CachedWyomingSounding` once the user locates them.
- **Env**: `netcdf4`, `metpy`, `siphon` added (see `environment.yml` / the `wrf` extra
  in `pyproject.toml`).
```

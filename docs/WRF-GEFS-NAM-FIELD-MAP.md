# GEFS + NAM two-stream field-map (DRAFT)

> **DRAFT — the GEFS+NAM two-stream path is NOT proven through WPS / `real.exe`.**
> Only the NAM-only single-stream path is validated (see
> [WRF-INPUT-STAGING.md](WRF-INPUT-STAGING.md)). This page is a design aid for the
> *future* two-stream work, owned on the WPS side by `brc-wrf`.
>
> **Token source of truth:** `brc_tools/nwp/lookups.toml`
> `[models.gefs_reforecast].wps_variable_levels`. If that list changes, update this.

## Why two streams

The GEFSv12 **reforecast** gives historical (pre-2017) atmospheric forcing but is
missing several **surface/static** fields WRF needs. An auth-free **NAM 12 km
analysis** fills those gaps. metgrid then fuses them (`fg_name = 'GEFS','NAM'`,
NAM as the filler stream).

## What each stream carries

| GEFS reforecast provides (token) | Vtable.GEFS implication | NAM must fill |
| --- | --- | --- |
| `hgt/tmp/ugrd/vgrd/spfh _pres` **+** `_abv700mb` (pressure fields **split at 700 hPa** — both halves = full column) | GHT / TT / UU / VV, and humidity as **SPECHUMD** (there is no RH on pressure) | — |
| `pres_msl`, `pres_sfc`, `hgt_sfc` | PMSL / PSFC / SOILHGT | — |
| `tmp_2m`, `spfh_2m`, `tmp_sfc`, `ugrd_hgt`, `vgrd_hgt` (10 m **height-level** winds) | 2 m TT / SPECHUMD, 10 m UU / VV | — |
| `tsoil_bgrnd`, `soilw_bgrnd` (below-ground soil), `weasd_sfc` (snow water eq.) | WEASD maps cleanly; **soil-layer → WPS mapping is an OPEN QUESTION** (the proven run used NAM soil, not these) | proper 4-layer soil (see below) |
| *(absent)* land-sea mask | — | **NAM `LANDSEA`** |
| *(absent)* SST / skin temp | — | **NAM `SKINTEMP` / SST** |
| *(absent)* snow **depth** (`snod`) | — | **NAM `SNOWH`** |
| *(absent)* 4-layer soil temp/moisture | — | **NAM soil (0-10 / 10-40 / 40-100 / 100-200 cm)** |

(Confirmed against `lookups.toml:89-109` and the `wrf_staging` module docstring,
which lists land-sea mask, SST, skin temp, and soil as NAM-supplied.)

## Open questions before any two-stream attempt

1. **Soil.** GEFS ships `*_bgrnd` soil tokens, but the validated path took soil
   from NAM. Decide whether `bgrnd` maps to WRF's 4 fixed layers or stays NAM's job.
2. **`Vtable.GEFS`** does not exist yet — building/validating it is `brc-wrf` work.
3. **Cadence.** Reforecast interval is 3 h (`interval_seconds=10800`) vs NAM's 6 h;
   the contract records this per source.

## Hand-off

Building `Vtable.GEFS` and proving `real.exe` with two streams is **brc-wrf**
work. From the brc-tools side, staging is driven from the checkout by
`conda run -n brc-tools-2026 python -m brc_tools.nwp.wrf_staging --source gefs_reforecast,nam_analysis` (see
[walkthroughs/wrf-staging.md](walkthroughs/wrf-staging.md) and
[WRF-INPUT-STAGING.md](WRF-INPUT-STAGING.md) §3).

# Stage WRF inputs — walk-through (boundary)

**What / why:** Download the GRIB files the WRF model needs and lay them out on
scratch with provenance sidecars. This is **only the input-prep half**. brc-tools
stops once the files + sidecars exist; running the model is the `brc-wrf` repo's
job.

> **State:** NAM-only single-stream is proven end-to-end. GFS 0.5° analysis is a
> second forcing, **staged + verified** for the Pelican case (awaiting brc-wrf WPS).
> GEFS+NAM two-stream is **not** proven — see [../WRF-GEFS-NAM-FIELD-MAP.md](../WRF-GEFS-NAM-FIELD-MAP.md).

**Needs:** DTN access for real downloads · conda env `brc-tools-2026`

## Look before you download (cheap, no network)

`--plan` lists the files, URLs, and total bytes, then exits:

```bash
conda run -n brc-tools-2026 python -m brc_tools.nwp.wrf_staging --plan \
    --case jan2013_basin_gefs --init-time "2013-01-31 12Z" --source nam_analysis
```

## Do the real stage (on the DTN)

Big downloads run on the Data Transfer Node, not a login/compute node:

```bash
sbatch scripts/stage_inputs.dtn.slurm        # brc-tools' own staging job
```

## Check what was staged

```bash
conda run -n brc-tools-2026 python -m brc_tools.nwp.wrf_staging --verify-manifest \
    /scratch/general/vast/$USER/wrf_inputs/jan2013_basin_gefs/manifest_jan2013_basin_gefs.json
```

**Produces (on scratch):** raw GRIB under `<case>/<source>/<member>/`, plus
`manifest_<case>.json` (every file + checksum) and `contract_<case>.json` (the
WPS-relevant facts `brc-wrf` should trust). See [manifest vs. contract](GLOSSARY.md).

---

## ⛔ Hand-off — the rest lives in `brc-wrf`

brc-tools stops at **GRIB + manifest + contract on scratch**. WPS, `real.exe`,
`wrf.exe`, and the Slurm **run** profile are owned by `brc-wrf` + `brc-knowledge`.
Continue there (paths are from the repo root, both repos checked out as siblings):

- `../brc-wrf/brc-docs/BRC-WRF-FIRST-CASE.md` — run the case end-to-end
- `../brc-wrf/brc-docs/BRC-WRF-USAGE.md` — WRF/WPS usage + the run wrapper
- `../brc-wrf/brc-docs/BRC-WRF-STATE-PLAYBOOK.md` — what's proven / next

Full brc-tools-side detail: [../WRF-INPUT-STAGING.md](../WRF-INPUT-STAGING.md) ·
state: [../WRF-STAGING-STATE-PLAYBOOK.md](../WRF-STAGING-STATE-PLAYBOOK.md).

**See also:** terms (GRIB, WPS, DTN, scratch, reforecast) → [GLOSSARY.md](GLOSSARY.md)

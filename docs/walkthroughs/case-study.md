# Run a case study — walk-through

**What / why:** A "case study" is one script that combines the other tools —
download a model run, pull obs, score, and emit figures for a single weather
event. It's how a forecast question becomes a folder of PNGs.

**Needs:** `SYNOPTIC_TOKEN` (most cases use obs) · conda env `brc-tools`

## Run an existing example

```bash
python scripts/case_study_20250222.py        # cold-pool erosion / warm front, 22 Feb 2025
python scripts/case_study_kvel_foehn.py       # foehn detection at Vernal (KVEL)
python scripts/case_study_kvel_westerly.py    # strong westerly wind ramp at Vernal
```

**Produces:** figures under `figures/` (gitignored).

## Write your own

Don't start from scratch — follow the pattern doc, which explains the two paths
(known date vs. scan-and-select) and the shared helpers in
`brc_tools.nwp.case_study`:

→ **[../CASE-STUDY-GUIDE.md](../CASE-STUDY-GUIDE.md)** (the full how-to)

**See also:** [obs.md](obs.md) · [nwp-download.md](nwp-download.md) · [verify.md](verify.md) · [visualize.md](visualize.md) · terms → [GLOSSARY.md](GLOSSARY.md)

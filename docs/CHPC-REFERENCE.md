# CHPC Reference - Lawson Research Group

**Canonical source for CHPC deployment across all BRC projects.**
Other repos should reference this file, not duplicate it.

---

## Group Resources

| Resource | Name | Details |
|----------|------|---------|
| **Account** | `lawson` | PI: John Lawson (u0737349) |
| **Partition (NP)** | `lawson-np` | 2 owner nodes on Notchpeak |
| **Partition (KP)** | `lawson-kp` | 4 owner nodes on Kingspeak |
| **OS** | Rocky Linux 8.10 | Verified Nov 2025 |

### Storage Allocations

| Path/Name | Type | Capacity | Use |
|-----------|------|----------|-----|
| `lawson-group5` | Cottonwood 09-10 | 16.1 TiB | Persistent datasets |
| `lawson-group6` | Cottonwood 13-14 | 16.3 TiB | Persistent datasets |
| `lawson-group4` | Cottonwood 09-10 | 5.2 TiB | Persistent datasets |
| `/home/lawson` | Vast | 7.3 GiB | Code, configs only |
| `/scratch/general/vast/` | Scratch | Shared | Temporary data, caches |

### Team Members

| Name | uNID | Role |
|------|------|------|
| John Lawson | u0737349 | Principal Investigator |
| Huy Tran | u6002242 | Researcher |
| Tyler Elgiar | u0725192 | Researcher |
| Loknath Dhar | u6052357 | Researcher |
| Michael Davies | u6060939 | Researcher |
| Elspeth Montague | u6060938 | Researcher |
| Trang Tran | u6002243 | Researcher |

---

## Partition Selection

**Priority order:**
1. `lawson-np` - Owner nodes, no queue, your hardware
2. `lawson-kp` - Owner nodes, alternative cluster
3. `notchpeak-shared` - Shared, when owner nodes down

**Owner nodes:** No utilization restrictions, but efficiency warnings still sent. These are advisory only for owner partitions.

---

## salloc Templates

### Standard Interactive (I/O-bound work)
```bash
salloc -n 4 -N 1 --mem=16G -t 2:00:00 -p lawson-np -A lawson-np
```
Use for: Clyfar forecasts, data downloads, light processing

### Heavy Compute (CPU-intensive)
```bash
salloc -n 16 -N 1 --mem=64G -t 4:00:00 -p lawson-np -A lawson-np
```
Use for: Full ensemble runs, training, large data processing

### Fallback (owner nodes busy)
```bash
salloc -n 4 -N 1 --mem=16G -t 2:00:00 -p notchpeak-shared -A notchpeak-shared-short
```

### Quick Debug
```bash
salloc -n 2 -N 1 --mem=8G -t 0:30:00 -p lawson-np -A lawson-np
```

---

## Environment Setup

### Conda (Miniforge recommended)
```bash
# Location
~/software/pkg/miniforge3/

# Activate base
source ~/software/pkg/miniforge3/etc/profile.d/conda.sh

# Project environments
conda activate clyfar-nov2025    # Clyfar forecasting
conda activate brc-tools         # General BRC work
```

### Common Exports
```bash
export PYTHONPATH="$PYTHONPATH:~/gits/clyfar"
export POLARS_ALLOW_FORKING_THREAD=1
```

### API Keys
```bash
# Required for uploads
export DATA_UPLOAD_API_KEY="<32-char-hex>"

# Store in ~/.bashrc or load from secure location
```

---

## Directory Structure

```
~/gits/
├── clyfar/          # Ozone forecast model
├── brc-tools/       # Shared Python utilities
└── ubair-website/   # (usually not on CHPC)

/scratch/general/vast/
├── clyfar_test/     # Test outputs
│   ├── v0p9/        # Version-specific runs
│   └── figs/        # Generated figures
└── herbie_cache/    # NWP download cache
```

---

## Cron Jobs

### Active Production
```bash
# Observations - every 10 minutes
*/10 * * * * source ~/.bashrc && conda activate brc-tools && python ~/gits/brc-tools/brc_tools/download/get_map_obs.py >> ~/logs/obs.log 2>&1
```

### Clyfar Forecasts (4× daily via Slurm)
```bash
# Submit Slurm job at 3hr after each GEFS run
30 3,9,15,21 * * * cd ~/gits/clyfar && ./scripts/submit_clyfar.sh >> ~/logs/clyfar_submit.log 2>&1
```

---

## Common Pitfalls

| Issue | Cause | Fix |
|-------|-------|-----|
| Low CPU warning | Over-allocated resources | Use `-n 4` not `-n 8` for I/O work |
| Module not found | PYTHONPATH not set | `export PYTHONPATH="$PYTHONPATH:~/gits/clyfar"` |
| Conda not found | Shell not initialized | `source ~/software/pkg/miniforge3/etc/profile.d/conda.sh` |
| Upload fails | Wrong hostname | Must run from *.chpc.utah.edu |
| Solver hangs | Conda conflict | Use `mamba` instead of `conda` |

---

## Links

- [CHPC Portal](https://portal.chpc.utah.edu/)
- [Slurm Jobs](https://portal.chpc.utah.edu/slurm/jobs/)
- [Group Dashboard](https://portal.chpc.utah.edu/groups/lawson/)

---

## Project-Specific Docs

| Project | Doc | Content |
|---------|-----|---------|
| clyfar | `CHPC-QUICKREF.md` | Clyfar-specific salloc, env |
| clyfar | `CHPC_DEPLOYMENT_CHECKLIST.md` | Deployment phases |
| ubair-website | `CHPC-IMPLEMENTATION.md` | Website upload setup |

---

**Last Updated:** 2025-11-25
**Maintainer:** John Lawson

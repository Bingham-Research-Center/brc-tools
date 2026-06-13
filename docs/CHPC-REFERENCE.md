# CHPC Reference — brc-tools-specific deployment notes

**Authoritative CHPC infrastructure reference (storage, partitions, sbatch
patterns, hardware, quotas, GPU access):** `~/gits/brc-knowledge/scholarium/reference-base/resources/chpc-team-resource-inventory.md`.
Do not duplicate facts from brc-knowledge here — update brc-knowledge instead.

CHPC file storage policies: <https://www.chpc.utah.edu/documentation/policies/3.1FileStoragePolicies.php>.

This file holds only what is brc-tools-specific: cron jobs, env vars,
conda envs, upload pitfalls. **Paths below assume a CHPC node** — they
begin with `/uufs/chpc.utah.edu/...` or `/scratch/general/...` and `~`
resolves to `/uufs/chpc.utah.edu/common/home/u0737349`. The Linode/Akamai
receiver (`basinwx.com` / `basinwx.dev`) has a different layout; a
cold-start agent on the Linode side will see `~` resolve elsewhere.

---

## Quick orientation (cold-start agent)

```bash
hostname; env | grep -E '^SLURM_' | head -5     # which node? login or compute? salloc?
mydiskquota                                      # home + scratch quotas
df -hT /uufs/chpc.utah.edu/common/home/lawson-group{4,5,6} 2>&1   # group volumes mounted?
```

If `df` returns "Too many levels of symbolic links" for a `lawson-group*`
mount, that volume is not available on this node — do not stage data
there. Re-check from a different node or contact CHPC. Last live check
on notch392 (2026-05-13): group6 OK; group4 and group5 broken.

---

## Conda environments

```bash
# Miniforge (installed at ~/software/pkg/miniforge3/)
source ~/software/pkg/miniforge3/etc/profile.d/conda.sh

conda activate clyfar-nov2025    # Clyfar forecasting; has SynopticPy, polars, herbie
conda activate brc-tools         # General brc-tools work
```

## Environment exports

```bash
export PYTHONPATH="$PYTHONPATH:~/gits/clyfar"
export POLARS_ALLOW_FORKING_THREAD=1
export DATA_UPLOAD_API_KEY="<32-char-hex>"   # required for BasinWX uploads
```

## Cron jobs (active production)

`~/.bashrc`, `~/gits/`, `~/logs/` are CHPC-side paths in the lines below.

```bash
# Observations — every 10 min. Must run from notchpeak1 (login node);
# compute nodes can't reach external APIs. See [[ops_cron_host]] memory.
*/10 * * * * source ~/.bashrc && conda activate brc-tools && \
  python ~/gits/brc-tools/brc_tools/download/get_map_obs.py >> ~/logs/obs.log 2>&1

# Clyfar forecasts — 4× daily via Slurm (3 h after each GEFS run)
30 3,9,15,21 * * * cd ~/gits/clyfar && ./scripts/submit_clyfar.sh \
  >> ~/logs/clyfar_submit.log 2>&1
```

## HRRR surface layer export (BasinWX)

CLI: `scripts/export_hrrr_surface_layers.py`. Use `--server-url` to
override the config-file URL — this is what lets dev/prod cron entries
diverge.

```bash
30 * * * * source ~/.bashrc && conda activate brc-tools && cd ~/gits/brc-tools && \
  python scripts/export_hrrr_surface_layers.py --upload \
  --server-url https://basinwx.dev >> ~/logs/hrrr_upload_dev.log 2>&1
```

Swap to `--server-url https://www.basinwx.com` for production.

## brc-tools-specific pitfalls

| Issue | Cause | Fix |
|-------|-------|-----|
| Upload fails | Wrong hostname | Uploader must run from `*.chpc.utah.edu`; the ubair-website server enforces this via `x-client-hostname` header |
| `ModuleNotFoundError: brc_tools` | PYTHONPATH unset or wrong env | Activate the env and re-source `~/.bashrc` |
| Conda not found | Shell not initialised | `source ~/software/pkg/miniforge3/etc/profile.d/conda.sh` |
| `df` reports "Too many levels of symbolic links" on a group volume | autofs fault on this node | Try a different node; volume may still be intact elsewhere |

## Team members (CHPC access)

| Name | uNID | Role |
|------|------|------|
| John Lawson | u0737349 | Principal Investigator |
| Huy Tran | u6002242 | Researcher |
| Tyler Elgiar | u0725192 | Researcher |
| Loknath Dhar | u6052357 | Researcher |
| Michael Davies | u6060939 | Researcher |
| Elspeth Montague | u6060938 | Researcher |
| Trang Tran | u6002243 | Researcher |

## Project-specific docs

| Project | Doc | Content |
|---------|-----|---------|
| clyfar | `CHPC-QUICKREF.md` | Clyfar-specific salloc, env |
| clyfar | `CHPC_DEPLOYMENT_CHECKLIST.md` | Deployment phases |
| clyfar | `scripts/storage_inventory.sh` | Audit Clyfar storage usage (read-only or `--clean`) |
| clyfar | `scripts/report_disk_usage.sh` | Surface large files for cleanup |
| ubair-website | `CHPC-IMPLEMENTATION.md` | Website upload setup |

## Links

- [CHPC Portal](https://portal.chpc.utah.edu/)
- [Slurm Jobs](https://portal.chpc.utah.edu/slurm/jobs/)
- [Group Dashboard](https://portal.chpc.utah.edu/groups/lawson/)

---

**Last Updated:** 2026-05-13 — trimmed; canonical CHPC infra now lives in brc-knowledge.
**Maintainer:** John Lawson.

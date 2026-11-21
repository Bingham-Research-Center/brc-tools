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

## Synoptic token rotation

`brc_tools` never reads the Synoptic token itself — SynopticPy resolves it in
this order: explicit `token=` argument → `SYNOPTIC_TOKEN` env var →
`~/.config/SynopticPy/config.toml` (mode 0600). Nothing on CHPC exports
`SYNOPTIC_TOKEN`, so that config file is the single CHPC-side store. No CI
secret or repo `.env` carries it either (`clyfar/.env` and `ub-wx/.env.example`
hold placeholders only).

Rotating a public token touches four places. CHPC and the receivers hold
**independent** copies — a CHPC-only rotation leaves the sites' own live charts
broken:

| Where | What |
|-------|------|
| CHPC `~/.config/SynopticPy/config.toml` | `token = "..."` — every CHPC pull: obs cron, `ObsSource`, case studies, `clyfar`, `ub-wx` |
| `basinwx.com` → `/srv/ubair-website/.env` | `SYNOPTIC_API_TOKEN` (the server also accepts `SYNOPTIC_API_KEY`), then `pm2 restart` — backs the live `/api/synoptic/*` proxy |
| `basinwx.dev` → `/srv/ubair-website/.env` | same var + restart |
| live previews → `/srv/ubair-website-preview-<user>/.env` | same var + `scripts/manage-previews.sh update <user>` |

Install on CHPC without exposing the token on a command line:
`~/gits/preprint-clyfar-v0p9-five-winter/scripts/install_rotated_synoptic_token.py`
(getpass prompt, atomic 0600 write, zero network calls). Then verify:

```bash
cd /tmp && python -c "from synoptic.services import Metadata; print(Metadata(stid=['KVEL']).df().height)"
tail -6 ~/logs/obs.log     # next */5 run should upload to PRIMARY and MIRROR
tail -3 ~/logs/basinwx/push_receipts.jsonl   # one JSON line per attempt: ts, role, url, file, attempt, stage, status, verified
```

**SynopticPy prints the token verbatim in its auth-failure traceback**, so
`~/logs/obs.log` holds the dead secret after any bad-token episode — scrub it
and keep the log 0600. Never park a token in `~/.bashrc*`, commented out or
otherwise: two mislabelled `DATA_UPLOAD_API_KEY` comments there held the
Synoptic token until the 2026-08-26 rotation.

## Cron jobs (active production)

`~/.bashrc`, `~/gits/`, `~/logs/` are CHPC-side paths in the lines below.

```bash
# Observations — every 5 min. Must run from notchpeak1 (login node);
# compute nodes can't reach external APIs. See [[ops_cron_host]] memory.
# Env is clyfar-nov2025 (NOT brc-tools-2026) — test changes to the obs
# path in BOTH envs before committing to the production checkout.
*/5 * * * * /bin/bash -c 'source ~/.bashrc_basinwx && source ~/software/pkg/miniforge3/etc/profile.d/conda.sh && conda activate clyfar-nov2025 && python ~/gits/brc-tools/brc_tools/download/get_map_obs.py >> ~/logs/obs.log 2>&1'

# HRRR road forecast — hourly (website hard-rejects init_time > 3 h)
20 * * * * ~/gits/brc-data-ops/cron/run_road_forecast_push.sh

# HRRR surface layers — 4× daily. PILOT since 2026-11-21 on env brc-tools-2026-11
# (Herbie 2026.10.0); revert by dropping the CONDA_ENV= prefix.
45 0,6,12,18 * * * CONDA_ENV=brc-tools-2026-11 ~/gits/brc-data-ops/cron/run_hrrr_surface_push.sh

# HRRR waypoint forecast — hourly
50 * * * * ~/gits/brc-data-ops/cron/run_hrrr_waypoint_push.sh

# HRRR KVEL crosswind (15-min subh) — hourly
55 * * * * ~/gits/brc-data-ops/cron/run_hrrr_kvel_crosswind_push.sh

# Clyfar forecasts — SEASONAL, comment out ~end of March, re-enable ~October
15 3,9,15,21 * * * /bin/bash -c 'source ~/.bashrc_basinwx && export PATH=$PATH:/uufs/notchpeak.peaks/sys/installdir/slurm/std/bin && cd ~/gits/clyfar && sbatch scripts/submit_clyfar.sh >> ~/logs/clyfar_submit.log 2>&1'
```

**Times are notchpeak1 local time (America/Denver): the crontab sets no `CRON_TZ`.** The
surface job's `45 0,6,12,18` is 07:45/13:45/19:45/01:45 UTC under MST and an hour earlier
under MDT. This block matches `crontab -l` on notchpeak1 as read 2026-11-21 (six jobs).
**The crontab and the four HRRR wrappers belong to `brc-data-ops` since 2026-11-21**:
its `crontab/notchpeak1.crontab` is the reviewed copy, its `cron/` holds the wrappers
(each with a 40-min time limit), and its runbook covers backups and rollback. The
wrappers `cd` into this tree and run `scripts/export_hrrr_*.py` and
`python -m brc_tools.download.get_road_forecast`, so those CLIs are a seam: change
them in step with brc-data-ops. Every model job is HRRR: nothing fetches or uploads
RRFS. The wrappers default to `CONDA_ENV=brc-tools-2026`, whose Herbie (2026.3.0)
cannot reach the operational RRFS feed.

The repo checkout `~/gits/brc-tools` **is production** for these jobs — the
obs cron imports from the working tree. Keep it on `main`, never dirty;
do feature work in a worktree.

## HRRR surface layer export (BasinWX)

CLI: `scripts/export_hrrr_surface_layers.py`. `--server-url` sends to one host
instead of the fan-out, which is the `.dev`-only rehearsal route. JSON stages to
`~/.cache/brc-tools/basinwx` by default (`--output-dir` to override) before upload,
never into the repo checkout.

```bash
conda activate brc-tools-2026 && cd ~/gits/brc-tools
python scripts/export_hrrr_surface_layers.py --upload --server-url https://www.basinwx.dev
```

The scheduled job is brc-data-ops `cron/run_hrrr_surface_push.sh`.

## brc-tools-specific pitfalls

| Issue | Cause | Fix |
|-------|-------|-----|
| Upload fails | Wrong hostname | Uploader must run from `*.chpc.utah.edu`; the ubair-website server enforces this via `x-client-hostname` header |
| `ModuleNotFoundError: brc_tools` | PYTHONPATH unset or wrong env | Activate the env and re-source `~/.bashrc` |
| Conda not found | Shell not initialised | `source ~/software/pkg/miniforge3/etc/profile.d/conda.sh` |
| `df` reports "Too many levels of symbolic links" on a group volume | autofs fault on this node | Try a different node; volume may still be intact elsewhere |
| Synoptic `stream_flow` / `gage_height` queries return zero stations | The token lacks the **USGS HYDRO** network (`mnet_id=203`) — it's a separate entitlement, not bundled with state/20-yr access | Email `support@synopticdata.com` to add network 203; meanwhile pull gauges directly from **USGS NWIS** (`pip install dataretrieval`, or `https://waterservices.usgs.gov/nwis/`) |

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

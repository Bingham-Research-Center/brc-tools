# `brc-tools` — Bingham Research Center Python tools

> AI agents: see [`CLAUDE.md`](CLAUDE.md) for project context.
> Documentation index: [`docs/`](docs/). Current focus: HRRR/RRFS ingest in [`docs/nwp/`](docs/nwp/).
> New here (and not a meteorologist)? Start with [`docs/walkthroughs/`](docs/walkthroughs/) — one short copy-paste page per tool, plus a glossary.

Shared Python utilities for atmospheric data operations at the Bingham
Research Center. Pulls weather observations (SynopticPy) and NWP model
data (Herbie/HRRR) and pushes JSON to the [BasinWX](https://www.basinwx.com)
website.

**Mental model (new here?):** fetch weather data (station observations + model
forecasts) → tidy it into a common shape → ship small JSON files to the website that
draws the Uinta Basin's air-quality dashboards. Almost everything in the package hangs
off that one flow. Not a meteorologist? Start with [`docs/walkthroughs/`](docs/walkthroughs/).

Package name: `brc_tools` (underscore). Repo name: `brc-tools` (hyphen).

## Installation

```bash
pip install -e .          # core deps
pip install -e ".[dev]"   # + pytest, ruff, mypy, jupyter
```

Conda/mamba (recommended on CHPC — curated, bundles the GRIB/cartopy stack):
```bash
mamba env create -f environment.yml   # env "brc-tools-2026"; then: pip install -e . --no-deps
# On CHPC two envs already exist: brc-tools-2026 (Herbie 2026.3.0) and brc-tools-2026-11
# (Herbie 2026.10.0, needed for RRFS). Which runs what: docs/ENVIRONMENT-SETUP.md
```

## Quick usage

```python
from brc_tools.nwp import NWPSource
from brc_tools.nwp.derived import add_wind_fields, add_theta_e
from brc_tools.visualize.planview import plot_planview_evolution

src = NWPSource("hrrr")
ds = src.fetch(init_time="2025-02-22 12Z", forecast_hours=range(0, 13),
               variables=["temp_2m", "wind_u_10m", "wind_v_10m", "mslp"],
               region="uinta_basin")
ds = add_wind_fields(ds)
fig = plot_planview_evolution(ds, "wind_speed_10m", cmap="YlOrRd")
```

See `scripts/` for full case study examples.

Historical satellite context uses the portable NASA CMR/GIBS renderer documented in
[`docs/MODIS-CONTEXT-RENDERER.md`](docs/MODIS-CONTEXT-RENDERER.md); it does not require
WRF, Slurm, GDAL, or an Earthdata login.

## Claude Code skills

Repo-local skills (slash commands) live in `.claude/skills/`. Each drives a
TOML-configured engine in `scripts/`, submits to CHPC SLURM, and writes figures
**outside** the checkout.

There are **three WRF figure engines and they are not interchangeable** — pick by the
question you are asking:

| skill | question it answers | engine | doc |
|---|---|---|---|
| [`/wrf-full-figures`](.claude/skills/wrf-full-figures/SKILL.md) | publication figure set for a study (300-DPI quicklook equivalents, difference maps, heat-deficit diagnostics) | `scripts/wrf_figures.py` | [`docs/WRF-FIGURE-ENGINE.md`](docs/WRF-FIGURE-ENGINE.md) |
| [`/wrf-basin-winds`](.claude/skills/wrf-basin-winds/SKILL.md) | drainage and basin winds — 10 m wind plan views plus terrain-filled curtains on **native eta levels** along named transects | `scripts/wrf_winds.py` | [`docs/WRF-WINDS.md`](docs/WRF-WINDS.md) |
| [`/wrf-convective`](.claude/skills/wrf-convective/SKILL.md) | storm diagnosis — reflectivity, **reflectivity sampled on a real radar's beam surfaces** with the observed scan beside it, gust swaths, updraft helicity, skew-T with parcel path, hodographs, station verification from `tslist` | `scripts/wrf_convective.py` | [`docs/WRF-CONVECTIVE.md`](docs/WRF-CONVECTIVE.md) |

Plus one non-WRF renderer:

- [`/basin-forecast-funnel`](.claude/skills/basin-forecast-funnel/SKILL.md) — synoptic
  montage (250 hPa jet → 500 hPa flow → 600 hPa moisture/LLJ → surface analysis) for an
  analysis time: NAM up to 2026-11-03, GFS 0.25° after NAM's retirement. Doc:
  [`docs/FORECAST-FUNNEL.md`](docs/FORECAST-FUNNEL.md).

### How to use these skills — example prompts

A skill is a **prompt, not a command line**. Type `/wrf-basin-winds`, or just describe
the job, and the skill asks back for the three things it refuses to guess — the case,
the families, and the times — because each one changes what the job costs and what it
answers. You do not need to know the flags. You do need to know which run you mean.

**Have the case TOML ready first.** The engines are case-agnostic, so every case needs a
declarative recipe — transects, profile points, colour limits — and it lives in the repo
that owns the case, never here. A case with no TOML starts by writing one; the schema and
a worked example are in [`docs/WRF-WINDS.md`](docs/WRF-WINDS.md).

#### A drainage run, plotted every hour

The thread below is the ordinary shape of this work: write the recipe, smoke-test one
time, then sweep. Substitute your own case and run.

**1 — the recipe, if the case has none yet.**

```
/wrf-basin-winds — new case. <experiment dir> has no figures.toml. Write one,
modelled on the ashley-drainage-600m file: d01 for context, d02 for the valley,
transects along and across the drainage, profiles at the source / floor / exit,
and a view3d for the cold pool. Run dir is <run>/wrf_run. It is a November night,
so retune the theta_2m / temp_2m / pblh scales off the September values. Show me
the TOML before rendering anything.
```

**2 — one time, every family, before committing to a sweep.** A family that was never
smoke-tested is how a whole submitted job has been lost before.

```
/wrf-basin-winds — smoke-test <case>: one valid time, all four families, both
nests. Use the deepest night hour. Dry-run first and tell me the figure count,
then submit on the DTN and tell me which files to open.
```

**3 — the hourly sweep.** `--hourly` is `--every 60`; when the run writes hourly history
it is also `--all`. Say the window explicitly — without `--start`/`--end` a fine cadence
over a long run is a figure count nobody intended.

```
/wrf-basin-winds — sweep <case> hourly across the whole window, <init> to <end>.
Dry-run for the count first; I want a go/no-go before it queues. Use
--skip-existing so the smoke-test figures are not re-rendered, and set --w-exag
for a drainage night rather than the afternoon value in the TOML.
```

**4 — narrow once you know what the sweep showed.** Cheaper and more legible than
re-running everything.

```
/wrf-basin-winds — just the night, please: sections and profiles only, d02 only,
23Z through 15Z, hourly.
```

**5 — coverage, which `find` cannot answer.** It cannot tell a figure that failed from
one never asked for; `--report` reads the manifests and can.

```
/wrf-basin-winds — do we actually have every figure for <case>? Report coverage
from the manifests in the output root, then re-render anything that failed.
```

A sweep can also run **against a job that is still writing**: with no time flag the
engine renders the latest time present on every requested domain, and `--skip-existing`
regenerates any figure older than the files it derives from, so re-running as the run
advances is safe and cheap.

#### The other three

```
/wrf-convective — did the simulated cell verify? Composite reflectivity and the
0.5° beam view beside the observed KGJX scan, plus tslist at the nearest station.
```
```
/wrf-full-figures — publication set for <study case>, difference maps included.
```
```
/basin-forecast-funnel — synoptic funnel for the 12Z analysis on <date> (GFS after 3 Nov 2026).
```

**One trap worth knowing before you pick.** `/wrf-full-figures` reads only the
colon-separated `wrfout` filename convention, so on a run built with `nocolons = .true.`
(`wrfout_d02_2025-11-21_12_00_00`) it reports "no wrfout" and renders nothing. The two
sweep engines accept either convention. That alone decides the engine for some runs,
regardless of which question you were asking.

### Which figure answers which question

The two sweep engines pick families with `--figure` (repeatable):

| `/wrf-basin-winds` | answers |
|---|---|
| `topdown` | what the surface looks like — wind, θ₂ₘ, PBLH, surface decoupling (TSK−T₂ₘ), snow, 10 m convergence |
| `section` | vertical structure along a named A→B line, on the model's own eta cells |
| `profile` | how deep the stable layer is, and whether the air above it is dry enough to mix down |
| `view3d` | how far the cold pool has filled the basin |

| `/wrf-convective` | answers |
|---|---|
| `surface` | where the storm is — reflectivity, gust swath, updraft helicity, echo top, vorticity |
| `meso` | what it is running into — θₑ, dewpoint, convergence, moisture-flux convergence |
| `aux` | the same at the high-cadence stream's interval, for a feature the history aliases |
| `section` | vertical structure — reflectivity / `w` / θ curtains |
| `beam` | **what the radar would have seen**, on real beam surfaces, optionally beside the observed scan |
| `sounding` | the environment — skew-T with parcel path, plus a hodograph |
| `verify` | whether it happened at the right time at a real station (`tslist`) |
| `track` | where the strongest echo went — a CSV, not a figure |

Both engines share `--start`/`--end`, `--every`, `--dry-run`, `--skip-existing`,
`--report` and `--allow-errors`.

Before a first sweep on a new case, read [`docs/VISUAL-SUITE-SOP.md`](docs/VISUAL-SUITE-SOP.md) —
the engine-agnostic procedure, the method errors already found, and the gaps still open.
Two habits it exists to enforce: **render one time from every family and actually open
the files before sweeping**, and **state the physical surface** (beam tilt, height,
layer, accumulation window) on the figure itself.

Per-case configuration lives in the repo that owns the case, never here — e.g.
`../ub-wx/experiments/20251011-ashley-rotating-cell/figures.toml`, or
`../latex-jrl-mjd-mdpiair-2026/verification/config/figures/pelican2013.toml`.

## CHPC Deployment

*Operations reference — a junior dev can skip this on day one and come back when you actually deploy.*

On CHPC, this checkout (`~/gits/brc-tools`) is the code the BasinWX crons run, so keep it
on `main` and clean. **The crontab and the cron wrappers live in the private
[`brc-data-ops`](https://github.com/Bingham-Research-Center/brc-data-ops) repo** (since
2026-11-21). They `cd` here and run the export entry points in `scripts/`, so those
command lines are a cross-repo seam.

**Canonical reference:** [`docs/CHPC-REFERENCE.md`](docs/CHPC-REFERENCE.md)

- **Observation job:** `brc_tools/download/get_map_obs.py` (still a direct crontab line, every 5 min)
- **Upload module:** `brc_tools/download/push_data.py` (fan-out, retries, receipts)
- **Secrets:** `DATA_UPLOAD_API_KEY` in the environment. The Synoptic token lives in
  `~/.config/SynopticPy/config.toml` on CHPC (`SYNOPTIC_TOKEN` elsewhere).

**Cross-repo data contract:** see [`docs/CROSS-REPO-SYNC.md`](docs/CROSS-REPO-SYNC.md).

### Path and storage hygiene

Keep **source code in the repo** and **runtime outputs outside the repo checkout**.
This matters on CHPC: large ignored trees under `~/gits/brc-tools/` slow `git status`
and make source-vs-generated files harder to reason about.

| Do | Don't |
| --- | --- |
| Use `/scratch/general/vast/$USER/...` for large reproducible outputs (WRF inputs, GRIB staging, bulk downloads). | Do **not** stage large runtime data under `~/gits/brc-tools/data/` or other repo-local paths. |
| Use `~/.cache/brc-tools/...` or an env var such as `BRC_TOOLS_HERBIE_CACHE` for per-user caches. | Do **not** hard-code a specific user's home path such as `/uufs/chpc.utah.edu/common/home/u0737349/...`. |
| Use `/tmp` / `tempfile.gettempdir()` for short-lived temp files and lock files. | Do **not** leave scratch, temp, cache, or lock artifacts in tracked source directories. |
| Use relative repo paths only for committed assets such as docs, schemas, and test fixtures. | Do **not** write generated JSON, GRIB, logs, or cache files into the repo unless they are intentional fixtures/examples. |

### Upload destinations (fan-out)

Uploads can target one or more servers (e.g. production + dev). Resolution
order used by `load_config_urls()` in `brc_tools/download/push_data.py`:

1. `BASINWX_API_URLS` env var — comma-separated list. First URL is primary
   (failure raises), remaining URLs are best-effort mirrors (failure logged
   as WARN but non-fatal).
2. `~/.config/ubair-website/website_urls` — same format, file fallback.
3. `~/.config/ubair-website/website_url` — legacy single-URL file, preserved
   for back-compat.

A failed DNS lookup, a refused or timed-out connection, or a `502`/`503`/`504` is tried
again (`BASINWX_UPLOAD_ATTEMPTS`, default 3). Every attempt adds one line to
`~/logs/basinwx/push_receipts.jsonl`.

Full endpoint/auth/schema contract: [`docs/WEBSITE-INTEGRATION.md`](docs/WEBSITE-INTEGRATION.md).

### Why `send_json_to_server` is preserved

`brc_tools.download.push_data.send_json_to_server(server, fpath, bucket, key)`
retains its original single-URL signature because **the `clyfar` repo imports
it directly**. New brc-tools code should use `send_json_to_all(urls, ...)`
instead. `clyfar`'s exporter has migrated to `send_json_to_all`; its
`setup-chpc.sh` smoke check still imports the legacy name, so the function stays.

## Open threads / TODO

Active backlog and open action items live in [`WISHLIST-TASKS.md`](WISHLIST-TASKS.md)
(the canonical prioritised backlog). Cross-repo WRF state lives in
[`docs/WRF-STAGING-STATE-PLAYBOOK.md`](docs/WRF-STAGING-STATE-PLAYBOOK.md).

### Upstream notes — Herbie

A couple of behaviours we hit while wiring up NCEI-historical GRIB staging on **Herbie
2025.11.3**, recorded for our own reference — not bug reports, and not a claim our reading
is the intended design (Herbie is excellent and we lean on it heavily):

- The `rap_historical` template raised `ValueError: Invalid suffix 'grb.inv'` for a 2013
  analysis date; that `IDX_SUFFIX` entry reads differently from the dotted `.grb.inv` used
  elsewhere in the same file. We fetch the NCEI RAP-130 analysis directly instead — the same
  URL the template builds.
- `rap_ncei` / `nam` didn't resolve our 2013 targets (RAP-130 lives under
  `…/access/historical/…`; Herbie's `nam` is operational-only).

These are pinned to one version and may already differ upstream (latest is 2026.10.0, checked 2026-11-20) —
worth re-checking after each upgrade.

On **Herbie 2026.3.0 and 2026.10.0** the index download (`requests.get(self.idx)`) and the
file checks (`requests.head(url)`) pass no timeout. One silent S3 connection can then
block a job indefinitely: four cron runs sat for 2–3 days on 18–19 Nov 2026. brc-tools
gives those calls a timeout with `brc_tools.nwp._http.ensure_request_timeouts()`, and new
code that calls Herbie directly should call it too. Full per-source rationale:
[`docs/nwp/NWP-SOURCE-MATRIX.md`](docs/nwp/NWP-SOURCE-MATRIX.md).

## Authors

John Lawson and Michael Davies, Bingham Research Center, 2025

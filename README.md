### `brc-tools` - Bingham Research Center (python) Tools

> AI agents: see [`CLAUDE.md`](CLAUDE.md) for project context.
> Documentation index: [`docs/`](docs/). Current focus: HRRR/RRFS ingest in [`docs/nwp/`](docs/nwp/).

Shared Python utilities for atmospheric data operations at the Bingham
Research Center. Pulls weather observations (SynopticPy) and NWP model
data (Herbie/HRRR) and pushes JSON to the [BasinWX](https://www.basinwx.com)
website.

Package name: `brc_tools` (underscore). Repo name: `brc-tools` (hyphen).

## Installation

```bash
pip install -e .          # core deps
pip install -e ".[dev]"   # + pytest, ruff, mypy, jupyter
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

## CHPC Deployment

This package is deployed on CHPC to push weather data to BasinWX.

**Canonical reference:** [`docs/CHPC-REFERENCE.md`](docs/CHPC-REFERENCE.md)

- **Production script:** `brc_tools/download/get_map_obs.py`
- **Upload module:** `brc_tools/download/push_data.py`
- **Required env vars:** `DATA_UPLOAD_API_KEY`, `SYNOPTIC_TOKEN`

**Cross-repo data contract:** see [`docs/CROSS-REPO-SYNC.md`](docs/CROSS-REPO-SYNC.md).

## Authors

John Lawson and Michael Davies, Bingham Research Center, 2025

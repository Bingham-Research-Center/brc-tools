# Pull weather observations — walk-through

**What / why:** Get real measurements from weather stations (temperature, wind,
pressure…) for the Uinta Basin. You'd run this to see what *actually happened*,
or to find past events worth studying.

**Needs:** `SYNOPTIC_TOKEN` (or `~/.config/SynopticPy/config.toml`) · conda env `brc-tools`

## Get a station time series

```python
from brc_tools.obs import ObsSource

obs = ObsSource()
df = obs.timeseries(
    waypoint_group="foehn_path",          # or: stids=["KVEL", "KPVU"]
    start="2025-02-22 12Z",
    end="2025-02-23 06Z",
    variables=["temp_2m", "wind_speed_10m", "mslp"],
)
```

**Produces:** a Polars DataFrame — columns `stid`, `valid_time` (UTC), one per
variable, plus `waypoint` when you pass a group.

## Find events automatically (scanner)

Scan a station month-by-month and rank candidate days against a rule:

```python
from brc_tools.obs.scanner import scan_events, detect_foehn

events = scan_events(
    stid="KVEL",
    variables=["temp_2m", "dewpoint_2m", "wind_speed_10m", "wind_dir_10m"],
    months=(3, 4, 5), year=2025,
    criteria_fn=detect_foehn,             # or detect_wind_ramp
)
# events: list of dicts, best first — e.g. {"date": "2025-04-15", "score": ...}
```

**See also:** signatures → [`API-REFERENCE.md` → ObsSource / scanner](../API-REFERENCE.md) · terms (foehn, waypoint, MSLP) → [GLOSSARY.md](GLOSSARY.md)

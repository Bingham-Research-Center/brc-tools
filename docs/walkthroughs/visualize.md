# Make maps and time-series plots — walk-through

**What / why:** Turn model/obs data into figures — a map at one time, a map's
evolution over forecast hours, or stacked station time series. You'd run this to
eyeball a forecast or build case-study figures.

**Needs:** matplotlib + cartopy (in the `brc-tools` env) · conda env `brc-tools`

## A map (plan view)

```python
import matplotlib.pyplot as plt
from brc_tools.visualize import plot_planview

plot_planview(ds, "wind_speed_10m", time_idx=6, wind_barbs=True)   # ds from nwp-download
plt.savefig("windmap.png", dpi=150, bbox_inches="tight")
```

Multi-panel time evolution (one panel per forecast hour):

```python
from brc_tools.visualize import plot_planview_evolution
plot_planview_evolution(ds, "temp_2m", ncols=3)
```

## Station time series (multi-run + obs)

```python
from brc_tools.visualize import plot_station_timeseries

nwp_series = {"15Z": nwp_df_15z, "16Z": nwp_df_16z}   # {run label: DataFrame}
fig = plot_station_timeseries(nwp_series, "temp_2m", obs_df=obs_df)
fig.savefig("timeseries.png", bbox_inches="tight")
```

**Produces:** matplotlib `Axes`/`Figure` objects — save them with `savefig`.

**See also:** signatures → [`API-REFERENCE.md` → visualize](../API-REFERENCE.md) · terms → [GLOSSARY.md](GLOSSARY.md)

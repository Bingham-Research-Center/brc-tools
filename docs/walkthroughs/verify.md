# Score a forecast against observations — walk-through

**What / why:** Measure how close a forecast was to reality, per station and
variable (bias, MAE, RMSE, correlation). You'd run this to compare model runs or
track skill over a case.

**Needs:** nothing (works on DataFrames you already have) · conda env `brc-tools`

## One call: pair and score

```python
from brc_tools.verify.deterministic import paired_scores

scores = paired_scores(
    nwp_df,                                # from NWPSource.extract_at_waypoints()
    obs_df,                                # from ObsSource.timeseries()
    variables=["temp_2m", "wind_speed_10m"],
    tolerance_minutes=30,                  # how close in time a match must be
)
# scores columns: waypoint, variable, n_obs, bias, mae, rmse, correlation
```

`paired_scores` joins the two frames in time and harmonizes units for you, so you
don't pre-align. For one-off math on plain arrays there are scalar helpers too:

```python
from brc_tools.verify.deterministic import rmse, bias
rmse(forecast_array, observed_array)
```

**Produces:** a Polars DataFrame, one row per (waypoint, variable).

**See also:** signatures → [`API-REFERENCE.md` → verify.deterministic](../API-REFERENCE.md) · terms → [GLOSSARY.md](GLOSSARY.md)

# Pull EPA air-quality observations (AQS AirData) — walk-through

**What / why:** Get quality-assured ozone, PM2.5, and other monitor data from
EPA's AirData bulk files — including the Uinta Basin tribal/regulatory sites.
This is the citable AQ record for study periods where Synoptic has nothing
(e.g. winter 2012-13 basin ozone).

**Needs:** internet only — anonymous, no key.  Hourly ozone is ~66 MB zipped
per year; daily is ~5 MB.  Files cache in `BRC_TOOLS_AQS_CACHE`
(default `~/.cache/brc-tools/aqs`) with a `*.meta.json` provenance sidecar
(URL, retrieval time, server Last-Modified) — record that vintage in studies,
because EPA regenerates these files as QA updates land.

## Get the winter-ozone episode record

```python
from brc_tools.api.aqs import download_airdata, load_airdata, basin_site_ids

zp = download_airdata("daily", "ozone", 2013)      # ~5 MB, cached
df = load_airdata(zp, sites=basin_site_ids(),
                  start="2013-01-01", end="2013-02-28")
```

**Produces:** a Polars frame of EPA's daily summaries — `"1st Max Value"` on
the `Pollutant Standard == "Ozone 8-hour 2015"` rows is the regulatory MDA8
(ppm). **Don't recompute MDA8 from hourly data**; EPA already applied the
completeness and day-assignment rules. Hourly files (`kind="hourly"`) gain a
tz-naive UTC `valid_time` column for diurnal structure.

## CLI

```bash
python scripts/fetch_aqs_airdata.py --param ozone --kind daily --years 2013 \
    --basin --start 2013-01-01 --end 2013-02-28 \
    --out /scratch/general/vast/$USER/aqs_ozone_daily.parquet
```

`--basin` uses the verified Uinta Basin registry (`UINTA_BASIN_SITES`): Ouray,
Redwash, Whiterocks, Myton (Ute Indian Tribe — filed under normal FIPS codes,
not "TT" tribal codes), Roosevelt, Vernal, Fruitland (UDAQ), Dinosaur NM and
Rangely (NPS), Little Mountain (USFS). The Enefit industry monitor is excluded
by default (2013 data flagged incomplete). PM2.5 at the tribal sites lives in
`--param pm25_nonfrm` (88502), not the FRM 88101 file.

**Not here:** USU study sites (Horsepool, Seven Sisters, Pariette Draw) are
not in AQS — use the BRC public Box downloads
(usu.edu/binghamresearch/data-access.php) or the NOAA CSL UBWOS archive
(PI-contact data policy).

**See also:** signatures → [`API-REFERENCE.md`](../API-REFERENCE.md) ·
Synoptic weather obs → [obs.md](obs.md) · radiosondes → `brc_tools.api.soundings`

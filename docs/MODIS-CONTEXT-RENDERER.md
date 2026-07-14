# MODIS context renderer

`brc_tools.satellite.modis` makes a provenance-bearing MODIS context figure without
requiring WRF, Slurm, GDAL, rasterio, SatPy, or an Earthdata login.

It has two separate NASA inputs:

1. **CMR granule metadata** identifies the daytime Terra/Aqua swath covering the center
   of the requested map whose temporal midpoint is closest to a target UTC timestamp.
2. **GIBS WMS imagery** supplies a georeferenced corrected-reflectance PNG for that
   platform and calendar date.

That distinction is important: GIBS has a daily time dimension, not a granule-time
selector. The JSON provenance sidecar therefore records both the exact closest CMR
granule and the exact daily GIBS request without describing the map as a raw swath crop.

## Portable dependency contract

The online path needs only dependencies already in the `brc-tools` core environment:

- `requests` for CMR and GIBS;
- Matplotlib + Pillow for PNG decoding and PNG/PDF output;
- NumPy, already required by Matplotlib and `brc-tools`.

The implementation intentionally avoids the heavier HDF-EOS/geolocation route. This
makes the same command usable on Akamai, a workstation, a CHPC login/DTN node, or an
offline CHPC compute node after its small cache has been staged. The WRF optional extra
(`netCDF4`, MetPy, and Siphon) is unrelated and is not required.

Use the curated environment when creating a new installation:

```bash
mamba env create -f environment.yml
conda activate brc-tools-2026
pip install -e . --no-deps
```

An existing environment is sufficient if this succeeds:

```bash
python -c "import matplotlib, numpy, requests; print('MODIS renderer dependencies OK')"
```

## Uinta Basin example

Set output and cache locations outside the `brc-tools` checkout:

```bash
export BRC_TOOLS_MODIS_CACHE="$HOME/.cache/brc-tools/modis"
export BRC_TOOLS_OUTPUT="$HOME/brc-tools-output"
mkdir -p "$BRC_TOOLS_OUTPUT"

python scripts/render_modis_context.py \
  --target 2013-02-02T18:00:00Z \
  --bbox -111.8 39.2 -108.2 41.5 \
  --output "$BRC_TOOLS_OUTPUT/modis_uinta_20130202_near1800" \
  --products true-color,snow-false-color \
  --marker Vernal,-109.529,40.455 \
  --marker Ouray,-109.677,40.090
```

The command queries both platforms by default. For this target and map center, CMR
selects Terra granule `MOD02HKM.A2013033.1815.061.2017294153853.hdf`, acquired
18:15--18:20 UTC. Its 18:17:30 midpoint is 17.5 minutes after the 18:00 UTC target;
the closest Aqua granule is 19:55--20:00 UTC.

Outputs are:

- `*.png` and `*.pdf`: the rendered figure;
- `*.provenance.json`: target, selection rule, every candidate granule, exact CMR and
  GIBS URLs, layer names, cache basenames, renderer-source hash, Python/dependency
  versions, and output hashes;
- cached raw GIBS PNG and CMR response under `$BRC_TOOLS_MODIS_CACHE`.

Use `--products snow-false-color` for a single snow-discrimination panel. The default
comparison is useful for inspection: true color is intuitive, while MODIS bands 7-2-1
normally show snow and ice as cyan and most liquid cloud as white. Ice cloud can also
appear cyan, so the image is snow context rather than a validated fractional-snow map.

## Offline and cross-host use

Run the command once on any host with outbound HTTPS. A later render with the identical
target, bounding box, dimensions, platform choice, and products can be made without
network access:

```bash
python scripts/render_modis_context.py \
  --target 2013-02-02T18:00:00Z \
  --bbox -111.8 39.2 -108.2 41.5 \
  --output "$BRC_TOOLS_OUTPUT/modis_uinta_20130202_near1800" \
  --cache-dir "$BRC_TOOLS_MODIS_CACHE" \
  --offline
```

If a CHPC compute node cannot reach NASA, populate the cache on a login or DTN node and
make that cache path visible to the compute job. Do not pass an Akamai path to CHPC or a
CHPC path to Akamai; either rerun the small download on each networked host or copy the
cache explicitly.

The map canvas has fixed pixel dimensions for a given panel count and DPI. Font and
FreeType builds can still change text antialiasing by a few pixels across environments;
the sidecar records runtime versions and the exact output hash, while the cached NASA
raster has its own independent hash.

`--refresh` replaces matching cache entries. It cannot be combined with `--offline`.

## Scientific and technical limits

- The CMR query requires the granule footprint to cover the **map center**. This avoids
  choosing an adjacent five-minute swath that merely touches the bounding box.
- GIBS corrected reflectance is a browse/visualization product. It is suitable for
  episode context, not quantitative snow-cover retrieval or model validation.
- The 7-2-1 panel distinguishes most cloud from snow better than true color, but ice
  cloud may still be cyan.
- For quantitative snow fraction, cloud masks, or a strict raw-granule crop, add a
  separate authenticated Level-1B/Level-2 pipeline and its heavier geolocation stack;
  do not silently reinterpret this renderer.

## Primary documentation

- [NASA GIBS Python/WMS example](https://nasa-gibs.github.io/gibs-api-docs/python-usage/)
- [NASA GIBS access basics](https://nasa-gibs.github.io/gibs-api-docs/access-basics/)
- [NASA CMR search API](https://cmr.earthdata.nasa.gov/search/site/docs/search/api.html)
- [MOD02HKM Collection 6.1](https://doi.org/10.5067/MODIS/MOD02HKM.061)
- [NASA explanation of MODIS 7-2-1 snow/cloud colors](https://modis.gsfc.nasa.gov/gallery/individual.php?db_date=2026-05-11)

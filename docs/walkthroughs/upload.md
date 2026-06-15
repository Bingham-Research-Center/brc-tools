# Push JSON to the BasinWX website — walk-through

**What / why:** Send a finished JSON product to the BasinWX site(s). The website
just displays whatever we upload, so this is the last step of an operational job.
Uploads **fan out** to every configured server (production + dev).

**Needs:** `DATA_UPLOAD_API_KEY` (32-char hex) · `BASINWX_API_URLS` (comma list;
first = primary) · conda env `brc-tools`. The full data contract is in
[WEBSITE-INTEGRATION.md](../WEBSITE-INTEGRATION.md).

## Run an operational producer (easiest)

```bash
# Latest Basin observations → JSON → upload
python brc_tools/download/get_map_obs.py

# Latest HRRR surface layers → JSON → upload
python scripts/export_hrrr_surface_layers.py --upload --region uinta_basin
```

## Upload your own JSON (library)

```python
from brc_tools.download.push_data import save_json, load_config_urls, send_json_to_all

save_json(my_df, "/tmp/forecast.json", orient="records")
api_key, urls = load_config_urls()                 # from env / ~/.config
results = send_json_to_all(urls, "/tmp/forecast.json", "forecasts", api_key)
# results: {url: True/False}; the primary must succeed or it raises
```

**Produces:** files named `{prefix}_{YYYYMMDD_HHMM}Z.json`, POSTed to each server.
Check health at `{url}/api/health`.

> `send_json_to_server` (the single-URL primitive) is imported by `clyfar` — don't
> change its signature without a cross-repo PR (see CLAUDE.md).

**See also:** signatures → [`API-REFERENCE.md`](../API-REFERENCE.md) · contract → [WEBSITE-INTEGRATION.md](../WEBSITE-INTEGRATION.md) · terms → [GLOSSARY.md](GLOSSARY.md)

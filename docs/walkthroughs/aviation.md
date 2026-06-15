# Aviation / flight data — walk-through

**What / why:** Look up flights and airport arrivals/departures via FlightAware.
Used for aviation-weather work around Basin airports (e.g. KVEL).

**Needs:** `FLIGHTAWARE_API_KEY` (or `~/.config/flightaware/api_key`) · conda env `brc-tools`

## Look up airport arrivals

```python
from brc_tools.api.flightaware import FlightAwareClient

client = FlightAwareClient()
arrivals = client.get_airport_arrivals("KVEL")     # also: get_flight("UAL123")
```

**Produces:** a dict (parsed FlightAware AeroAPI v4 JSON).

> **Heads up — experimental:** the FlightRadar24, Perplexity, and Mistral clients
> under `brc_tools/api/` are stubs / paid-only and not wired into anything yet.
> Don't rely on them. Auth for all API clients is documented in
> [../API-CLIENTS.md](../API-CLIENTS.md).

**See also:** [../API-CLIENTS.md](../API-CLIENTS.md) · terms → [GLOSSARY.md](GLOSSARY.md)

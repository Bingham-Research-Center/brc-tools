# External API clients (`brc_tools.api`)

Thin Python wrappers for four external services. One subpackage each;
shared auth helper at `brc_tools.api._auth.load_api_key`. The clients
follow the same shape as `ObsSource` / `NWPSource`: a class with the
credential loaded in `__init__`, a handful of single-purpose methods,
no implicit retries.

| Service | Subpackage | Class | Env var | Notes |
|---------|-----------|-------|---------|-------|
| FlightAware AeroAPI | `brc_tools.api.flightaware` | `FlightAwareClient` | `FLIGHTAWARE_API_KEY` | Free tier ~$5/mo |
| FlightRadar24 | `brc_tools.api.flightradar24` | `FR24Client` | `FR24_API_KEY` | **Stub** — paid only, min ~$9/mo |
| Perplexity Sonar | `brc_tools.api.perplexity` | `PerplexityClient` | `PERPLEXITY_API_KEY` | Pay-per-request; OpenAI-compatible |
| Mistral | `brc_tools.api.mistral` | `MistralClient` | `MISTRAL_API_KEY` | Usage-based |

## Install

LLM clients pull large SDKs, so they live behind an extras group:

```bash
pip install -e ".[api]"   # adds openai + mistralai
```

CHPC cron deployments (HRRR upload, obs ingest) do not need this; the
core install stays minimal.

## Auth convention

`load_api_key(env_var, config_subpath=None)` reads the env var first
and optionally falls back to `~/.config/{config_subpath}` (first line
of the file). Raises `RuntimeError` if neither is set. Mirrors the
pattern in `brc_tools.download.push_data.load_config`.

## Quick examples

```python
# FlightAware
from brc_tools.api.flightaware import FlightAwareClient
fa = FlightAwareClient()
fa.get_airport_arrivals("KSLC")

# Perplexity (OpenAI-compatible Sonar endpoint)
from brc_tools.api.perplexity import PerplexityClient
ppl = PerplexityClient()
print(ppl.ask("What is the current PM2.5 forecast for Vernal UT?"))

# Mistral
from brc_tools.api.mistral import MistralClient
m = MistralClient()
print(m.chat([{"role": "user", "content": "Hello"}]))
```

## MCP servers

`.mcp.json` at the repo root configures two MCP servers that Claude
Code picks up automatically when run from this directory:

| Server | npm package | Verified |
|--------|-------------|----------|
| `perplexity` | `@perplexity-ai/mcp-server` | Official, maintained by Perplexity (2026-05) |
| `mistral` | `mistral-mcp` | Community; broad capability surface |

Set `PERPLEXITY_API_KEY` and/or `MISTRAL_API_KEY` in your shell env.
`npx` will download the server on first invocation.

**MCP vs Python wrapper — when to use which:**

- **MCP** is for agent workflows: Claude Code calls the server directly
  while you work. Best when you want the assistant itself to do a web
  search or fan out to a second model.
- **Python wrapper** is for scripted automation: a case-study script
  that wants to summarise a result, a batch job, anything reproducible.

The same API key works for both — Python and MCP read the same env var.

## Caveats

- **Perplexity is publicly de-prioritising MCP** in favour of their Agent
  API. The OpenAI-compatible REST API used by `PerplexityClient` is
  expected to remain; the MCP server may be deprecated in future.
- **FR24 is stubbed.** Subpackage exists for layout uniformity, but
  every method raises `NotImplementedError` until a subscription
  decision is made.
- **No retries built in.** Each client does one shot per call. Add
  `tenacity` and exponential backoff at the call site if needed; do
  not push the retry into the wrapper without a specific reason.
- **CHPC**: `pip install -e .` (no `[api]` extra) is enough for cron
  jobs. The api/ subpackage will still import — only instantiating the
  Perplexity/Mistral clients requires the extras.

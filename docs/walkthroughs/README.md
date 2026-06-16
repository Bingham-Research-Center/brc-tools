# brc-tools walk-throughs

Plain-language, copy-paste guides — one short page per tool. Written for a new
developer who is **not** a meteorologist. For full function signatures see
[../API-REFERENCE.md](../API-REFERENCE.md); for unfamiliar words see
[GLOSSARY.md](GLOSSARY.md).

## Step 0 — set up first

Everything below assumes the `brc-tools` conda env. If you haven't built it yet:
→ **[../ENVIRONMENT-SETUP.md](../ENVIRONMENT-SETUP.md)**.

## What this repo does (one sentence)

brc-tools pulls **observations** (Synoptic) and **model data** (Herbie), then
**scores**, **plots**, and **uploads** them to the BasinWX website — and stages
GRIB for WRF, stopping at the `brc-wrf` boundary.

## Who should read what

| You are… | Start here |
| --- | --- |
| New dev, not a meteorologist | [GLOSSARY](GLOSSARY.md) → [obs](obs.md) → [nwp-download](nwp-download.md) |
| Running the operational website push | [upload](upload.md) (+ [contract](../WEBSITE-INTEGRATION.md)) |
| Investigating a weather event | [case-study](case-study.md) → [../CASE-STUDY-GUIDE.md](../CASE-STUDY-GUIDE.md) |
| Staging WRF inputs | [wrf-staging](wrf-staging.md) → [../WRF-INPUT-STAGING.md](../WRF-INPUT-STAGING.md) |

## Suggested reading order

[GLOSSARY](GLOSSARY.md) → [obs](obs.md) → [nwp-download](nwp-download.md) →
[verify](verify.md) → [visualize](visualize.md) → [upload](upload.md) → then
[case-study](case-study.md) / [aviation](aviation.md) / [wrf-staging](wrf-staging.md)
as needed.

## Spokes

- [obs.md](obs.md) — pull station observations; scan for events
- [nwp-download.md](nwp-download.md) — download model forecast grids
- [verify.md](verify.md) — score forecast vs. obs
- [visualize.md](visualize.md) — maps and time-series plots
- [upload.md](upload.md) — push JSON to the BasinWX website
- [case-study.md](case-study.md) — combine the above for one event
- [aviation.md](aviation.md) — FlightAware flight data
- [wrf-staging.md](wrf-staging.md) — stage WRF inputs, then hand off to `brc-wrf`
- [GLOSSARY.md](GLOSSARY.md) — shared term list

## Not covered here (experimental / stub, by design)

No walk-throughs exist for these because they aren't ready — don't go hunting:
`verify/infogain` (empty stub), the FlightRadar24 / Perplexity / Mistral API
clients (stubs / paid-only), and the unexported `visualize/crosssection` +
`visualize/profile` helpers.

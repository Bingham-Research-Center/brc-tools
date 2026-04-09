# NWP / HRRR / RRFS work

Active work area for the HRRR/RRFS data ingest → BasinWX pipeline.

## Current scope (Phase 1)
HRRR hourly + Synoptic historical observations first. RRFS, HRRR
sub-hourly, and ensemble products are explicit Phase 2+ extensions.

## Where things live
- **`./ROADMAP.md`** — six-phase implementation plan. The strategic
  north star. New NWP code goes in a dedicated `brc_tools/nwp/`
  subpackage (not `brc_tools/download/`).
- **`./HRRR-BRANCH-NOTES.md`** — snapshot of an earlier exploration of
  unmerged HRRR branches, with a recommended read order. Use this to
  mine reusable code from `feat/hrrr-road-poc-minimal` without checking
  the branch out.

## Anchors
- GitHub issue: `#10` (Prioritize HRRR/RRFS import-to-BasinWx)
- Source branch with prototypes (not on main):
  `feat/hrrr-road-poc-minimal`
- Target package (new): `brc_tools/nwp/`
- Push contract: `brc_tools/download/push_data.send_json_to_server`
  → `POST {server}/api/upload/{data_type}` (see `../../CLAUDE.md`).
- Companion repo: `ubair-website` (BasinWX receiver).

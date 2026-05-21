# NWP / HRRR / RRFS work

Active work area for the HRRR/RRFS data ingest → BasinWX pipeline.

- **`./ROADMAP.md`** — phase tracker, current status, branch survey
  archive. Single source of truth for NWP strategy.

## Quick anchors
- GitHub issue: `#10` (HRRR/RRFS → BasinWx).
- Code: `brc_tools/nwp/` (NWPSource, derived, alignment, case_study, basinwx).
- Push contract: `brc_tools.download.push_data.send_json_to_server`
  (see `../../CLAUDE.md`).
- Operational deployment: `../CHPC-REFERENCE.md` → "HRRR surface layers".
- Companion repo: `ubair-website` (BasinWX receiver).

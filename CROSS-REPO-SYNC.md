# Cross-Repository Synchronization Protocol

**Purpose:** Prevent drift between code, documentation, and technical report across 4 repositories.

## The 4 Repositories

1. **clyfar** (`/Users/johnlawson/PycharmProjects/clyfar`)
   - Python ozone prediction model
   - Source of truth for: Categories, thresholds, inference method, membership functions

2. **brc-tools** (`/Users/johnlawson/PycharmProjects/brc-tools`)
   - Shared utilities for data download/upload
   - Source of truth for: API protocols, data transfer methods

3. **ubair-website** (`/Users/johnlawson/WebstormProjects/ubair-website`)
   - Node.js website for visualization
   - Source of truth for: Data schemas, API endpoints, display logic

4. **preprint-clyfar-v0p9** (`/Users/johnlawson/Documents/GitHub/preprint-clyfar-v0p9`)
   - LaTeX technical manuscript
   - Source of truth for: Scientific methodology description

## Source of Truth Hierarchy

When conflicts arise, resolve in this order:

1. **Python code** (clyfar/fis/v0p9.py) - What actually runs
2. **Tech report** (preprint LaTeX) - Scientific methodology
3. **API schema** (ubair-website/DATA_MANIFEST.json) - Data contracts
4. **Markdown docs** - Implementation guides

**Rule:** Code is truth. If tech report contradicts code, either fix code or update report.

## Synchronization Triggers

Update all 4 repos when ANY of these change:

### Critical Changes (update within same session)
- Ozone category names or thresholds
- Input variable thresholds (snow, wind, MSLP, solar radiation)
- Fuzzy inference methodology
- Data schema for forecasts (JSON structure)
- API endpoint changes

### Important Changes (update within 1 week)
- New data products added
- Schedule changes (4× daily, etc.)
- GEFS dependency updates
- Environment variable names

### Minor Changes (update as convenient)
- Code refactoring (no behavior change)
- Documentation formatting
- Example updates

## Required Files to Sync

These files must stay aligned across repos:

| File | Location | What to sync |
|------|----------|-------------|
| **CONTRADICTIONS-REPORT.md** | All 4 repos | Findings from code vs report review |
| **CROSS-REPO-SYNC.md** | All 4 repos | This protocol |
| **AGENT-INDEX.md** | clyfar, brc-tools, ubair-website | Current status, key context |
| **.env.example** | clyfar, brc-tools | Required environment variables |

## Workflow for Making Changes

### Scenario 1: Changing Ozone Thresholds

```bash
# 1. Update Python code first (source of truth)
cd ~/PycharmProjects/clyfar
# Edit fis/v0p9.py lines 78-117 (category definitions)

# 2. Update tech report
cd ~/Documents/GitHub/preprint-clyfar-v0p9
# Edit manuscript-claude-draft.tex lines 635-638, 739-742

# 3. Update website schema
cd ~/WebstormProjects/ubair-website
# Edit DATA_MANIFEST.json (forecasts.categories)

# 4. Run contradiction check
# Re-run Phase 1 review or manually verify alignment

# 5. Update CONTRADICTIONS-REPORT.md in all 4 repos
# Clear resolved contradictions, note new matches
```

### Scenario 2: Adding New Data Product

```bash
# 1. Implement in clyfar first
cd ~/PycharmProjects/clyfar
# Add export function to export/to_basinwx.py
# Test with test_integration.py

# 2. Update website to receive/display
cd ~/WebstormProjects/ubair-website
# Add schema to DATA_MANIFEST.json
# Update API validation
# Add display logic to frontend

# 3. Document in tech report
cd ~/Documents/GitHub/preprint-clyfar-v0p9
# Add methodology section if needed

# 4. Update AGENT-INDEX.md in all repos
# Note new data product, schema, endpoints
```

### Scenario 3: Schedule Changes

```bash
# 1. Update cron templates
cd ~/WebstormProjects/ubair-website
# Edit chpc-deployment/cron_templates/

# 2. Update all documentation mentioning schedule
# Search all 4 repos for "twice daily", "4 times daily", etc.
# Update CHPC-IMPLEMENTATION.md, INTEGRATION_GUIDE.md

# 3. Update AGENT-INDEX.md
# Note new schedule in all 3 code repos
```

## AI Agent Instructions

### When an AI agent (Claude, Codex, Cursor, etc.) makes changes:

1. **Check current state** - Read AGENT-INDEX.md first
2. **Identify scope** - Will this affect other repos?
3. **Update related files** - Don't leave partial updates
4. **Flag for review** - Add TODO comment if uncertain about cross-repo impact
5. **Update AGENT-INDEX.md** - Record what you changed

### Multi-Agent Coordination

If multiple AI agents are working simultaneously:

- **Clyfar agent**: Focus on model logic, mention if thresholds change
- **Website agent**: Focus on display/API, mention if schema changes
- **Docs agent**: Focus on markdown, check code first before updating
- **Report agent**: Focus on LaTeX, verify against Python code

**Communication:** Use git commit messages to signal cross-repo changes:
```
feat(thresholds): Update elevated category to 55-65 ppb [SYNC-NEEDED]

Affects:
- clyfar: fis/v0p9.py
- preprint: manuscript-claude-draft.tex
- website: DATA_MANIFEST.json
```

## Verification Checklist

Before considering a change complete:

- [ ] Python code updated (if applicable)
- [ ] Tech report updated (if methodology changed)
- [ ] Website schema updated (if data structure changed)
- [ ] All 4 CONTRADICTIONS-REPORT.md files synced
- [ ] AGENT-INDEX.md updated in affected repos
- [ ] Tests pass in clyfar (test_integration.py)
- [ ] Git commit messages include [SYNC-NEEDED] tag if applicable

## Emergency: Repos Out of Sync

If you discover contradictions:

1. **Stop new development** - Don't compound the problem
2. **Create tracking issue** - Document what's mismatched
3. **Identify source of truth** - Which version is correct?
4. **Update in hierarchy order** - Code → Report → Schema → Docs
5. **Re-run Phase 1 review** - Verify contradictions resolved
6. **Update CONTRADICTIONS-REPORT.md** - Mark as resolved with date

## Tools for Sync Verification

```bash
# Search for specific threshold across all repos
cd ~ && grep -r "elevated.*75.*90" \
  WebstormProjects/ubair-website \
  PycharmProjects/clyfar \
  PycharmProjects/brc-tools \
  Documents/GitHub/preprint-clyfar-v0p9

# Compare category definitions
cd ~/PycharmProjects/clyfar && grep -A5 "ozone_cats" fis/v0p9.py
cd ~/Documents/GitHub/preprint-clyfar-v0p9 && grep -A5 "background.*moderate.*elevated" *.tex

# Check environment variable consistency
cd ~ && grep -r "DATA_UPLOAD_API_KEY" \
  WebstormProjects/ubair-website \
  PycharmProjects/clyfar \
  PycharmProjects/brc-tools
```

## Version Control Strategy

- **clyfar**: Tag releases when deploying to CHPC (e.g., v0.9.5)
- **brc-tools**: Tag when API protocol changes (e.g., v0.1.1)
- **ubair-website**: Tag when merging dev → ops (e.g., v2.1.0)
- **preprint**: Tag when submitting to journal (e.g., v1.0-submission)

**Rule:** Cross-repo version compatibility documented in each repo's README.

## Contact & Questions

If uncertain about cross-repo impact:
1. Check CONTRADICTIONS-REPORT.md for known issues
2. Review AGENT-INDEX.md for current state
3. Ask in team chat before committing changes that span repos
4. When in doubt, create a git branch for testing sync

---

**Last Updated:** 2025-11-23
**Next Review:** After resolving MSLP unit mismatch

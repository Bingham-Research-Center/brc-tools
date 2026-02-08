# Remove Legacy Documentation and Redundant Files

## 🎯 Purpose
Clean up repository by removing outdated, redundant, and low-value documentation files that are no longer needed after recent infrastructure improvements.

## 🗑️ Files Deleted (6 total, 21,749 lines removed)

### Root Level Cleanup
- **CLAUDE-INDEX.md** (97 lines) - Redundant navigation now integrated in main CLAUDE.md
- **CLAUDE-CODE-WORKFLOW.md** (279 lines) - Overly complex workflow replaced by streamlined team approach
- **WISHLIST-TASKS.md** (119 lines) - Outdated task list superseded by PR-based development workflow

### Reference Directory Cleanup
- **reference/FLIGHTAWARE-SPEC.md** (1MB+) - Massive API specification dump not actively used
- **reference/BRC-TOOLS-SETUP.md** (6KB) - Manual setup procedures replaced by automated `setup_config.py`
- **reference/PYTHON-DEVELOPER-TODO.md** (4KB) - Outdated development tasks completed or obsolete

## ✅ What Remains (High Value)
- **CLAUDE.md** - Core project context and conventions
- **README.md** - Clean project overview and entry point
- **docs/** - Essential technical documentation (pipeline, testing, environment)
- **reference/FLIGHTAWARE-API.md** - Concise, actively used API reference

## 📊 Impact
- **Repository size reduced** by over 1MB of unused documentation
- **Simplified navigation** - no more redundant or conflicting documentation
- **Cleaner onboarding** - clear path through essential files only
- **Maintenance reduction** - fewer files to keep updated

## 🔄 Rationale
Recent infrastructure work (setup automation, comprehensive testing, team guides) has made these legacy files obsolete. This cleanup:
- Eliminates confusion from multiple overlapping guides
- Focuses attention on current, accurate documentation
- Reduces maintenance burden for future updates
- Prepares repository for streamlined team collaboration

## 🧪 Validation
- All deleted files are redundant to existing functionality
- No active code references or dependencies removed
- Essential project information preserved in remaining files
- Team workflow unaffected (improvements in other PRs)

## 📝 Breaking Changes
None - this is purely documentation cleanup with no functional impact.

---

This cleanup complements the team collaboration infrastructure in PR #2 and prepares the repository for streamlined development workflow.
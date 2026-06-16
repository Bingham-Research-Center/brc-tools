# Handoff to brc-wrf — cross-repo hygiene & caretaker pass

From a brc-tools session, 2026-06-16. Keep the brc-tools↔brc-wrf wiring rock-solid, make
`AGENTS.md` self-maintaining, and trim BRC-added cruft. **Never touch the WRF source tree**
(arch/, chem/, dyn_em/, frame/, phys/, Registry, configure, compile, Makefile, …).

## 0. Trustable context
- Wiring audited 2026-06-16: every `../brc-tools`↔`../brc-wrf` doc link resolves, both
  directions, zero broken. Don't re-fix — keep it true (§2 caretaker check).
- brc-tools shipped a staging-hygiene batch (manifest **schema v2** + token preflight); see
  `../brc-tools/docs/WRF-INPUT-STAGING.md` §4. It does **not** change the proven NAM-only
  path, the scratch layout, or the contract sidecar — so the WRF run side is unchanged.
  brc-wrf consumes the **contract sidecar**, not `staged_files` (confirmed in
  `brc-cases/wrf_case.py`), so the additive schema bump is a no-op for you.

## 1. Wiring verification (rock-solid) — do first, ~2 min
From brc-wrf root:

    grep -rno "\.\./brc-tools[^ )\"\`]*" AGENTS.md README.md brc-docs doc brc-cases \
      | sed 's/^[^:]*:[0-9]*://' | sort -u \
      | while read p; do [ -e "$p" ] && echo "OK  $p" || echo "BROKEN $p"; done

Expect all OK. If BROKEN: the brc-tools file moved — fix the reference here (don't invent a
path). Optional content note in AGENTS.md "Current Run Truth": "manifest schema v2 (additive);
brc-wrf reads the contract sidecar, not staged_files."

## 2. AGENTS caretaker — make doc-currency a habit
Add a short block to `AGENTS.md` (keep AGENTS.md the short routing file; detail stays in
`doc/BRC_WRF_MICROTASK_HANDOFF.md`):

    ## Doc Currency (caretaker)
    When any of these change, update the named file IN THE SAME COMMIT:
    - brc-tools contract/manifest fields or staging flags -> "Current Run Truth" here.
    - A proof state flips (e.g. GEFS+NAM two-stream proven) -> "Current Run Truth" here +
      brc-docs/BRC-WRF-STATE-PLAYBOOK.md + brc-docs/BRC-WRF-FIRST-CASE.md.
    - Any ../brc-tools path renamed -> run the §1 link-check and fix references.
    README.md = humans; AGENTS.md = agents. Don't duplicate run logic into README.md.

## 3. Parse down (BRC-added files only — WRF source is off-limits)
- `TASK-PRIORITIES-JUNE13.md` (root, dated) — superseded by `doc/BRC_WRF_MICROTASK_HANDOFF.md`.
  Fold any still-live items into the board, then delete.
- `doc/BRC_WRF_HANDOFF.md` overlaps the microtask board — reduce to a 3-line pointer or delete.
- `brc-docs/` (7 files) — audited current; light plain-language pass only, no deletions.
- `README.md` (human-aimed, ~99 lines) — confirm it carries a useful **human** resource list
  (WRF registration/user guide, CHPC + WRF quickstart in `brc-knowledge`, the BRC docs index)
  and routes humans, not agents. Keep AI routing in AGENTS.md.

## 4. brc-tools side (done this session)
- Doc-map drift + stale merge-status fixed; `CROSS-REPO-SYNC.md` now notes this seam.
- Both root scratch notes deleted.
- Staging-hygiene batch pushed to `origin/feat/wrf-input-staging`; PR open against `main`
  (find it via `gh pr list --repo Bingham-Research-Center/brc-tools`).
- Matching item: microtask **#32** (brc-wrf docs reference the brc-tools staging doc + scratch
  layout) — close it as part of §1–§3.

## Outstanding / caveats / intentionally left
- **Outstanding test:** brc-tools `--preflight` is offline-tested only; the live S3 list-URL
  format is unverified — first live run is the real test.
- **Caveat:** manifest is schema v2 (additive); if brc-wrf ever parses the manifest directly,
  treat extra fields as expected (you currently read the contract, so no action).
- **Caveat:** local brc-tools `main` is stale behind `origin/main` (#22) — harmless, FYI.
- **Intentionally left:** WRF source tree untouched; GEFS+NAM two-stream still unproven
  (optional); brc-wrf cleanup (§2–§3) is handed to you, not done from the brc-tools session.

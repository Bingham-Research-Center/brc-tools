# Agent Instructions for `brc-tools`

## Start here

- Read `README.md`, `CLAUDE-CODE-WORKFLOW.md`, `CLAUDE-INDEX.md`, `CLAUDE.md`, and `WISHLIST-TASKS.md` first.
- For deployment and runtime context, use `docs/CHPC-REFERENCE.md` and `docs/PIPELINE-ARCHITECTURE.md`.
- Treat issue comments or review comments that explicitly address `@copilot` as part of the task instructions.

## Repo boundaries

- `brc-tools` is the shared Python/data-ingest side of the BasinWx workflow.
- Put shared helper layers, new data sources, metadata mappings, and upload helpers here.
- Do **not** put `clyfar`-specific workflow code or `ubair-website` UI/backend code here unless the task explicitly requires cross-repo coordination docs.

## Research and reference-gathering tasks

- Do not ignore explicit requests to gather external references or specs.
- Prefer authoritative sources first: NOAA/NCEP, Herbie docs, Synoptic docs, vendor API docs, and repo-local specs.
- Save durable gathered material under `resources/` or a task-specific subfolder there.
- In saved markdown, include source URLs and a brief note explaining why each source matters.
- Ask clarifying questions if the target model, product, variable, or output format is ambiguous.

## Working conventions

- Use American English in code and durable repo documentation.
- Prefer Polars over Pandas for new dataframe work.
- Use UTC internally and convert only for display.
- Keep keys, units, dimensions, file/product naming, and BasinWx-facing payload shapes explicit.
- Do not treat mapping docs as optional prose; they are part of the interface agents should follow.

## Validation

- If the toolchain is available, run:
  - `python -m ruff check .`
  - `python -m mypy brc_tools/`
  - `python -m pytest tests/`
- If those tools are missing, install the needed Python tooling before skipping validation.

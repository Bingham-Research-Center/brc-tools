# Environment Setup Guide

## For Team Members New to Python Environments

### What is a Virtual Environment?
A virtual environment is like a clean workspace for each project. It keeps this project's packages separate from other Python projects on your computer.

## Quick Start (Recommended)

### 1. Using venv (Built into Python)
```bash
# Navigate to project folder
cd brc-tools

# Create virtual environment
python -m venv venv

# Activate it
# On Mac/Linux:
source venv/bin/activate
# On Windows:
venv\Scripts\activate

# Install the package + dependencies (declared in pyproject.toml)
pip install -e ".[dev]"
```

### 2. Using Environment Variables (.env file)
```bash
# Copy the template
cp .env.example .env

# Edit .env with your API keys
# Never commit this file to git!
```

## For Conda Users

If you prefer conda/miniforge, that's fine! Here's how:

**Recommended (conda-forge + mamba/miniforge):** use the curated `environment.yml` at the
repo root — it mirrors `pyproject.toml` and tracks a current Herbie release:

```bash
mamba env create -f environment.yml   # creates env "brc-tools-2026"
conda activate brc-tools-2026
pip install -e . --no-deps            # install brc_tools itself (deps already solved)
pytest tests/                          # 2026-11-20: 1052 passed, 11 skipped (herbie 2026.3.0 and 2026.10.0)
```

On CHPC that `pip install -e .` needs two extra flags — `--no-build-isolation` (pypi.org is
unreachable from compute/login sandboxes, so pip cannot fetch a build backend) and `--no-user`
(otherwise pip falls back to a read-only `~/.local/lib`):

```bash
pip install -e . --no-deps --no-build-isolation --no-user
```

Then confirm the install **from outside the checkout** — running `python -c "import brc_tools"`
while sitting in the repo passes on cwd alone and hides a missing install, which later surfaces as
an `ImportError` in `brc-wrf` or `clyfar` (both import `brc_tools` from their own trees):

```bash
cd /tmp && python -c "import brc_tools, brc_tools.visualize.grid, brc_tools.download.push_data"
```

**Two envs exist side by side on CHPC** (state 2026-11-20):

| Env | Herbie | SynopticPy | polars / numpy / pandas | Runs |
|---|---|---|---|---|
| `brc-tools-2026` | 2026.3.0 | 2026.6.0 | 1.42 / 2.5.0 / 3.0.3 | the four HRRR crons, ub-wx, brc-wrf, the pelican2013 manuscript pin. **Do not upgrade in place.** |
| `brc-tools-2026-11` | 2026.10.0 | 2026.10.0 | 2.1.0 / 2.5.5 / 3.1.1 | the HRRR surface-layers cron, as a pilot since 2026-11-21. Built from `environment.yml` with the two Blaylock packages at their current releases; `brc_tools` installed editable. |

`brc-tools-2026-11` is the only env that can fetch RRFS (the operational bucket needs
Herbie ≥ 2026.9.2). `pytest tests/` there: **1052 passed, 11 skipped** on 2026-11-20, the
same as `brc-tools-2026`, so the suite holds on polars 2. A live Synoptic pull through
`ObsSource` works on it (KVEL, 2026-11-21), and its surface-layers payload is identical to
`brc-tools-2026`'s for the same HRRR run apart from the timestamp. **Activate it** (`conda activate`), do not call its `bin/python` bare:
conda-forge's pyproj finds its database through `PROJ_DATA`, which only activation sets,
and 25 tests fail with `proj_create: no database context specified` without it. The cron
wrappers activate already. Moving a cron onto it is an ops decision:
`docs/BRC-DATA-OPS-HANDOFF.md`.

Prefer a fresh, dedicated env over reusing a shared/accreted one. The canonical list of
dependencies is **`pyproject.toml`** (`[project.dependencies]`); `environment.yml` is the
conda mirror.

### Why Both pip and conda?
- **pip**: Has all Python packages, always up-to-date
- **conda**: Better for complex scientific packages (cartopy, GDAL)
- You can use both in the same environment!

## Understanding .env Files

The `.env` file stores sensitive information like API keys:

```bash
# .env.example shows what you need:
SYNOPTIC_TOKEN=your_token_here
DATA_UPLOAD_API_KEY=your_32char_hex_key_here

# The actual .env file is gitignored (never uploaded)
# Each team member has their own .env locally
```

### How Python Reads .env
```python
from dotenv import load_dotenv
import os

load_dotenv()  # This loads your .env file

api_key = os.getenv('SYNOPTIC_TOKEN')
```

## What are ruff and mypy?

### ruff
- **What**: A fast Python linter (checks for errors and style)
- **Why**: Catches bugs before you run code
- **Usage**: 
  ```bash
  ruff check .  # Check all files
  ruff check --fix .  # Auto-fix issues
  ```

### mypy
- **What**: Static type checker
- **Why**: Catches type-related bugs
- **Usage**:
  ```bash
  mypy brc_tools/  # Check types
  ```
- **Example** it would catch:
  ```python
  def add(a: int, b: int) -> int:
      return a + b
  
  result = add("hello", "world")  # mypy warns: expecting int, got str
  ```

## Troubleshooting

### "Command not found: python"
Try `python3` instead of `python`

### "No module named pip"
```bash
python -m ensurepip --upgrade
```

### Conda and venv conflict
Don't activate both! Pick one:
```bash
# If using venv, deactivate conda first
conda deactivate
source venv/bin/activate
```

### Package installation fails
Some packages need system libraries:
```bash
# Mac (using Homebrew)
brew install proj geos

# Ubuntu/Debian
sudo apt-get install libproj-dev libgeos-dev

# Then retry pip install
```

## Best Practices

1. **Always activate your environment** before working
2. **Keep `pyproject.toml` (and `environment.yml`) updated** when adding packages
3. **Never commit .env files** (check .gitignore)
4. **Document weird dependencies** in comments
5. **Test in a fresh environment** occasionally

## For VS Code Users

1. Open Command Palette (Cmd/Ctrl + Shift + P)
2. Type "Python: Select Interpreter"
3. Choose the venv you created
4. VS Code will auto-activate it in terminals

## For PyCharm Users

1. Settings → Project → Python Interpreter
2. Add Interpreter → Existing Environment
3. Browse to `venv/bin/python` (or `venv\Scripts\python.exe`)
4. PyCharm handles activation automatically
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

# Install packages
pip install -r requirements.txt
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

```bash
# Create conda environment
conda create -n brc-tools python=3.11

# Activate it
conda activate brc-tools

# Install pip packages
pip install -r requirements.txt

# Some packages might work better with conda:
conda install -c conda-forge cartopy
```

### Why Both pip and conda?
- **pip**: Has all Python packages, always up-to-date
- **conda**: Better for complex scientific packages (cartopy, GDAL)
- You can use both in the same environment!

## Understanding .env Files

The `.env` file stores sensitive information like API keys:

```bash
# .env.example shows what you need:
SYNOPTIC_API_KEY=your_key_here
BRC_API_KEY=your_key_here

# The actual .env file is gitignored (never uploaded)
# Each team member has their own .env locally
```

### How Python Reads .env
```python
from dotenv import load_dotenv
import os

load_dotenv()  # This loads your .env file

api_key = os.getenv('SYNOPTIC_API_KEY')
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
2. **Keep requirements.txt updated** when adding packages
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
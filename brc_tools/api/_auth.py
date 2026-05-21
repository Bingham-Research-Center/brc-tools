"""Shared API-key loader for `brc_tools.api.*` clients.

Precedence: environment variable first; optional file under
`~/.config/{config_subpath}` as a fallback. The file contains just the
key on its first line.
"""

import os
from pathlib import Path


def load_api_key(env_var: str, config_subpath: str | None = None) -> str:
    """Return an API key, raising `RuntimeError` if not found.

    Mirrors the env-then-config pattern already used by
    `brc_tools.download.push_data.load_config`.
    """
    value = os.environ.get(env_var)
    if value:
        return value.strip()

    if config_subpath:
        path = Path.home() / ".config" / config_subpath
        if path.exists():
            line = path.read_text().splitlines()[0].strip()
            if line:
                return line

    where = f"{env_var} env var"
    if config_subpath:
        where += f" or ~/.config/{config_subpath}"
    raise RuntimeError(f"Missing API key: set {where}.")

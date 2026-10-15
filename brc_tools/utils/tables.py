"""Small CSV tables of dict rows: the ``data/`` files an experiment keeps in git.

Floats are written to ``digits`` significant figures and read back as floats; every
other value round-trips as text.  Keys are the union of the rows' keys in first-seen
order, so rows may differ in shape.
"""
from __future__ import annotations

import csv
from pathlib import Path


def write_csv(path: str | Path, rows: list[dict], *, digits: int = 6) -> Path:
    path = Path(path)
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys, restval="")
        w.writeheader()
        for r in rows:
            w.writerow({k: (f"{v:.{digits}g}" if isinstance(v, float) else v) for k, v in r.items()})
    return path


def read_csv(path: str | Path) -> list[dict]:
    with open(path) as fh:
        return [{k: _num(v) for k, v in r.items()} for r in csv.DictReader(fh)]


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return v

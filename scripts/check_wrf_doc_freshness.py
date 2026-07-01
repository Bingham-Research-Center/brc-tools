#!/usr/bin/env python3
"""Fail if WRF-lane docs revive stale Pelican handoff wording."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

TOP_LEVEL_TARGETS = [
    "CLAUDE.md",
    "WISHLIST-TASKS.md",
]

NEEDLES = {
    "BRC-TOOLS-LINK-HANDOFF": (
        "deleted brc-wrf handoff; use "
        "BRC-WRF-PELICAN-NWP-HOTSWAP-HANDOFF.md"
    ),
    "awaiting brc-wrf WPS": "GFS already completed WPS/real/wrf in brc-wrf",
    "brc-wrf consumes the GFS contract next": (
        "GFS contract has already been consumed"
    ),
    "The ball is in `brc-wrf`'s court": "GFS WRF-side run is complete",
    "WPS/run is brc-wrf's": "GFS WRF-side run is complete",
    "WPS/run is `brc-wrf`'s to prove": "GFS WRF-side run is complete",
}

LINE_RULES = [
    (
        ("RAP forcing", "DTN stage"),
        "RAP was already staged; unchanged RAP-only is blocked before real.exe",
    ),
]


def main() -> int:
    findings: list[str] = []
    paths = [ROOT / rel for rel in TOP_LEVEL_TARGETS]
    paths.extend(sorted((ROOT / "docs").rglob("*.md")))

    for path in paths:
        rel = path.relative_to(ROOT)
        if not path.exists():
            findings.append(f"{rel}: missing target")
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for needle, reason in NEEDLES.items():
                if needle in line:
                    findings.append(f"{rel}:{lineno}: stale '{needle}' ({reason})")
            for needles, reason in LINE_RULES:
                if all(needle in line for needle in needles):
                    joined = " + ".join(needles)
                    findings.append(f"{rel}:{lineno}: stale '{joined}' ({reason})")

    if findings:
        print("WRF doc freshness check failed:")
        for finding in findings:
            print(f"  {finding}")
        return 1

    print("WRF doc freshness check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

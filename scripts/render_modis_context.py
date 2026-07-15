#!/usr/bin/env python3
"""CLI wrapper for :mod:`brc_tools.satellite.modis`.

See ``docs/MODIS-CONTEXT-RENDERER.md`` for the online and staged-cache workflows.
"""

from brc_tools.satellite.modis import main

if __name__ == "__main__":
    raise SystemExit(main())

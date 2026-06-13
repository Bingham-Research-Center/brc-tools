#!/usr/bin/env python3
"""Stage WPS/WRF-ready GRIB inputs (GEFSv12 Reforecast) to scratch.

Thin CLI wrapper around ``brc_tools.nwp.wrf_staging.main``. Example::

    python scripts/stage_wrf_inputs.py \
        --case jan2013_basin_gefs --init-time "2013-01-31 00Z" \
        --members 0 --fxx-window 12,48

See ``brc_tools/nwp/wrf_staging.py`` for the full option set and the WRF handoff.
"""

from brc_tools.nwp.wrf_staging import main

if __name__ == "__main__":
    raise SystemExit(main())

"""Inventory Synoptic API streamflow/gauge stations within 50 km of Vernal, UT.

Vernal centre: 40.4555 N, -109.5287 W. Radius 31.07 mi (~50 km).

Synoptic stream-related variable names (from /variables): stream_flow (ft3/s),
gage_height (ft), flow_rate, water_temp.
"""
from __future__ import annotations

import polars as pl
from synoptic.services import Metadata, Networks

VERNAL_LAT = 40.4555
VERNAL_LON = -109.5287
RADIUS_MI = 31.07

STREAM_VARS = ["stream_flow", "gage_height", "flow_rate", "water_temp"]


def stations_for(var: str) -> pl.DataFrame:
    try:
        return Metadata(
            radius=[VERNAL_LAT, VERNAL_LON, RADIUS_MI],
            vars=var,
        ).df()
    except Exception as exc:
        print(f"  [{var}] -> {exc}".splitlines()[0])
        return pl.DataFrame()


def main() -> None:
    nets = Networks().df().select(["mnet_id", "shortname", "longname"])

    print(f"Synoptic inventory within {RADIUS_MI:.1f} mi (~50 km) of Vernal UT "
          f"({VERNAL_LAT}, {VERNAL_LON})\n")

    for var in STREAM_VARS:
        df = stations_for(var)
        n = len(df)
        print(f"\n=== {var}: {n} station(s) ===")
        if n == 0 or df.is_empty():
            continue
        show = df.join(nets, on="mnet_id", how="left")
        cols = [c for c in ["stid", "name", "latitude", "longitude", "elevation",
                            "shortname", "longname"] if c in show.columns]
        with pl.Config(tbl_rows=-1, fmt_str_lengths=50, tbl_width_chars=200):
            print(show.select(cols))

    print("\nNote: USGS HYDRO (mnet_id=203) is the Synoptic network that carries "
          "most USGS NWIS stream gauges. This token does not have access to it "
          "(restricted network). To enable: request access from Synoptic "
          "(support@synopticdata.com) or pull gauge data directly from USGS "
          "NWIS (https://waterservices.usgs.gov).")


if __name__ == "__main__":
    main()

"""Observation data access via SynopticPy, sharing the NWP alias namespace."""

from brc_tools.obs.scanner import detect_foehn, detect_wind_ramp, scan_events
from brc_tools.obs.source import ObsSource

__all__ = [
    "ObsSource",
    "detect_foehn",
    "detect_wind_ramp",
    "scan_events",
]

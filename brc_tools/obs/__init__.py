"""Observation access. Research/archive imports do not load the NWP stack."""

from importlib import import_module

__all__ = ["ObsSource", "detect_foehn", "detect_wind_ramp", "scan_events"]


def __getattr__(name):
    if name not in __all__:
        raise AttributeError(name)
    module = "source" if name == "ObsSource" else "scanner"
    value = getattr(import_module(f"{__name__}.{module}"), name)
    globals()[name] = value
    return value

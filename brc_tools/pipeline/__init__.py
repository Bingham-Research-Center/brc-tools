"""BRC Tools Pipeline Package

This package implements the fetch→process→push data pipeline architecture.

Modules:
    base: Base pipeline class and interfaces
    observations: Synoptic observation data pipeline
    models: NWP model data pipeline
    aviation: FlightAware aviation data pipeline
"""

from .base import Pipeline

__all__ = ['Pipeline']
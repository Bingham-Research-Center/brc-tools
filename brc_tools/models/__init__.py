"""BRC Tools Models Package

This package contains modules for accessing and processing numerical weather prediction (NWP) data.

Modules:
    aqm: Air Quality Model data access and processing
    hrrr: High Resolution Rapid Refresh model data
    rrfs: Rapid Refresh Forecast System data  
    base: Base classes for all model interfaces
"""

from .base import BaseModel

__all__ = ['BaseModel']
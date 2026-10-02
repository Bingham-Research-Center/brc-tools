"""Idealised theory of nocturnal cold-air drainage, to be read against terrain geometry.

``brc_tools.terrain`` says what the ground is; this subpackage says what a layer of cold
air would do on it under stated assumptions.  Everything here is arithmetic on those
assumptions -- none of it is a measurement, and each function's docstring names the
closure it uses so a result can be traced to it.

Modules
-------
``cooling``     clear-night surface energy balance: how fast a surface draws heat from the air
``slopeflow``   Prandtl's slope-flow solution, bulk drainage layers, Froude numbers, pool tilt
``hydraulics``  a cold layer leaving a basin through a throat: critical, drowned and
                friction-limited capacity for a section given as area against stage
``cascade``     basins joined by throats, filling and spilling through a night
``sinks``       reader for the lookups.toml ``[sinks.*]`` table (the basins and their exits)

numpy only: the subpackage imports in any environment, including one without the raster
stack or Herbie.
"""
from __future__ import annotations

__all__ = ["cooling", "slopeflow", "hydraulics", "cascade", "sinks"]

G = 9.81            # m s-2
CP = 1004.0         # J kg-1 K-1
R_D = 287.0         # J kg-1 K-1
SIGMA = 5.670374419e-8
OMEGA = 7.2921e-5   # s-1

"""Idealised stratified flow over terrain, to be read against real terrain geometry.

``brc_tools.drainage`` says what a layer of cold air does when it drains *off* terrain;
this subpackage says what a stratified wind does when it blows *over* it, and what a cold
pool under that wind does in return.  Same contract as ``drainage``: every function is
arithmetic on a named closure, the constants are arguments, nothing is a measurement.

Modules
-------
``mountainwave``  linear Boussinesq mountain waves: 3-D over a DEM (Smith 1980) and 2-D
                  along a transect through a layered atmosphere with inversions (Scorer)
``layer``         one-layer reduced-gravity hydraulics over an obstacle (Long 1954;
                  Houghton & Kasahara 1968; Baines 1995): regimes, upstream bores, lee jets
``leewaves``      trapped lee waves: two-layer Scorer and inversion-capped (Vosper 2004)
                  dispersion relations, trapping criteria, resonant wavelengths
``seiche``        free oscillations of a cold pool: Merian's formula and the eigenmodes of
                  the reduced-gravity shallow-water operator on a pool-depth map
``pool``          a cold pool under a wind: interface displacement by an imposed pressure,
                  the soft-boundary interaction number, Wedderburn number, Rossby radius

numpy everywhere; ``seiche.basin_modes`` needs scipy.
"""
from __future__ import annotations

__all__ = ["mountainwave", "layer", "leewaves", "seiche", "pool"]

G = 9.81            # m s-2
THETA0 = 285.0      # K, reference potential temperature for reduced gravity
RHO0 = 1.0          # kg m-3, Basin-floor air density to the nearest 10 % (~1.05 at 840 hPa, 270 K)

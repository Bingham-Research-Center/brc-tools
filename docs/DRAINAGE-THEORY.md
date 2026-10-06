# Idealised drainage theory (`brc_tools.drainage`)

`brc_tools.terrain` says what the ground is. This subpackage says what a layer of cold
air would do on it **under stated assumptions**. Nothing here is a measurement: every
function is arithmetic on a closure, the closure is named in its docstring, and the
constants are arguments because they are the assumptions. The use is to *test an idea
before a model run* -- which canyons a grid plugs, whether a throat could pass what its
basin makes, how long a pool takes to fill -- and to predict what a run should show, so
the run can falsify it. numpy only; it imports in any environment.

| Module | What it answers | Closure |
|---|---|---|
| `cooling` | how fast a surface draws heat from the air on a clear night | one-layer surface energy balance |
| `slopeflow` | how thin and fast a slope current is; where it is critical; how a wind aloft tilts a pool | Prandtl (1942); layer-mean drag balance; geostrophy |
| `hydraulics` | how much a pool can push through a throat | reduced-gravity (1.5-layer) hydraulics |
| `cascade` | how a chain of basins fills and spills through a night | reservoirs with volume and heat deficit |
| `sinks` | which basins, exits and throats (reads `lookups.toml [sinks.*]`) | -- |

## 1. Cooling (`cooling.solve_surface`)

Per cell, per hour, for the surface temperature `Ts`:

    eps * sigma * Ts^4 = eps * L_down + H + G
    L_down = SVF * eps_clear(Ta, ea) * sigma * Ta^4 + (1 - SVF) * sigma * Ta^4
    H      = rho cp C_HN f(Ri_b) U (Ta - Ts),   f = 1 / (1 + c Ri_b)
    G      = k (T_base - Ts) / d

The surface is grey: it absorbs `eps` of the downwelling longwave as it emits `eps` of
a black body (Kirchhoff) and reflects the rest, so the returned upwelling longwave is
`L_up = eps sigma Ts^4 + (1 - eps) L_down` and the net loss `L_up - L_down` is `H + G`.
(Absorbing all of `L_down` while emitting with `eps`, as the first version did, kept
the surface 0.6-0.9 K too warm and `H` too small: by 4 % over snow, `eps = 0.98`, and
13-23 % over soil, `eps = 0.95`, on 258-270 K nights.)

Clear-sky emissivity from Prata (1996), saturation vapour pressure from Bolton (1980),
stable damping in the form of Louis (1979), sky-view factor from the terrain
(`terrain.skyview`, Dozier & Frew 1990). `H` is positive where the **air** loses heat to
the surface: that is the term a drainage flow runs on.

The two constants that dominate -- the exchange wind `U` and the neutral transfer
coefficient `C_HN` -- stand for how strongly a stable surface layer stays coupled to the
ground, and no default is defensible to better than a factor of two. `wind_ms=` takes a
per-cell wind (an analysed 10 m wind) in place of the single `params.u_ms`. Run a low,
central and high set; report the bracket.

`open_water_flux` is the companion for a lake that has not frozen: a bulk (neutral)
estimate of the sensible and latent heat it puts *into* the air. Over water much warmer
than the air the layer is unstable and the true flux is larger, so it is a floor.

## 2. Slope flows and the pool (`slopeflow`)

**Prandtl's solution.** On a uniformly cooled slope in a stratified atmosphere with
constant diffusivities the wind maximum sits at `(pi/4) l`, `l = (4 Km Kh / (N^2 sin^2
alpha))^(1/4)`: about 6 m above a 10 degree slope and 11 m above a 3 degree one for
`K = 0.1 m2 s-1`, `N = 0.02 s-1`. The jet speed does not depend on the slope. This is
what decides whether a model's lowest level is inside the jet or above it.

**A bulk drainage layer.** `equilibrium_speed` balances along-slope buoyancy against bed
drag and interfacial entrainment, `U = sqrt(g' h sin(alpha) / (cd + E))` (the steady
layer-averaged balance, after Manins & Sawford 1979 with storage and advection dropped).
Its Froude number, `sqrt(tan(alpha) / (cd + E))`, depends only on the slope and the drag,
so a thalweg can be mapped into super- and subcritical reaches from the terrain alone.
`E` defaults to a power law of the slope, `0.05 sin(alpha)^(2/3)` (the form attributed
to Briggs 1981 in the drainage-flow literature). **That coefficient is an assumption
here, not a verified constant** -- entrainment into a stable current is uncertain by a
factor of several; pass your own or bracket it. On a nearly flat river reach the bed
slope no longer drives the current (its own depth gradient does), so the equilibrium
speed there is a lower bound.

**Three Froude numbers** that get confused: `froude_mountain` = `U / (N H)` (does the
flow aloft go over an obstacle or round it), `froude_layer` = `U / sqrt(g' h)` (is a
current super- or subcritical; 1 at a hydraulic control), and `equilibrium_froude` above.

**Pool tilt.** With the pool at rest under a geostrophic wind `U` aloft,
`grad(h) = (f / g') k x U` (Margules): the pool's top rises to the **left** of the wind
looking downwind (northern hemisphere), towards the lower pressure aloft. 7 m s-1 over a
5 K pool at 40 N is 3.6 m per km -- 250 m across a 70 km basin, which is the depth of
the pool. `geostrophic_pressure_gradient` and `pool_head_pa` put the two pressure
differences side by side.

## 3. Throat hydraulics (`hydraulics`)

A pool `dtheta` colder than the air above behaves like water under the reduced gravity
`g' = g dtheta / theta0`. For a throat whose cross-section is known as area against
interface level (from `terrain.throat` or `terrain.profiles`):

- `critical_capacity(stages, area, energy, g')`: the inviscid maximum from a reservoir at
  rest, `Q = max over eta of A(eta) sqrt(2 g' (E - eta))`. For a rectangular section it
  is the weir formula `(2/3)^1.5 W sqrt(g') H^1.5`; the tests check the critical depth at
  2/3, 3/4 and 4/5 of the head for rectangular, parabolic and triangular sections.
- `drowned_capacity`: the same throat when the downstream pool stands above the critical
  level (an orifice), zero once the pools are level.
- `backwater_capacity(reach, energy, g')`: a long canyon, where bed and interface drag
  limit the flow: a standard-step profile from the exit upstream, reset to critical
  wherever it would fall below it, so the control section is found rather than assumed.
  The friction slope is `u^2 (cd P + ci T) / (g' A)`.
- `normal_depth_discharge`: uniform flow, the reduced-gravity Chezy formula.

A real pool is continuously stratified, not a slab. For a linearly stratified reservoir
drawn through a line opening the discharge per unit width scales as `N H^2` with a
critical Froude number near `1/pi` (selective withdrawal). To compare it with the slab,
give both the same **total buoyancy** -- the same mean deficit, which is what a heat
budget fixes and what `cascade` uses (`g'` from `D / (rho cp V)`):

    slab:    integral of buoyancy = g' H
    linear:  integral of N^2 (H - z) dz = N^2 H^2 / 2   ->   N^2 = 2 g' / H
    q_strat = (1/pi) N H^2 = (sqrt(2)/pi) sqrt(g') H^1.5 = STRATIFIED_FACTOR * q_weir

so `STRATIFIED_FACTOR = (sqrt(2)/pi) / (2/3)^1.5 = 0.827`. (Matching the *bottom*
deficit instead, `N^2 = g'/H`, gives 0.585 -- a pool with half the buoyancy; the first
version used that value, which understated the stratified capacity by a factor
`sqrt(2)`.) **Published values of the withdrawal constant differ by tens of per cent;
carry both closures as a bracket.**

The geometry-only measures (sill height, throat area, width in cells) need none of this
and are the firmer result. The capacities are upper bounds on what a *model* carries: a
model does not resolve a current through fewer than about five cells.

Precedents for hydraulics on real valley sections: Gohm & Mayr (2004, QJRMS 130,
449-480); canyon exit jets, Chrust, Whiteman & Hoch (2013, JAMC 52, 1187-1200).

## 4. The cascade (`cascade`)

Each `Node` is a basin with its hypsometry, an exit throat (area against stage on some
terrain) and the node it drains into. Its state is pool **volume** and **heat deficit**,
so the pool's temperature deficit is an outcome:

    dV/dt = eff * P_slope / (rho cp dtheta_in) + sum(Q_in) - Q_out
    dD/dt = eff * P_slope + P_pool + sum(rho cp dtheta_up Q_in) - rho cp dtheta Q_out

`P_slope` is the cooling over the catchment above the pool top, `P_pool` the cooling of
the surface under the pool (it chills the pool without adding volume), `eff` the share
of the slope cooling that reaches the pool as a current, and `Q_out` the throat's
drowned capacity for the pool's own `g'`, so a pool backing up from below throttles the
one above it.

Bookkeeping: explicit Euler, the outflow of a step capped at the volume present. A pool
that drains away inside a step takes the deficit it gained during that step with it
(into the node below, or out of the system, and into that step's `phi_out_w`), so volume
and heat deficit are both conserved. Every `downstream` must name a node of the cascade
(`None` is the only way out of the system); a name that matches no node is an error.
`CascadeParams.day_length_h` (default 10 h) is the daytime over which `day_loss` of a
pool decays when `is_day` is given.

What it is for: run it twice, with the throat curves of the true terrain and of a model
grid, and the difference is what the grid spacing does to the answer. What it is not: a
forecast. `eff` and `dtheta_in` cannot be had from the terrain; supply usually exceeds
any slot's capacity many times over, so there is no steady pool height behind a slot --
report the leak ratio, the time to first spill and the deficit delivered, as functions
of `eff`.

## 5. References

Bolton (1980) MWR 108, 1046. Dozier & Frew (1990) IEEE TGRS 28, 963. Louis (1979) BLM 17,
187. Manins & Sawford (1979) JAS 36, 619. Prandtl (1942) *Fuehrer durch die
Stroemungslehre*. Prata (1996) QJRMS 122, 1127. Gohm & Mayr (2004) QJRMS 130, 449.
Chrust, Whiteman & Hoch (2013) JAMC 52, 1187. The entrainment power law and the
stratified-withdrawal constant are flagged above as assumptions.

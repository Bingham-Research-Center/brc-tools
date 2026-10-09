# Idealised flow over terrain (`brc_tools.flow`)

`brc_tools.drainage` says what cold air does when it drains *off* terrain. This
subpackage says what a stratified wind does when it blows *over* it, and what a cold pool
under that wind does in return. Same contract: arithmetic on a named closure, constants as
arguments, nothing a measurement. Tested against closed forms in `tests/test_flow.py`.

| Module | What it answers | Closure |
|---|---|---|
| `mountainwave.linear_3d` | waves, surface wind and pressure over a DEM | linear Boussinesq, uniform U and N (Smith 1980) |
| `mountainwave.layered_2d` | trapped lee waves and surface flow reversal along a transect | same, N piecewise constant, inversions as jumps |
| `layer` | is a ridge a hydraulic control; how fast is the lee jet | one-layer reduced-gravity shallow water |
| `leewaves` | does the profile trap a wave; how long is it | two-layer Scorer, inversion-capped (Vosper 2004) |
| `seiche` | slowest free oscillations of a pool | reduced-gravity shallow-water eigenmodes |
| `pool` | how far a wind aloft moves a pool's top | hydrostatic stagnant pool as a soft boundary |

`terrain.skyview.horizon_angles` / `in_shadow` (same scan as `sky_view`, kept per
azimuth) and `visualize.printsize` (figures drawn at their printed width) came in with it.

## 1. Linear mountain waves

Fourier transform the terrain; with K² = k² + l² and the intrinsic frequency
σ = Uk + Vl,

    m² = K² (N²/σ² − 1)      (hydrostatic: K² N²/σ²)
    η̂(z) = ĥ e^{imz},   ŵ = iσ η̂,   p̂ = iρ₀ σ² m η̂ / K²,   û = −k p̂ / (ρ₀σ)

with Im m ≥ 0 (radiation upward). σ carries −iε, a Rayleigh friction of time scale 1/ε that
only regularises the waves whose crests lie along the wind. Rows of the input run **south to
north**. Valid while N h / U ≲ 0.5; isentropes overturn where −∂η/∂z = 1, first at
N h / U = 1 for the Witch of Agnesi in linear theory (0.85 in Long's exact solution).

`layered_2d` integrates the log-derivative R = w′/w of w″ + (l² − k²) w = 0 down from the
radiating top layer, exactly through each layer of constant l = N/U and across each
inversion with U² (w′_below − w′_above) = g′ w, then carries the amplitude up from
ŵ(0) = iUk ĥ. A trapped mode is a pole on the real k axis; ε turns it into a lee-wave
train of decay length ~U/ε (default: half the padded transect). `LayeredWave.surface_wind`
is U + u′ at the ground; where it is negative, linear theory has reversed the surface flow
under a lee-wave crest — the usual linear proxy for a rotor (Doyle & Durran 2002).

## 2. One-layer hydraulics (`layer`)

Layer depth D₀, speed U₀, reduced gravity g′, obstacle h: F₀ = U₀/√(g′D₀), M = h/D₀.
Critical flow at the crest needs M ≥ M_c = 1 + F₀²/2 − (3/2)F₀^{2/3}. Below it the flow
passes uncontrolled (no windstorm); at or above, a bore runs upstream, the lee goes
supercritical, and the jet ends in a jump. `controlled_flow` solves the bore (mass,
momentum) and crest criticality together and returns the lee jet's depth, speed and Froude
number. For F₀ > 1 a stationary upstream jump is possible above M_s, and between M_s and M_c
both states exist.

## 3. Trapped lee waves (`leewaves`)

Steady trapped modes satisfy m₁ cot(m₁H) + μ₂ = g′/U², m₁ = √(l₁² − k²), μ₂ = √(k² − l₂²);
`trapped_wavelengths` finds every root on a pole-free form. Scorer: a mode needs
l₁² − l₂² > π²/(4H²). Vosper: a neutral layer under an inversion traps when
Fi² < 1/(l₂H coth l₂H), Fi = U/√(g′H) — roughly Fi < 1.

## 4. Pools (`seiche`, `pool`)

Free modes: ω² η = −g′ ∇·(H∇η), no flux through the shoreline; face depth is the mean of two
wet cells. The constant (volume) mode is dropped. Rotation is negligible when the Rossby
radius √(g′H)/f (~80 km at 7 m s⁻¹) exceeds the pool (`rossby_radius`). Check:
`merian_period`.

A stagnant pool is hydrostatic: η = −p′/(ρ₀g′). Because g′ ~ g/100, a 20 Pa wave-pressure
anomaly moves a 3 K inversion by 200 m. As a boundary for the flow aloft (2-D hydrostatic,
Z = iUN sgn k): ζ̂ = ĥ_out/(1 + Z/g′), η̂ = −(Z/g′) ζ̂, so Γ = UN/g′ sets how soft the pool
is. Wedderburn number g′H²/(u*²L) < 1: the interface surfaces upwind.

## 5. References

Baines (1995) *Topographic Effects in Stratified Flows*, CUP. Doyle & Durran (2002) JAS 59,
186. Houghton & Kasahara (1968) CPAM 21, 1. Lareau & Horel (2015) BLM 154, 291. Long (1954)
Tellus 6, 97. Miles & Huppert (1969) JFM 35, 497. Scorer (1949) QJRMS 75, 41. Smith (1980)
Tellus 32, 348. Thompson & Imberger (1980) Proc. 2nd Int. Symp. Stratified Flows. Vosper
(2004) QJRMS 130, 1723.

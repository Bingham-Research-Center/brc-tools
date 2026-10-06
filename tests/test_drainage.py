"""brc_tools.drainage against closed forms: hydraulics, the cascade, slope flow, the surface balance."""

from __future__ import annotations

import importlib
import sys
import warnings

import numpy as np
import pytest

from brc_tools.drainage import cascade, cooling, hydraulics as hy, slopeflow as sf

GP = hy.reduced_gravity(5.0, 270.0)


def test_subpackage_imports_with_numpy_alone(monkeypatch):
    for name in ("scipy", "rasterio", "richdem", "pyproj", "netCDF4", "herbie", "xarray"):
        monkeypatch.setitem(sys.modules, name, None)
    for mod in ("brc_tools.drainage", "brc_tools.drainage.hydraulics", "brc_tools.drainage.cascade",
                "brc_tools.drainage.slopeflow", "brc_tools.drainage.cooling"):
        sys.modules.pop(mod, None)
        importlib.import_module(mod)


# ------------------------------------------------------------------ critical capacity
def section(kind, stages, z0=1000.0, w=500.0, m=2.0):
    h = np.maximum(stages - z0, 0.0)
    if kind == "rectangle":
        return w * h
    if kind == "triangle":
        return m * h ** 2
    return (2.0 / 3.0) * np.sqrt(4.0 * m) * h ** 1.5          # parabola: width = sqrt(4 m h)


@pytest.mark.parametrize("kind,frac", [("rectangle", 2 / 3), ("parabola", 3 / 4), ("triangle", 4 / 5)])
def test_critical_depth_fraction_of_the_head(kind, frac):
    stages = np.linspace(1000.0, 1400.0, 801)
    q, eta_c = hy.critical_capacity(stages, section(kind, stages), 1300.0, GP)
    assert (eta_c - 1000.0) / 300.0 == pytest.approx(frac, abs=0.01)
    assert q > 0


def test_rectangular_throat_is_the_weir_formula():
    stages = np.linspace(1000.0, 1400.0, 801)
    for head in (50.0, 150.0, 300.0):
        q, _ = hy.critical_capacity(stages, section("rectangle", stages), 1000.0 + head, GP)
        assert q == pytest.approx(hy.WEIR * 500.0 * np.sqrt(GP) * head ** 1.5, rel=2e-3)
    energies = np.array([1050.0, 1150.0, 1300.0])
    qs = hy.rating_curve(stages, section("rectangle", stages), energies, GP)
    assert np.all(np.diff(qs) > 0) and qs.shape == (3,)
    assert hy.rating_curve(stages, section("rectangle", stages), energies, GP, factor=hy.STRATIFIED_FACTOR) == pytest.approx(
        hy.STRATIFIED_FACTOR * qs)
    assert hy.STRATIFIED_FACTOR == pytest.approx(0.827, abs=0.002)


def test_stratified_factor_compares_pools_of_equal_total_buoyancy():
    # a linearly stratified pool with the slab's total buoyancy, g' H = N^2 H^2 / 2, passes
    # (1/pi) N H^2 per unit width; that is STRATIFIED_FACTOR times the slab's weir discharge
    for gp, depth in ((GP, 100.0), (0.05, 300.0)):
        n = np.sqrt(2.0 * gp / depth)
        assert n ** 2 * depth ** 2 / 2.0 == pytest.approx(gp * depth)
        assert (1.0 / np.pi) * n * depth ** 2 == pytest.approx(hy.STRATIFIED_FACTOR * hy.WEIR * np.sqrt(gp) * depth ** 1.5)
    # the bottom-deficit match (N^2 = g'/H) is a pool with half the buoyancy: sqrt(2) less
    assert hy.STRATIFIED_FACTOR / ((1.0 / np.pi) / hy.WEIR) == pytest.approx(np.sqrt(2.0))


def test_no_flow_below_the_sill_and_drowning_reduces_it():
    stages = np.linspace(900.0, 1400.0, 501)
    area = section("rectangle", stages, z0=1100.0)                # the throat opens at 1100 m
    assert hy.critical_capacity(stages, area, 1050.0, GP)[0] == 0.0
    free, eta_c = hy.critical_capacity(stages, area, 1300.0, GP)
    assert hy.drowned_capacity(stages, area, 1300.0, eta_c - 20.0, GP) == pytest.approx(free)
    partly = hy.drowned_capacity(stages, area, 1300.0, 1280.0, GP)
    assert 0.0 < partly < free
    assert hy.drowned_capacity(stages, area, 1300.0, 1300.0, GP) == 0.0


# ------------------------------------------------------------------ backwater
def uniform_reach(n=81, length=40e3, slope=1e-3, w=400.0, depth_range=400.0):
    s = np.linspace(0.0, length, n)
    bed = 1500.0 - slope * s
    stages = np.linspace(bed.min(), bed.max() + depth_range, 1201)
    h = np.maximum(stages[None, :] - bed[:, None], 0.0)
    return hy.Reach(s_m=s, stages_m=stages, area_m2=w * h, top_m=np.where(h > 0, w, 0.0),
                    perimeter_m=np.where(h > 0, w, 0.0)), bed, w, slope


def test_backwater_without_friction_is_the_smallest_critical_capacity():
    reach, bed, w, _ = uniform_reach()
    energy = bed[0] + 120.0
    q, ctl = hy.backwater_capacity(reach, energy, GP, cd=0.0, ci=0.0)
    expect = min(hy.critical_capacity(reach.stages_m, reach.area_m2[k], energy, GP)[0] for k in range(reach.s_m.size))
    assert q == pytest.approx(expect, rel=5e-3)


def test_backwater_recovers_normal_depth_in_a_long_uniform_channel():
    # the drawdown curve reaches normal depth over a few times h_n / slope: keep that far below the length
    reach, bed, w, slope = uniform_reach(slope=5e-3, depth_range=200.0)
    cd, ci, q = 0.030, 0.006, 5.0e3
    h_n = (q ** 2 * (cd + ci) / (GP * w ** 2 * slope)) ** (1.0 / 3.0)
    h_c = (q ** 2 / (GP * w ** 2)) ** (1.0 / 3.0)
    assert h_n > 1.5 * h_c                                         # a mild slope: normal flow is subcritical
    assert reach.s_m[-1] > 8.0 * h_n / slope
    energy, levels, control = hy.backwater_energy(reach, q, GP, cd=cd, ci=ci)
    assert control == reach.s_m.size - 1                           # the exit is the control
    assert levels[-1] - bed[-1] == pytest.approx(h_c, rel=0.02)    # critical there
    assert levels[0] - bed[0] == pytest.approx(h_n, rel=0.03)      # normal depth far upstream
    assert hy.normal_depth_discharge(w * h_n, w, w, slope, GP, cd, ci) == pytest.approx(q, rel=1e-6)
    # and the capacity for that reservoir level returns the discharge it was built from
    q_back, _ = hy.backwater_capacity(reach, energy, GP, cd=cd, ci=ci)
    assert q_back == pytest.approx(q, rel=0.01)


def test_backwater_warns_when_the_section_table_is_too_short():
    reach, *_ = uniform_reach(slope=5e-3, depth_range=200.0)
    with warnings.catch_warnings():
        warnings.simplefilter("error")                             # a table tall enough: silent
        hy.backwater_energy(reach, 5.0e3, GP, cd=0.030, ci=0.006)
    short, *_ = uniform_reach(slope=5e-3, depth_range=20.0)
    with pytest.warns(RuntimeWarning, match="top stage"):
        energy, levels, _ = hy.backwater_energy(short, 5.0e4, GP, cd=0.030, ci=0.006)
    assert levels.max() == pytest.approx(short.stages_m[-1])       # held at the top: a lower bound


def test_friction_lowers_the_capacity():
    reach, bed, *_ = uniform_reach()
    energy = bed[0] + 120.0
    q0, _ = hy.backwater_capacity(reach, energy, GP, cd=0.0, ci=0.0)
    q1, _ = hy.backwater_capacity(reach, energy, GP, cd=0.01, ci=0.002)
    q2, _ = hy.backwater_capacity(reach, energy, GP, cd=0.03, ci=0.002)
    assert q0 > q1 > q2 > 0


def test_a_constriction_becomes_the_control():
    reach, bed, w, _ = uniform_reach(slope=2e-4)
    k = 30
    scale = np.ones(reach.s_m.size)
    scale[k] = 0.2                                                 # one section five times narrower
    narrow = hy.Reach(reach.s_m, reach.stages_m, reach.area_m2 * scale[:, None], reach.top_m * scale[:, None],
                      reach.perimeter_m * scale[:, None])
    _, _, control = hy.backwater_energy(narrow, 1.0e5, GP, cd=0.002, ci=0.0)
    assert control == k


# ------------------------------------------------------------------ cascade
def flat_basin(name, floor, area_km2, downstream=None, throat=None, n=400, relief=600.0):
    z = np.linspace(floor, floor + relief, n)                      # a V-shaped hypsometry
    stages = np.linspace(floor, floor + relief, 61)
    area = np.zeros_like(stages) if throat is None else throat(stages)
    return cascade.Node(name=name, z_cells=z, cell_area_m2=area_km2 * 1e6 / n, throat_stage_m=stages,
                        throat_area_m2=area, downstream=downstream)


def test_node_stage_and_volume_are_inverse():
    node = flat_basin("a", 1500.0, 100.0)
    for stage in (1500.0, 1550.0, 1900.0):
        assert node.stage(node.volume(stage)) == pytest.approx(stage, abs=1e-6)
    assert node.flooded_area(2200.0) == pytest.approx(node.area_m2)


def test_a_closed_basin_fills_at_the_supply_rate():
    node = flat_basin("a", 1500.0, 100.0)
    t = np.array([0.0, 3600.0 * 6])
    p = cascade.CascadeParams(efficiency=0.5, dtheta_in_k=4.0, day_loss=0.0)
    res = cascade.integrate([node], {"a": np.full(2, 20.0)}, {"a": np.zeros(2)}, t, p, dt=60.0, record_every=1)
    # nothing leaves; slopes above the pool keep supplying: bound the volume by the whole-catchment rate
    upper = 0.5 * 20.0 * node.area_m2 * t[-1] / (p.rho * 1004.0 * 4.0)
    assert 0.5 * upper < res.volume_m3[-1, 0] <= upper * 1.001
    assert res.dtheta_k[-1, 0] == pytest.approx(4.0, rel=1e-6)     # no pool cooling: the deficit stays the inflow's
    assert np.all(res.q_out_m3s == 0.0)


def test_two_reservoirs_conserve_volume_and_deficit():
    upper = flat_basin("up", 1700.0, 50.0, downstream="down", throat=lambda s: 300.0 * np.maximum(s - 1700.0, 0.0))
    lower = flat_basin("down", 1500.0, 200.0)
    upper.v0_m3 = upper.volume(1800.0)
    upper.d0_j = 1.0 * 1004.0 * 6.0 * upper.v0_m3                  # a 6 K pool
    t = np.array([0.0, 3600.0 * 8])
    p = cascade.CascadeParams(efficiency=0.0, day_loss=0.0)
    zero = {"up": np.zeros(2), "down": np.zeros(2)}
    res = cascade.integrate([upper, lower], zero, zero, t, p, dt=30.0, record_every=1)
    assert res.volume_m3.sum(axis=1) == pytest.approx(upper.v0_m3, rel=1e-9)
    assert res.deficit_j.sum(axis=1) == pytest.approx(upper.d0_j, rel=1e-9)
    assert res.volume_m3[-1, 1] > 0.5 * upper.v0_m3                # most of it has moved down
    assert res.first_outflow_s("up") == 0.0
    assert res.delivered_j("up") == pytest.approx(res.deficit_j[-1, 1], rel=0.02)
    assert np.isnan(res.first_outflow_s("down"))


def test_a_raised_sill_delays_the_spill():
    def run(sill):
        up = flat_basin("up", 1700.0, 50.0, downstream="down", throat=lambda s: 300.0 * np.maximum(s - sill, 0.0))
        down = flat_basin("down", 1500.0, 200.0)
        t = np.array([0.0, 3600.0 * 12])
        f = {"up": np.full(2, 20.0), "down": np.zeros(2)}
        z = {"up": np.zeros(2), "down": np.zeros(2)}
        return cascade.integrate([up, down], f, z, t, cascade.CascadeParams(day_loss=0.0), dt=60.0)
    open_, dammed = run(1700.0), run(1850.0)
    assert open_.first_outflow_s("up") < dammed.first_outflow_s("up")
    assert dammed.delivered_j("up") < open_.delivered_j("up")
    assert dammed.stage_m[:, 0].max() > open_.stage_m[:, 0].max()


def test_cycles_are_rejected():
    a = flat_basin("a", 1500.0, 10.0, downstream="b")
    b = flat_basin("b", 1500.0, 10.0, downstream="a")
    z = {"a": np.zeros(2), "b": np.zeros(2)}
    with pytest.raises(ValueError):
        cascade.integrate([a, b], z, z, np.array([0.0, 60.0]))


def test_a_misspelt_downstream_is_an_error_not_an_exit():
    a = flat_basin("a", 1700.0, 10.0, downstream="lower_basn", throat=lambda s: 300.0 * np.maximum(s - 1700.0, 0.0))
    b = flat_basin("lower_basin", 1500.0, 10.0)
    z = {"a": np.zeros(2), "lower_basin": np.zeros(2)}
    with pytest.raises(ValueError, match="lower_basn"):
        cascade.integrate([a, b], z, z, np.array([0.0, 60.0]))
    with pytest.raises(ValueError, match="unique"):
        cascade.integrate([b, flat_basin("lower_basin", 1500.0, 10.0)], z, z, np.array([0.0, 60.0]))


def emptying_pool(downstream):
    """A shallow pool behind a throat far wider than it needs: it drains in the first step,
    while the cooling under it keeps adding deficit during that step."""
    up = flat_basin("up", 1700.0, 50.0, downstream=downstream, throat=lambda s: 1e5 * np.maximum(s - 1700.0, 0.0))
    up.v0_m3 = up.volume(1710.0)
    up.d0_j = 1.0 * 1004.0 * 6.0 * up.v0_m3
    return up


def test_a_pool_that_empties_inside_a_step_keeps_its_deficit():
    dt = 60.0
    t = np.array([0.0, 600.0])
    p = cascade.CascadeParams(efficiency=0.0, day_loss=0.0)
    up, down = emptying_pool("down"), flat_basin("down", 1500.0, 200.0)
    cool = {"up": np.full(2, 50.0), "down": np.full(2, 50.0)}
    res = cascade.integrate([up, down], cool, cool, t, p, dt=dt, record_every=1)
    assert res.volume_m3[1, 0] == 0.0 and res.q_out_m3s[0, 0] > 0.0          # gone after one step
    supplied = res.supply_w[:-1].sum() * dt                                  # explicit Euler: what the steps added
    assert res.deficit_j[-1].sum() == pytest.approx(up.d0_j + supplied, rel=1e-9)
    assert res.volume_m3[-1].sum() == pytest.approx(up.v0_m3, rel=1e-9)
    # an exit out of the system: what is left plus what left equals what there was plus what was added
    alone = emptying_pool(None)
    res = cascade.integrate([alone], {"up": np.full(2, 50.0)}, {"up": np.full(2, 50.0)}, t, p, dt=dt, record_every=1)
    left = res.phi_out_w[:-1, 0].sum() * dt
    assert res.deficit_j[-1, 0] + left == pytest.approx(alone.d0_j + res.supply_w[:-1, 0].sum() * dt, rel=1e-9)


def test_day_length_sets_the_decay_rate():
    def run(**kw):
        node = flat_basin("a", 1500.0, 100.0)
        node.v0_m3 = node.volume(1600.0)
        node.d0_j = 1.0 * 1004.0 * 5.0 * node.v0_m3
        p = cascade.CascadeParams(efficiency=0.0, day_loss=0.5, **kw)
        zero = {"a": np.zeros(2)}
        res = cascade.integrate([node], zero, zero, np.array([0.0, 5 * 3600.0]), p, dt=60.0, is_day=lambda t: True,
                                record_every=1)
        return res.deficit_j[-1, 0] / node.d0_j
    assert run(day_length_h=5.0) == pytest.approx(0.5, rel=1e-6)            # half gone after the 5 h day
    assert run() == pytest.approx(0.5 ** 0.5, rel=1e-6)                      # the default 10 h day: half way there


def test_delivered_deficit_without_numpy_trapezoid(monkeypatch):
    # NumPy < 2.0 has only np.trapz; the result must not depend on which one exists
    up = flat_basin("up", 1700.0, 50.0, downstream="down", throat=lambda s: 300.0 * np.maximum(s - 1700.0, 0.0))
    up.v0_m3 = up.volume(1800.0)
    up.d0_j = 1.0 * 1004.0 * 6.0 * up.v0_m3
    zero = {"up": np.zeros(2), "down": np.zeros(2)}
    res = cascade.integrate([up, flat_basin("down", 1500.0, 200.0)], zero, zero, np.array([0.0, 3600.0]),
                            cascade.CascadeParams(efficiency=0.0, day_loss=0.0), dt=60.0)
    expect = res.delivered_j("up")
    monkeypatch.delattr(np, "trapezoid", raising=False)
    monkeypatch.setattr(np, "trapz", lambda y, x: float(np.sum(0.5 * (y[1:] + y[:-1]) * np.diff(x))), raising=False)
    assert res.delivered_j("up") == pytest.approx(expect, rel=1e-12)


# ------------------------------------------------------------------ slope flow
def test_prandtl_jet_thins_on_steep_slopes_and_its_speed_ignores_the_slope():
    assert sf.prandtl_jet_height(10.0, 0.02, 0.1) == pytest.approx(5.96, abs=0.05)
    assert sf.prandtl_jet_height(3.0, 0.02, 0.1) == pytest.approx(10.9, abs=0.1)
    assert sf.prandtl_jet_speed(5.0, 0.02) == pytest.approx(2.93, abs=0.02)
    z = np.linspace(0.0, 60.0, 6001)
    u, th = sf.prandtl_profile(z, 5.0, 10.0, 0.02)
    assert z[np.argmax(u)] == pytest.approx(sf.prandtl_jet_height(10.0, 0.02), abs=0.02)
    assert u.max() == pytest.approx(sf.prandtl_jet_speed(5.0, 0.02), rel=1e-3)
    assert th[0] == pytest.approx(-5.0) and u[0] == 0.0


def test_equilibrium_current_and_its_criticality():
    u = sf.equilibrium_speed(GP, 100.0, 1.0, cd=0.005, entrainment=0.0)
    assert u == pytest.approx(np.sqrt(GP * 100.0 * np.sin(np.radians(1.0)) / 0.005))
    alpha_c = sf.critical_slope_deg(cd=0.005, entrainment=0.0)
    assert np.tan(np.radians(alpha_c)) == pytest.approx(0.005, rel=1e-3)
    assert sf.equilibrium_froude(alpha_c * 2, 0.005, 0.0) > 1 > sf.equilibrium_froude(alpha_c / 2, 0.005, 0.0)
    assert sf.equilibrium_froude(2.0, 0.005) < sf.equilibrium_froude(2.0, 0.005, 0.0)    # entrainment slows it


def test_froude_numbers_tilt_and_travel_time():
    assert sf.froude_mountain(5.0, 0.02, 670.0) == pytest.approx(0.373, abs=0.001)
    assert sf.froude_layer(np.sqrt(GP * 200.0), GP, 200.0) == pytest.approx(1.0)
    assert sf.pool_tilt(7.0, 40.0, GP) == pytest.approx(3.61e-3, rel=0.01)
    assert sf.geostrophic_pressure_gradient(7.0, 40.0) * 1e5 == pytest.approx(65.6, rel=0.01)   # Pa per 100 km
    assert sf.pool_head_pa(200.0, GP) == pytest.approx(36.3, rel=0.01)
    assert sf.travel_time_s([0.0, 1000.0, 3000.0], [2.0, 2.0, 2.0]) == pytest.approx(1500.0)
    assert sf.brunt_vaisala(0.011, 270.0) == pytest.approx(0.02, abs=5e-4)


# ------------------------------------------------------------------ cooling
def test_surface_balance_closes_and_snow_cools_the_air_harder():
    t_a = np.array([258.0, 258.0, 265.0])
    e = cooling.vapour_pressure_hpa(np.array([253.0, 253.0, 258.0]))
    svf = np.array([1.0, 1.0, 0.7])
    snow = np.array([True, False, False])
    depth = np.array([0.5, 0.0, 0.0])
    t_base = np.array([273.15, 262.0, 266.0])
    p = cooling.CoolingParams()
    ts, h, g, ld, lu = cooling.solve_surface(t_a, e, svf, snow, depth, t_base, p)
    assert np.allclose(lu - ld - h - g, 0.0, atol=0.05)            # the balance it was solved for
    assert np.all(ts < t_a) and np.all(h > 0)                      # the surface is colder; the air loses heat
    assert h[0] > h[1]                                             # snow: emits more, conducts less
    weak = cooling.solve_surface(t_a, e, svf, snow, depth, t_base, p.with_(u_ms=1.5, c_hn=1e-3))[1]
    assert np.all(weak < h)                                        # weaker coupling, smaller flux
    # a per-cell wind replaces params.u_ms: the same number everywhere reproduces the scalar
    # solve, and a calmer cell gives up less heat than its windier neighbour
    same = cooling.solve_surface(t_a, e, svf, snow, depth, t_base, p, wind_ms=np.full(3, p.u_ms))[1]
    assert np.allclose(same, h)
    mixed = cooling.solve_surface(t_a, e, svf, snow, depth, t_base, p, wind_ms=np.array([p.u_ms, 1.0, p.u_ms]))[1]
    assert mixed[1] < h[1] and mixed[0] == pytest.approx(h[0]) and mixed[2] == pytest.approx(h[2])
    assert cooling.prata_emissivity(273.15, 4.0) == pytest.approx(0.705, abs=0.02)
    less_sky = cooling.longwave_down(260.0, 2.0, 0.5)
    assert less_sky > cooling.longwave_down(260.0, 2.0, 1.0)       # canyon walls radiate more than clear sky


def test_surface_balance_obeys_kirchhoff():
    # a grey surface absorbs eps of L_down and reflects the rest: eps sigma Ts^4 = eps L_down + H + G
    t_a = np.array([258.0, 258.0, 265.0])
    e = cooling.vapour_pressure_hpa(np.array([253.0, 253.0, 258.0]))
    svf = np.array([1.0, 1.0, 0.7])
    snow = np.array([True, False, False])
    depth = np.array([0.5, 0.0, 0.0])
    t_base = np.array([273.15, 262.0, 266.0])
    p = cooling.CoolingParams()
    eps = np.where(snow, p.eps_snow, p.eps_soil)
    ts, h, g, ld, lu = cooling.solve_surface(t_a, e, svf, snow, depth, t_base, p)
    emitted = eps * cooling.SIGMA * ts ** 4
    assert np.allclose(emitted - eps * ld - h - g, 0.0, atol=0.05)
    assert np.allclose(lu, emitted + (1.0 - eps) * ld)              # upwelling = emitted + reflected
    assert np.allclose((lu - ld) - (h + g), 0.0, atol=0.05)         # the net longwave loss is what H + G resupply
    # a black surface (eps = 1) is the balance with nothing reflected
    black = p.with_(eps_snow=1.0, eps_soil=1.0)
    tsb, hb, gb, ldb, lub = cooling.solve_surface(t_a, e, svf, snow, depth, t_base, black)
    assert np.allclose(cooling.SIGMA * tsb ** 4 - ldb - hb - gb, 0.0, atol=0.05)
    assert np.allclose(lub, cooling.SIGMA * tsb ** 4)
    assert np.all(tsb < ts) and np.all(hb > h)                      # grey radiates its deficit away more slowly


def test_open_water_warms_the_air():
    h, le = cooling.open_water_flux(275.0, 258.0, cooling.vapour_pressure_hpa(253.0), 3.0)
    assert h == pytest.approx(1.0 * 1004.0 * 1.5e-3 * 3.0 * 17.0)
    assert le > 0 and h + le > 80.0

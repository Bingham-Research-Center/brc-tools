"""Unit tests for brc_tools.nwp.wrf_deficit_reference (synthetic dataset; no real wrfout).

The fixture's theta rises 2 K per level from 280 K, the winds are U = 5, V = 2 and the
w-level spacing is 100 m, so every deficit below is a hand-computable sum.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest
from _wrf_synthetic import make_synthetic_wrf

from brc_tools.nwp import wrf_deficit_reference as dr
from brc_tools.nwp import wrf_output as wo


@pytest.fixture
def ds():
    # moisture=True brings HFX = -10 W m-2 and QVAPOR (moist density)
    return make_synthetic_wrf(nz=8, ny=6, nx=6, moisture=True)


@pytest.fixture
def floor(ds):
    hgt = wo.surface_field(ds, "HGT")
    return hgt < hgt.min() + 60.0          # the three lowest columns of the west edge


def _analytic_H(ds, ref_k, cap_agl_m):
    """rho cp max(ref - theta, 0) dz summed over mass levels below the cap."""
    from brc_tools.nwp.wrf_derived import air_density
    theta = wo.potential_temperature(ds)
    zw = wo.geopotential_height_w(ds)
    dz = zw[1:] - zw[:-1]
    agl = wo.height_agl(ds)
    w = air_density(ds) * wo.CP * np.clip(ref_k - theta, 0.0, None) * dz
    w[agl > cap_agl_m] = 0.0
    return w.sum(axis=0)


def test_fixed_datum_flux_is_wind_times_H(ds):
    f = dr.deficit_fixed_fields(ds, 290.0, cap_agl_m=1500.0)
    np.testing.assert_allclose(f.heat_deficit_j_m2, _analytic_H(ds, 290.0, 1500.0), rtol=1e-12)
    np.testing.assert_allclose(f.flux_x_w_m, 5.0 * f.heat_deficit_j_m2, rtol=1e-12)
    np.testing.assert_allclose(f.flux_y_w_m, 2.0 * f.heat_deficit_j_m2, rtol=1e-12)
    g = dr.deficit_fixed_fields(ds, 290.0, cap_agl_m=1500.0, earth_relative=False)
    np.testing.assert_allclose(g.flux_x_w_m, f.flux_x_w_m)   # COSALPHA = 1, SINALPHA = 0
    assert f.heat_deficit_j_m2.min() > 0.0


def test_cap_agl_zeroes_levels_above(ds):
    # mass levels sit at 50, 150, 250, ... m AGL: a 200 m cap keeps exactly two
    f = dr.deficit_fixed_fields(ds, 300.0, cap_agl_m=200.0)
    np.testing.assert_allclose(f.heat_deficit_j_m2, _analytic_H(ds, 300.0, 200.0), rtol=1e-12)
    full = dr.deficit_fixed_fields(ds, 300.0, cap_agl_m=1e4).heat_deficit_j_m2
    assert np.all(f.heat_deficit_j_m2 < full)


def test_flat_profile_equals_constant_datum(ds):
    prof = dr.SunsetProfile(z_asl_m=np.array([1000.0, 5000.0]), theta_k=np.array([290.0, 290.0]),
                            valid_time=datetime(2025, 1, 26, 23), mixed_layer_theta_k=290.0,
                            ml_depth_m=500.0, top_m=5000.0)
    a = dr.deficit_fixed_fields(ds, prof)
    b = dr.deficit_fixed_fields(ds, 290.0)
    np.testing.assert_allclose(a.heat_deficit_j_m2, b.heat_deficit_j_m2)
    np.testing.assert_allclose(a.flux_x_w_m, b.flux_x_w_m)
    assert a.theta_ref_k.shape == wo.potential_temperature(ds).shape


def test_sunset_profile_is_monotone_and_starts_at_ml_theta(ds, floor):
    prof = dr.sunset_profile(ds, floor, time=datetime(2025, 1, 26, 23), ml_depth_m=500.0, top_m=3000.0)
    assert np.all(np.diff(prof.theta_k) >= 0.0)
    assert np.all(np.diff(prof.z_asl_m) > 0.0)
    assert prof.theta_k[0] == pytest.approx(prof.mixed_layer_theta_k)
    assert prof.theta_ref(-1e9) == pytest.approx(prof.mixed_layer_theta_k)   # edge clamp below
    assert prof.floor_cells == int(floor.sum())
    assert prof.method_version == dr.METHOD_VERSION


def test_sunset_profile_ml_theta_hand_value(ds, floor):
    # theta = 280 + 2k on mass levels at 50, 150, 250, 350, 450 m AGL below a 500 m ML:
    # mean of 280, 282, 284, 286, 288 = 284 K in every column, whatever the reducer.
    for stat in ("max", "median", "mean"):
        prof = dr.sunset_profile(ds, floor, time=datetime(2025, 1, 26, 23), ml_depth_m=500.0,
                                 top_m=3000.0, ml_stat=stat)
        assert prof.mixed_layer_theta_k == pytest.approx(284.0)
    # above the ML the profile follows the floor-mean theta(z), which keeps rising
    assert prof.theta_ref(prof.top_m) > prof.mixed_layer_theta_k


def test_sunset_profile_rejects_bad_masks(ds):
    with pytest.raises(ValueError):
        dr.sunset_profile(ds, np.zeros((6, 6), bool), time=datetime(2025, 1, 1))
    with pytest.raises(ValueError):
        dr.sunset_profile(ds, np.ones((6, 6), bool), time=datetime(2025, 1, 1), ml_stat="mode")


def test_two_datum_ordering(ds, floor):
    lo, hi = dr.two_datum(290.0, 0.5)
    assert lo < 290.0 < hi
    prof = dr.sunset_profile(ds, floor, time=datetime(2025, 1, 26, 23), top_m=3000.0)
    plo, phi = dr.two_datum(prof, 0.5)
    np.testing.assert_allclose(phi.theta_k - plo.theta_k, 1.0)
    np.testing.assert_allclose(plo.z_asl_m, prof.z_asl_m)
    assert phi.mixed_layer_theta_k == pytest.approx(prof.mixed_layer_theta_k + 0.5)
    assert "shifted" in phi.notes


def test_at_two_datums_low_then_high(ds):
    lo, hi = dr.at_two_datums(lambda r: dr.deficit_fixed_fields(ds, r).heat_deficit_j_m2, 290.0, delta_k=0.5)
    assert np.all(lo <= hi)
    assert np.all(lo < hi)


def test_json_round_trip(ds, floor, tmp_path):
    prof = dr.sunset_profile(ds, floor, time=datetime(2025, 1, 26, 23, 30), top_m=3000.0,
                             case="gigawatts", night="20250126", run_id="abc", domain=2,
                             floor_label="HGT < 1560 m")
    assert prof.sidecar_name() == "theta_ref_gigawatts_20250126.json"
    p = tmp_path / prof.sidecar_name()
    text = prof.to_json(p)
    assert '"schema": 1' in text and p.exists()
    back = dr.SunsetProfile.from_json(p)
    np.testing.assert_allclose(back.z_asl_m, prof.z_asl_m)
    np.testing.assert_allclose(back.theta_k, prof.theta_k)
    assert back.valid_time == prof.valid_time
    assert back.mixed_layer_theta_k == prof.mixed_layer_theta_k
    assert back.floor_label == "HGT < 1560 m" and back.domain == 2
    # a dict works too, and an unknown newer schema is refused
    assert dr.SunsetProfile.from_json(prof.to_dict()).case == "gigawatts"
    with pytest.raises(ValueError):
        dr.SunsetProfile.from_json({**prof.to_dict(), "schema": 99})


def test_catchment_terms_production_from_hfx(ds):
    masks = {"west": np.zeros((6, 6), bool)}
    masks["west"][:, :3] = True
    terms = dr.catchment_budget_terms(ds, masks, {}, 290.0)
    t = terms["west"]
    area = wo.grid_cell_area_m2(ds)
    assert t.n_cells == 18
    assert t.production_w == pytest.approx(10.0 * area[masks["west"]].sum())   # HFX = -10
    assert t.hfx_mean_w_m2 == pytest.approx(-10.0)
    assert t.storage_lo_j <= t.storage_j <= t.storage_hi_j
    assert np.isnan(t.export_w) and t.edges_w == {}
    assert t.lw_production_w is None                                            # no RTHRATLW


def test_catchment_terms_box_edges_sum_and_transect_reuse(ds):
    # a box walked clockwise: north edge W->E, east edge N->S, south edge E->W, west edge S->N
    la0, la1, lo0, lo1 = 40.1, 40.4, -109.9, -109.6
    edges = [((la1, lo0), (la1, lo1)), ((la1, lo1), (la0, lo1)), ((la0, lo1), (la0, lo0)), ((la0, lo0), (la1, lo0))]
    xlat, xlon = wo.surface_field(ds, "XLAT"), wo.surface_field(ds, "XLONG")
    mask = (xlat >= la0) & (xlat <= la1) & (xlon >= lo0) & (xlon <= lo1)
    terms = dr.catchment_budget_terms(ds, {"box": mask}, {"box": edges}, 290.0)
    t = terms["box"]
    assert len(t.edges_w) == 4
    assert t.export_w == pytest.approx(sum(t.edges_w.values()))
    f = dr.deficit_fixed_fields(ds, 290.0)
    direct = sum(wo.integrate_flux_transect(ds, f.flux_x_w_m, f.flux_y_w_m, a[0], a[1], b[0], b[1]).total_w
                 for a, b in edges)
    assert t.export_w == pytest.approx(direct)
    # uniform wind through a box: what comes in one side leaves the other (small residual
    # from nearest-column sampling only)
    assert abs(t.export_w) < 0.05 * max(abs(v) for v in t.edges_w.values())


def test_lw_term_absent_is_none_and_constant_is_analytic(ds):
    assert dr.longwave_production_field(ds, 290.0) is None
    theta = wo.potential_temperature(ds)
    ds2 = ds.assign(RTHRATLW=(("Time", "bottom_top", "south_north", "west_east"), np.full((1,) + theta.shape, -1e-4)))
    p = dr.longwave_production_field(ds2, 300.0, cap_agl_m=1e4, only_deficit_layer=False)
    from brc_tools.nwp.wrf_derived import air_density
    zw = wo.geopotential_height_w(ds2)
    expect = (air_density(ds2) * wo.CP * 1e-4 * (zw[1:] - zw[:-1])).sum(axis=0)
    np.testing.assert_allclose(p, expect, rtol=1e-12)
    assert np.all(p > 0.0)                                       # cooling produces deficit
    # restricting to the deficit layer against a cold datum removes everything
    q = dr.longwave_production_field(ds2, 200.0, cap_agl_m=1e4, only_deficit_layer=True)
    np.testing.assert_allclose(q, 0.0)
    # the restart name is accepted as a fallback
    ds3 = ds.assign(RTHRATENLW=ds2["RTHRATLW"])
    assert dr.longwave_production_field(ds3, 300.0, only_deficit_layer=False) is not None

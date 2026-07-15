"""Unit tests for brc_tools.nwp.wrf_output (synthetic dataset; no real wrfout)."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest
from _wrf_synthetic import make_synthetic_wrf

from brc_tools.nwp import wrf_output as wo


@pytest.fixture
def ds():
    return make_synthetic_wrf(nz=4, ny=6, nx=6)


def test_wrfout_path_formats_colons(tmp_path):
    p = wo.wrfout_path(tmp_path, 3, datetime(2013, 2, 2, 12))
    assert p.name == "wrfout_d03_2013-02-02_12:00:00"


def test_center_indices(ds):
    assert wo.center_indices(ds) == (3, 3)


def test_potential_temperature_is_T_plus_300(ds):
    theta = wo.potential_temperature(ds)
    assert theta.shape == (4, 6, 6)
    # level 0 -> 280 K, level 3 -> 286 K
    np.testing.assert_allclose(theta[:, 0, 0], [280.0, 282.0, 284.0, 286.0])


def test_destagger_by_dim_name_shapes(ds):
    u, v = wo.grid_relative_winds(ds)
    assert u.shape == (4, 6, 6) and v.shape == (4, 6, 6)
    assert wo.vertical_velocity(ds).shape == (4, 6, 6)
    assert wo.geopotential_height_w(ds).shape == (5, 6, 6)  # w-levels
    assert wo.geopotential_height_mass(ds).shape == (4, 6, 6)  # mass levels


def test_geopotential_height_mass_destagger(ds):
    z = wo.geopotential_height_mass(ds)
    # terrain(0,0)=1500; mass height = terrain + (k+0.5)*100
    np.testing.assert_allclose(z[:, 0, 0], [1550.0, 1650.0, 1750.0, 1850.0])
    assert np.all(np.diff(z[:, 0, 0]) > 0)  # monotonic upward


def test_earth_rotation_identity_when_sinalpha_zero(ds):
    u, v = wo.grid_relative_winds(ds)
    ue, ve = wo.earth_relative_winds(ds)
    np.testing.assert_allclose(ue, u)
    np.testing.assert_allclose(ve, v)


def test_nearest_column_index(ds):
    assert wo.nearest_column_index(ds, 40.3, -109.7) == (3, 3)
    assert wo.nearest_column_index(ds, 40.5, -109.6) == (5, 4)


def test_theta_2m_prefers_TH2(ds):
    np.testing.assert_allclose(wo.theta_2m(ds), 275.0)


def test_build_section_ew(ds):
    sec = wo.build_section(ds, "EW")
    assert sec.orientation == "EW"
    assert sec.distance_km.shape == (6,)
    assert sec.theta2d.shape == (4, 6)
    assert sec.terrain1d.shape == (6,)
    assert sec.center_index == 3
    assert sec.termini == ("A", "B")
    # along-section wind is grid-relative U == 5
    np.testing.assert_allclose(sec.along2d, 5.0)
    # theta2d is full theta, not perturbation
    assert sec.theta2d.min() >= 270.0
    # distance uses DX
    np.testing.assert_allclose(sec.distance_km[1], 333.333 / 1000.0)


def test_build_section_ns(ds):
    sec = wo.build_section(ds, "NS")
    assert sec.distance_km.shape == (6,)
    assert sec.termini == ("C", "D")
    np.testing.assert_allclose(sec.along2d, 2.0)  # grid-relative V


def test_build_section_bad_orientation(ds):
    with pytest.raises(ValueError):
        wo.build_section(ds, "diagonal")


def test_extract_column(ds):
    col = wo.extract_column(ds, 40.3, -109.7, label="center")
    assert col.label == "center"
    assert col.theta.shape == (4,)
    np.testing.assert_allclose(col.theta, [280.0, 282.0, 284.0, 286.0])
    assert np.all(np.diff(col.height_asl) > 0)
    assert np.all(np.diff(col.pressure_hpa) < 0)  # decreasing upward
    assert col.terrain_m == pytest.approx(1590.0)  # 1500 + 20*3 + 10*3


def test_domain_outline_ring_closed(ds):
    outline = wo.domain_outline(ds, label="d03")
    assert outline.label == "d03"
    assert outline.lon_ring.shape == outline.lat_ring.shape
    assert outline.lon_ring.ndim == 1


def test_cold_pool_diagnostics_positive(ds):
    col = wo.extract_column(ds, 40.3, -109.7)
    # theta rises with height, so crest is warmer than floor
    assert wo.delta_theta_crest_floor(col, crest_m=1900.0) > 0
    assert wo.cold_pool_heat_deficit(col, crest_m=1900.0) > 0


def test_heat_deficit_field_positive_and_consistent():
    """The vectorised field is non-negative and equals a hand-rolled single-column integral."""
    from scipy.integrate import trapezoid

    ds = make_synthetic_wrf(nz=8, ny=6, nx=6)
    crest = 1900.0
    field = wo.heat_deficit_field(ds, crest)
    assert field.shape == (6, 6)
    assert np.all(np.isfinite(field))
    assert np.all(field >= 0.0) and np.any(field > 0.0)

    # cross-check the vectorised value at its peak against the same integral computed
    # for that one column with np.interp (independent of the gather-based interpolation).
    theta = wo.potential_temperature(ds)
    z = wo.geopotential_height_mass(ds)
    p = wo.pressure_pa(ds)
    j, i = np.unravel_index(int(np.argmax(field)), field.shape)
    zc, tc, pc = z[:, j, i], theta[:, j, i], p[:, j, i]
    theta_crest = float(np.interp(crest, zc, tc))
    integrand = np.where(zc <= crest, np.clip(theta_crest - tc, 0.0, None), 0.0)
    expected = abs((wo.CP / wo.G) * trapezoid(integrand, pc))
    assert field[j, i] == pytest.approx(expected, rel=1e-6)


def test_deficit_flux_uniform_wind_equals_u_times_H():
    """With uniform winds (U=5, V=2), F = (5H, 2H) exactly — the analytic check."""
    ds = make_synthetic_wrf(nz=8, ny=6, nx=6)
    crest = 1900.0
    H = wo.heat_deficit_field(ds, crest)
    fx, fy = wo.deficit_flux_field(ds, crest)
    np.testing.assert_allclose(fx, 5.0 * H, rtol=1e-12)
    np.testing.assert_allclose(fy, 2.0 * H, rtol=1e-12)
    # grid-relative path identical here (SINALPHA == 0)
    gx, gy = wo.deficit_flux_field(ds, crest, earth_relative=False)
    np.testing.assert_allclose(gx, fx)
    np.testing.assert_allclose(gy, fy)


def test_deficit_flux_divergence_uniform_wind_is_advection_of_H():
    """Uniform wind: div(uH, vH) = u*dH/dx + v*dH/dy under the same discrete operator."""
    ds = make_synthetic_wrf(nz=8, ny=6, nx=6)
    crest = 1900.0
    H = wo.heat_deficit_field(ds, crest)
    dx, dy = wo.dx_dy(ds)
    expected = 5.0 * np.gradient(H, dx, axis=1) + 2.0 * np.gradient(H, dy, axis=0)
    div = wo.deficit_flux_divergence(ds, crest)
    np.testing.assert_allclose(div, expected, rtol=1e-9, atol=1e-6)


def test_cold_pool_depth_field():
    ds = make_synthetic_wrf(nz=4, ny=6, nx=6)
    depth = wo.cold_pool_depth_field(ds, 1900.0)
    assert depth.shape == (6, 6)
    assert np.all(depth >= 0.0)
    # column (0,0): terrain 1500 m, mass levels 1550/1650/1750/1850 m, theta 280..286 K;
    # theta_crest(1900) = 286 K -> deficit > 0 up to the 1750 m level = 250 m AGL.
    assert depth[0, 0] == pytest.approx(250.0)


def test_transect_deficit_flux_normal_convention():
    """West->east transect: the rightward normal points south, so F.n = -Fy = -2H."""
    ds = make_synthetic_wrf(nz=8, ny=6, nx=6)
    crest = 1900.0
    H = wo.heat_deficit_field(ds, crest)
    tf = wo.transect_deficit_flux(ds, crest, 40.0, -110.0, 40.0, -109.5, label="EW")
    assert tf.label == "EW"
    assert tf.dist_m[0] == 0.0 and tf.dist_m[-1] > 40_000.0  # ~0.5 deg lon at 40N
    np.testing.assert_allclose(tf.normal_en, (0.0, -1.0), atol=1e-12)
    np.testing.assert_allclose(tf.f_normal, -2.0 * H[tf.j, tf.i], rtol=1e-12)
    assert tf.total_w < 0.0  # deficit moves north (V > 0): leftward across an EW walk


def test_transect_deficit_flux_zero_length_raises():
    ds = make_synthetic_wrf()
    with pytest.raises(ValueError):
        wo.transect_deficit_flux(ds, 1900.0, 40.0, -110.0, 40.0, -110.0)


def test_discover_domains(tmp_path):
    for name in (
        "wrfout_d01_2013-02-02_12:00:00",
        "wrfout_d02_2013-02-02_12:00:00",
        "wrfout_d01_2013-02-02_13:00:00",
        "wrfout_d03_2013-02-02_12:00:00",
        "namelist.input",  # ignored
    ):
        (tmp_path / name).write_text("")
    assert wo.discover_domains(tmp_path) == [1, 2, 3]
    assert wo.discover_domains(tmp_path / "empty") == []


def test_init_time_reads_simulation_start_date(tmp_path):
    # earliest file is 13Z, but the SIMULATION_START_DATE attr (12Z) is authoritative
    ds = make_synthetic_wrf(nz=4, ny=6, nx=6)
    ds.attrs["SIMULATION_START_DATE"] = "2013-02-02_12:00:00"
    for hh in (13, 14):
        ds.to_netcdf(tmp_path / f"wrfout_d02_2013-02-02_{hh:02d}:00:00", engine="netcdf4")
    assert wo.init_time(tmp_path, 2) == datetime(2013, 2, 2, 12)


def test_init_time_falls_back_to_earliest_valid_time(tmp_path):
    ds = make_synthetic_wrf(nz=4, ny=6, nx=6)  # no SIMULATION_START_DATE attr
    for hh in (12, 13):
        ds.to_netcdf(tmp_path / f"wrfout_d01_2013-02-02_{hh:02d}:00:00", engine="netcdf4")
    assert wo.init_time(tmp_path, 1) == datetime(2013, 2, 2, 12)


def test_init_time_no_files_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        wo.init_time(tmp_path, 1)


def test_grid_spacing_label(ds):
    ds.attrs["DX"] = 3000.0
    assert wo.grid_spacing_label(ds) == "3 km"
    ds.attrs["DX"] = 1000.0
    assert wo.grid_spacing_label(ds) == "1 km"
    ds.attrs["DX"] = 333.333
    assert wo.grid_spacing_label(ds) == "333 m"


def test_point_in_domain(ds):
    # synthetic grid spans lat 40.0..40.5, lon -110.0..-109.5
    assert wo.point_in_domain(ds, 40.3, -109.7) is True
    assert wo.point_in_domain(ds, 10.0, 10.0) is False
    assert wo.point_in_domain(ds, 40.55, -109.7, pad=0.1) is True  # just outside, padded

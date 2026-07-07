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

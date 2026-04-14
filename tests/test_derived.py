"""Unit tests for brc_tools.nwp.derived."""

import numpy as np
import pytest

from brc_tools.nwp.derived import (
    pa_to_hpa,
    potential_temperature,
    relative_humidity,
    temp_K_to_C,
    theta_e,
    wind_components,
    wind_direction,
    wind_speed,
)


class TestUnitConversions:
    def test_temp_K_to_C(self):
        assert temp_K_to_C(273.15) == pytest.approx(0.0)
        assert temp_K_to_C(300.0) == pytest.approx(26.85)

    def test_pa_to_hpa(self):
        assert pa_to_hpa(101325.0) == pytest.approx(1013.25)

    def test_array_input(self):
        arr = np.array([273.15, 283.15, 293.15])
        result = temp_K_to_C(arr)
        np.testing.assert_allclose(result, [0.0, 10.0, 20.0])


class TestWind:
    def test_wind_speed_zero(self):
        assert wind_speed(0.0, 0.0) == pytest.approx(0.0)

    def test_wind_speed_345(self):
        assert wind_speed(3.0, 4.0) == pytest.approx(5.0)

    def test_wind_direction_north(self):
        # Wind FROM the north: u=0, v<0 -> dir=0 (or 360)
        d = wind_direction(0.0, -5.0)
        assert d == pytest.approx(0.0) or d == pytest.approx(360.0)

    def test_wind_direction_west(self):
        # Wind FROM the west: u>0, v=0 -> dir=270
        d = wind_direction(5.0, 0.0)
        assert d == pytest.approx(270.0)

    def test_wind_components_roundtrip(self):
        u, v = wind_components(10.0, 225.0)  # SW wind
        spd = wind_speed(u, v)
        dirn = wind_direction(u, v)
        assert spd == pytest.approx(10.0, rel=1e-6)
        assert dirn == pytest.approx(225.0, rel=1e-3)


class TestThermodynamics:
    def test_potential_temperature_surface(self):
        # At 1000 hPa, theta ~ T
        theta = potential_temperature(300.0, 1000.0)
        assert theta == pytest.approx(300.0, rel=1e-3)

    def test_potential_temperature_aloft(self):
        # At 500 hPa, 250 K -> theta should be higher
        theta = potential_temperature(250.0, 500.0)
        assert theta > 250.0

    def test_theta_e_reasonable(self):
        # Standard conditions: 20 C, dewpoint 15 C, 1013 hPa
        # Bolton (1980) gives theta_e ~ 322 K for these conditions
        te = theta_e(293.15, 288.15, 1013.0)
        assert 315.0 < te < 330.0

    def test_theta_e_dry_equals_warm(self):
        # When dewpoint = very cold (dry air), theta_e ~ theta
        te = theta_e(300.0, 220.0, 1000.0)
        theta = potential_temperature(300.0, 1000.0)
        assert te == pytest.approx(theta, rel=0.02)

    def test_relative_humidity_saturation(self):
        # At saturation: T = Td -> RH = 100%
        rh = relative_humidity(290.0, 290.0)
        assert rh == pytest.approx(100.0, rel=1e-3)

    def test_relative_humidity_subsaturated(self):
        rh = relative_humidity(300.0, 280.0)
        assert 0 < rh < 100

"""Unit tests for crosswind / headwind math and aviation payload shape."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pytest
import xarray as xr

from brc_tools.nwp.aviation import build_airport_crosswind_payload
from brc_tools.nwp.derived import KT_PER_MS, crosswind_kt, headwind_kt


class TestCrosswindMath:
    """Canonical cases for runway-relative wind decomposition.

    Wind vector (u, v) is eastward/northward in m/s; runway heading is
    degrees true (0 = N, 90 = E). Positive headwind = opposes aircraft,
    positive crosswind = from the right of the aircraft.
    """

    def test_calm_wind(self):
        assert headwind_kt(0.0, 0.0, 0) == pytest.approx(0.0)
        assert crosswind_kt(0.0, 0.0, 0) == pytest.approx(0.0)

    def test_pure_headwind_runway_360(self):
        # Aircraft landing on runway 36 (heading 0°/true north).
        # Wind FROM the north at 10 m/s -> u=0, v=-10.
        hw = headwind_kt(0.0, -10.0, 0)
        cw = crosswind_kt(0.0, -10.0, 0)
        assert hw == pytest.approx(10.0 * KT_PER_MS, rel=1e-6)
        assert cw == pytest.approx(0.0, abs=1e-9)

    def test_pure_tailwind_runway_360(self):
        # Wind FROM the south -> u=0, v=+10.
        hw = headwind_kt(0.0, 10.0, 0)
        assert hw == pytest.approx(-10.0 * KT_PER_MS, rel=1e-6)

    def test_right_crosswind_runway_360(self):
        # Aircraft heading north; wind FROM the east (right of aircraft)
        # at 10 m/s -> u=-10, v=0. Expect positive crosswind.
        cw = crosswind_kt(-10.0, 0.0, 0)
        hw = headwind_kt(-10.0, 0.0, 0)
        assert cw == pytest.approx(10.0 * KT_PER_MS, rel=1e-6)
        assert hw == pytest.approx(0.0, abs=1e-9)

    def test_left_crosswind_runway_360(self):
        # Aircraft heading north; wind FROM the west -> u=+10, v=0.
        cw = crosswind_kt(10.0, 0.0, 0)
        assert cw == pytest.approx(-10.0 * KT_PER_MS, rel=1e-6)

    def test_pure_headwind_runway_090(self):
        # Aircraft heading 090 (east). Wind FROM the east -> u=-10, v=0.
        hw = headwind_kt(-10.0, 0.0, 90)
        cw = crosswind_kt(-10.0, 0.0, 90)
        assert hw == pytest.approx(10.0 * KT_PER_MS, rel=1e-6)
        assert cw == pytest.approx(0.0, abs=1e-9)

    def test_kvel_runway_16_quartering(self):
        # KVEL runway 16 heading = 160° true. 45° right of heading = 205°.
        # Wind FROM 205° at 10 m/s (u, v from wind_components):
        #   u = -10 sin(205°), v = -10 cos(205°).
        from brc_tools.nwp.derived import wind_components

        u, v = wind_components(10.0, 205.0)
        hw = headwind_kt(u, v, 160)
        cw = crosswind_kt(u, v, 160)
        # 45° quartering headwind from the right: hw = cw = 10/sqrt(2).
        expected = 10.0 / np.sqrt(2.0) * KT_PER_MS
        assert hw == pytest.approx(expected, rel=1e-6)
        assert cw == pytest.approx(expected, rel=1e-6)

    def test_array_input(self):
        u = np.array([0.0, -10.0, 10.0])
        v = np.array([-10.0, 0.0, 0.0])
        hw = headwind_kt(u, v, 0)
        cw = crosswind_kt(u, v, 0)
        np.testing.assert_allclose(hw, np.array([10.0, 0.0, 0.0]) * KT_PER_MS, atol=1e-9)
        np.testing.assert_allclose(cw, np.array([0.0, 10.0, -10.0]) * KT_PER_MS, atol=1e-9)


class TestAviationPayload:
    """Shape-level validation of the aviation JSON payload."""

    @pytest.fixture
    def kvel_dataset(self) -> xr.Dataset:
        """Minimal synthetic HRRR grid centred on KVEL with 3 time steps."""
        lats = np.array([[40.40, 40.40, 40.40],
                         [40.44, 40.44, 40.44],
                         [40.48, 40.48, 40.48]])
        lons = np.array([[-109.55, -109.51, -109.47],
                         [-109.55, -109.51, -109.47],
                         [-109.55, -109.51, -109.47]])
        times = np.array(
            [np.datetime64("2026-04-24T12:00:00"),
             np.datetime64("2026-04-24T12:15:00"),
             np.datetime64("2026-04-24T12:30:00")]
        )
        # Constant 10 m/s southerly wind (u=0, v=+10).
        u = np.zeros((3, 3, 3), dtype=float)
        v = np.full((3, 3, 3), 10.0, dtype=float)
        ds = xr.Dataset(
            data_vars={
                "u10": (("time", "y", "x"), u),
                "v10": (("time", "y", "x"), v),
                "gust": (("time", "y", "x"), np.full((3, 3, 3), 12.0)),
            },
            coords={
                "time": times,
                "latitude": (("y", "x"), lats),
                "longitude": (("y", "x"), lons),
            },
        )
        return ds

    def test_payload_shape(self, kvel_dataset):
        init = dt.datetime(2026, 4, 24, 12, 0)
        payload = build_airport_crosswind_payload(
            kvel_dataset, airport="KVEL", init_time=init, product="subh"
        )
        assert payload["model"] == "hrrr_subh"
        assert payload["airport"] == "KVEL"
        assert payload["runway_headings_deg"] == [160, 340]
        assert payload["forecast_minutes"] == [0, 15, 30]
        assert len(payload["valid_times"]) == 3
        for key in ("wind_speed_kt", "wind_dir_deg", "gust_kt",
                    "crosswind_kt_160", "crosswind_kt_340",
                    "headwind_kt_160", "headwind_kt_340"):
            assert key in payload["variables"]
            assert key in payload["series"]
            assert len(payload["series"][key]) == 3

    def test_payload_values_southerly_wind(self, kvel_dataset):
        # u=0, v=+10: wind blows toward north, FROM south (180°).
        # Runway 160 (SSE heading) faces the wind -> positive headwind;
        # runway 340 (NNW heading) has wind from behind -> negative headwind.
        init = dt.datetime(2026, 4, 24, 12, 0)
        payload = build_airport_crosswind_payload(
            kvel_dataset, airport="KVEL", init_time=init
        )
        wind_speed = payload["series"]["wind_speed_kt"][0]
        assert wind_speed == pytest.approx(10.0 * KT_PER_MS, rel=1e-2)
        hw_340 = payload["series"]["headwind_kt_340"][0]
        hw_160 = payload["series"]["headwind_kt_160"][0]
        assert hw_160 > 0
        assert hw_340 < 0
        assert hw_340 == pytest.approx(-hw_160, rel=1e-6)

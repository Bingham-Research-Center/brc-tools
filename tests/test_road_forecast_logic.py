import datetime as dt

from brc_tools.download.get_road_forecast import build_road_payload, derive_road_fields


def test_derive_road_fields_converts_units_and_flags_precip():
    raw = {
        "temp_2m": 273.15,
        "_ugrd": 3.0,
        "_vgrd": 4.0,
        "wind_gust": 8.25,
        "visibility": 5000.0,
        "precip_1hr": 1.2,
        "_csnow": 1.0,
        "_crain": 0.0,
        "_cfrzr": 0.0,
        "_cicep": 0.0,
        "snow_depth": 0.152,
        "cloud_cover": 87.2,
        "rh_2m": 94.6,
    }

    derived = derive_road_fields(raw)

    assert derived["temp_2m"] == 0.0
    assert derived["wind_speed_10m"] == 5.0
    assert derived["wind_gust"] == 8.2
    assert derived["visibility"] == 5.0
    assert derived["precip_1hr"] == 1.2
    assert derived["precip_type"] == "snow"
    assert derived["snow_depth"] == 152.0
    assert derived["cloud_cover"] == 87.2
    assert derived["rh_2m"] == 94.6


def test_derive_road_fields_stays_explicit_about_missing_values():
    derived = derive_road_fields({"temp_2m": 280.15})

    assert derived["temp_2m"] == 7.0
    assert derived["wind_speed_10m"] is None
    assert derived["precip_type"] is None


def test_build_road_payload_preserves_hourly_shape():
    init_time = dt.datetime(2026, 3, 17, 12, tzinfo=dt.timezone.utc)
    hourly_template = [{"temp_2m": -1.0, "wind_speed_10m": 3.0}] * 3
    forecasts_by_route = {
        "us40": {0: hourly_template},
        "us191": {},
        "basin_roads": {},
    }

    payload = build_road_payload(
        init_time=init_time,
        max_fxx=3,
        forecasts_by_route=forecasts_by_route,
    )

    assert payload["model"] == "hrrr"
    assert payload["forecast_hours"] == [1, 2, 3]
    assert len(payload["valid_times"]) == 3
    assert payload["routes"]["us40"]["waypoints"][0]["forecasts"]["temp_2m"] == [
        -1.0,
        -1.0,
        -1.0,
    ]


def test_build_road_payload_emits_flat_points_for_website():
    init_time = dt.datetime(2026, 3, 17, 12, tzinfo=dt.timezone.utc)
    hourly_template = [{"temp_2m": -1.0, "wind_speed_10m": 3.0}] * 3
    forecasts_by_route = {
        "us40": {0: hourly_template},
        "us191": {},
        "basin_roads": {},
    }

    payload = build_road_payload(
        init_time=init_time,
        max_fxx=3,
        forecasts_by_route=forecasts_by_route,
    )

    points = payload["points"]
    assert len(points) == 17  # 9 + 4 + 4 across all corridors
    first = points[0]
    assert first["route_id"] == "us40"
    assert {"lat", "lon", "name", "forecasts"} <= set(first)
    assert len(first["forecasts"]) == 3
    step_zero = first["forecasts"][0]
    assert step_zero["valid_time"] == "2026-03-17T13:00:00Z"
    assert step_zero["temp_2m"] == -1.0
    assert step_zero["wind_speed_10m"] == 3.0

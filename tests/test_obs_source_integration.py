"""ObsSource.timeseries against a fake SynopticPy (no network, no token).

The fake returns SynopticPy's *long* table and the real ``.synoptic.pivot()`` turns it
wide, so these tests pin what ObsSource does with what SynopticPy actually hands back:
which variables it asks for, the alias renames, the naive-UTC ``valid_time``, the
waypoint column, sensor 1 only, and u/v built from speed + direction.
"""

from __future__ import annotations

import datetime as dt
import logging
import math

import polars as pl
import pytest

pytest.importorskip("synoptic.services")
import synoptic.services  # noqa: E402
from _nwp_fakes import OBS_VARIABLES, long_obs_frame, make_fake_timeseries  # noqa: E402

from brc_tools.nwp.source import load_lookups  # noqa: E402
from brc_tools.obs.source import ObsSource  # noqa: E402

LU = load_lookups()
GROUP = "basin_full"
T0 = dt.datetime(2026, 11, 21, 5)
TIMES = [T0 + dt.timedelta(minutes=20 * k) for k in range(4)]


def _stations(names):
    return {LU["waypoints"][n]["reference_stid"]: (LU["waypoints"][n]["lat"], LU["waypoints"][n]["lon"], 1600.0)
            for n in names}


def _install(monkeypatch, *, stations=None, values=None, drop=()):
    """Serve the requested ``vars`` for every requested station (minus ``drop``)."""

    def frame_for(*, stid, vars, **_):
        wanted = {s: v for s, v in (stations or _stations(LU["waypoint_groups"][GROUP])).items()
                  if s in stid and s not in drop}
        return long_obs_frame(wanted, TIMES, values=values,
                              variables=[v for v in vars if v in OBS_VARIABLES])

    fake = make_fake_timeseries(frame_for)
    monkeypatch.setattr(synoptic.services, "TimeSeries", fake)
    return fake


def test_asks_synoptic_for_the_stations_and_variables_behind_the_aliases(monkeypatch):
    fake = _install(monkeypatch)
    ObsSource().timeseries(waypoint_group=GROUP, start="2026-11-21 05Z", end="2026-11-21 06Z",
                           variables=["temp_2m", "mslp", "wind_speed_10m"])
    (call,) = fake.calls
    group = LU["waypoint_groups"][GROUP]
    assert call["stid"] == [LU["waypoints"][w]["reference_stid"] for w in group]
    assert call["vars"] == ["air_temp", "sea_level_pressure", "wind_speed"]
    assert call["start"] == T0.replace(tzinfo=dt.timezone.utc)
    assert call["end"] == (T0 + dt.timedelta(hours=1)).replace(tzinfo=dt.timezone.utc)
    assert call["verbose"] is False


def test_columns_are_canonical_with_naive_utc_time_and_waypoints(monkeypatch):
    _install(monkeypatch)
    df = ObsSource().timeseries(waypoint_group=GROUP, start=T0, end=TIMES[-1],
                                variables=["temp_2m", "mslp", "rh_2m"])

    assert {"stid", "valid_time", "waypoint", "temp_2m", "mslp", "rh_2m"} <= set(df.columns)
    assert not {"air_temp", "sea_level_pressure", "relative_humidity", "date_time"} & set(df.columns)
    assert df.schema["valid_time"] == pl.Datetime("us")  # tz stripped, still UTC wall time
    assert df["valid_time"].min() == T0 and df["valid_time"].max() == TIMES[-1]
    stid_to_wp = {LU["waypoints"][w]["reference_stid"]: w for w in LU["waypoint_groups"][GROUP]}
    for stid, wp in df.select("stid", "waypoint").unique().iter_rows():
        assert stid_to_wp[stid] == wp
    assert df.height == len(stid_to_wp) * len(TIMES)


def test_only_sensor_one_is_read(monkeypatch):
    """The fake's second air_temp sensor reads 100 degrees off; it must not leak in."""
    _install(monkeypatch)
    df = ObsSource().timeseries(stids=["QV4"], start=T0, end=TIMES[-1], variables=["temp_2m"])
    assert df["temp_2m"].to_list() == [OBS_VARIABLES["air_temp"][1]] * len(TIMES)


def test_explicit_stids_carry_no_waypoint_column(monkeypatch):
    _install(monkeypatch)
    df = ObsSource().timeseries(stids=["QV4", "KU69"], start=T0, end=TIMES[-1], variables=["temp_2m"])
    assert "waypoint" not in df.columns
    assert set(df["stid"]) == {"QV4", "KU69"}


@pytest.mark.parametrize("speed, direction, u, v", [
    (4.0, 270.0, 4.0, 0.0),    # westerly: blows toward the east
    (4.0, 0.0, 0.0, -4.0),     # northerly: blows toward the south
    (2.0, 135.0, -math.sqrt(2), math.sqrt(2)),  # south-easterly
    (0.0, 0.0, 0.0, 0.0),      # calm
])
def test_u_and_v_are_built_from_speed_and_direction(monkeypatch, speed, direction, u, v):
    def values(stid, lat, lon, t, var):
        return {"wind_speed": speed, "wind_direction": direction}.get(var, OBS_VARIABLES[var][1])

    fake = _install(monkeypatch, values=values)
    df = ObsSource().timeseries(stids=["QV4"], start=T0, end=TIMES[-1],
                                variables=["wind_u_10m", "wind_v_10m"])
    assert fake.calls[0]["vars"] == ["wind_direction", "wind_speed"]
    assert df["wind_u_10m"].to_list() == pytest.approx([u] * len(TIMES), abs=1e-9)
    assert df["wind_v_10m"].to_list() == pytest.approx([v] * len(TIMES), abs=1e-9)


def test_u_and_v_sit_beside_the_renamed_speed_and_direction(monkeypatch):
    _install(monkeypatch)
    df = ObsSource().timeseries(stids=["QV4"], start=T0, end=TIMES[-1],
                                variables=["wind_speed_10m", "wind_dir_10m", "wind_u_10m"])
    assert {"wind_speed_10m", "wind_dir_10m", "wind_u_10m"} <= set(df.columns)
    assert df["wind_u_10m"][0] == pytest.approx(4.0)  # 4 m/s from 270


def test_unknown_alias_is_warned_and_skipped(monkeypatch, caplog):
    _install(monkeypatch)
    with caplog.at_level(logging.WARNING, logger="brc_tools.obs.source"):
        df = ObsSource().timeseries(stids=["QV4"], start=T0, end=TIMES[-1],
                                    variables=["temp_2m", "no_such_alias"])
    assert "temp_2m" in df.columns
    assert any("no_such_alias" in r.getMessage() for r in caplog.records)


def test_a_station_synoptic_does_not_return_simply_has_no_rows(monkeypatch):
    _install(monkeypatch, drop={"QV4"})
    df = ObsSource().timeseries(waypoint_group=GROUP, start=T0, end=TIMES[-1], variables=["temp_2m"])
    assert "vernal" not in set(df["waypoint"])
    assert df["waypoint"].null_count() == 0


def test_waypoints_or_group_or_stids_is_required():
    with pytest.raises(ValueError, match="stids="):
        ObsSource().timeseries(start=T0, end=TIMES[-1], variables=["temp_2m"])

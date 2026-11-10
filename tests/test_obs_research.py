"""Offline scientific/archive and request-safety regression tests."""

import copy
import json
from datetime import datetime, timezone

import pytest
import requests

from brc_tools.obs.archive import atomic, preserve, replay
from brc_tools.obs.budget import AcquisitionStopped, Budget
from brc_tools.obs.research import fetch, long_frame


def payload():
    return {
        "SUMMARY": {"RESPONSE_CODE": 1, "RESPONSE_TIME": 2},
        "UNITS": {"air_temp": "Celsius"},
        "STATION": [
            {
                "STID": "TEST",
                "ELEVATION": "5000",
                "SENSOR_VARIABLES": {"air_temp": {"air_temp_set_1": {"position": "2"}}},
                "OBSERVATIONS": {
                    "date_time": ["2026-11-01T00:01:00Z"],
                    "air_temp_set_1": [1.23456789],
                    "air_temp_set_2": [None],
                },
                "QC": {"air_temp_set_1": [["suspect"]]},
            }
        ],
    }


def test_archive_roundtrip_and_mutation(tmp_path):
    p = payload()
    original = copy.deepcopy(p)
    path = preserve(tmp_path, p, "timeseries", {}, {})
    p["STATION"].clear()
    restored, _ = replay(path)
    original["SUMMARY"].pop("RESPONSE_TIME")
    assert restored == original
    df = long_frame(restored)
    assert df.height == 2 and df["value"][0] == 1.23456789
    assert "suspect" in df["qc"][0] and df["value"][1] is None
    obj = next((tmp_path / "objects").glob("*"))
    obj.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="digest"):
        replay(path)


def test_no_overwrite(tmp_path):
    atomic(tmp_path / "a", b"a")
    atomic(tmp_path / "a", b"a")
    with pytest.raises(ValueError):
        atomic(tmp_path / "a", b"b")
    assert (tmp_path / "a").read_bytes() == b"a"


def test_redaction(tmp_path):
    p = payload()
    p["token"] = "secret"
    p["url"] = "https://test/?token=secret&x=1"
    path = preserve(tmp_path, p, "metadata", {"api_key": "secret"}, {})
    restored, receipt = replay(path)
    assert "secret" not in json.dumps([restored, receipt])


def test_timezone_and_malformed():
    p = payload()
    p["STATION"][0]["OBSERVATIONS"]["date_time"] = ["2026-11-01T01:01:00+01:00"]
    assert long_frame(p)["time"][0] == datetime(2026, 11, 1, 0, 1, tzinfo=timezone.utc)
    p["STATION"][0]["OBSERVATIONS"]["air_temp_set_1"].append(3)
    with pytest.raises(ValueError):
        long_frame(p)


def test_no_network_without_confirmation(tmp_path):
    with pytest.raises(AcquisitionStopped):
        with Budget(tmp_path, "synoptic", "x").transport():
            pytest.fail("entered")


def test_transport_counts_import_like_calls_stops_and_resumes(tmp_path, monkeypatch):
    calls = []
    now = [100.0]

    def send(self, req, **kw):
        calls.append(kw)
        r = requests.Response()
        r.status_code = 200
        r._content = b'{"SUMMARY":{"RESPONSE_CODE":1}}'
        return r

    monkeypatch.setattr(requests.sessions.Session, "send", send)

    def sleep(t):
        now[0] += t

    b = Budget(
        tmp_path,
        "synoptic",
        "batch",
        allowed=True,
        max_requests=2,
        clock=lambda: now[0],
        sleep=sleep,
    )
    for _ in range(2):
        with b.transport():
            requests.get("https://api.synopticdata.com/v2/stations/metadata")
    with pytest.raises(AcquisitionStopped, match="budget"):
        with b.transport():
            requests.get("https://api.synopticdata.com/v2/stations/metadata")
    assert len(calls) == 2 and now[0] == 130 and calls[0]["timeout"] == (10, 60)


@pytest.mark.parametrize(
    "status,body",
    [
        (429, {}),
        (200, {"SUMMARY": {"RESPONSE_CODE": 2, "HTTP_STATUS_CODE": 429}}),
        (403, {}),
    ],
)
def test_quota_breaker(tmp_path, monkeypatch, status, body):
    def send(*a, **kw):
        r = requests.Response()
        r.status_code = status
        r._content = json.dumps(body).encode()
        return r

    monkeypatch.setattr(requests.sessions.Session, "send", send)
    b = Budget(tmp_path, "synoptic", "batch", allowed=True)
    with pytest.raises(AcquisitionStopped):
        with b.transport():
            requests.get("https://api.synopticdata.com/v2/stations/metadata")
    with pytest.raises(AcquisitionStopped, match="stopped"):
        with b.transport():
            pytest.fail("must not enter")


def test_replay_needs_no_token_or_network(tmp_path):
    from brc_tools.obs.archive import digest, encode

    params = {
        "stid": ["TEST"],
        "vars": ["air_temp"],
        "start": "2026-11-01T00:00:00+00:00",
        "end": "2026-11-02T00:00:00+00:00",
    }
    path = preserve(tmp_path, payload(), "timeseries", params, {})
    key = digest(encode(dict(service="timeseries", params=params, version=1)))
    atomic(
        tmp_path / "requests" / f"{key}.json",
        encode({"receipt": str(path.relative_to(tmp_path))}),
    )
    assert fetch("timeseries", params, archive=tmp_path, budget=None).frame.height == 2


def test_units_are_declared_not_guessed():
    from brc_tools.obs.units import convert

    assert convert(1000, "hPa")[:2] == (100000, "Pa")
    assert convert(1000, "Pa")[:2] == (1000, "Pa")
    assert convert(32, "Fahrenheit")[0] == pytest.approx(0)
    assert convert(20, "knots")[0] == pytest.approx(10.2888889)
    assert convert(1, "inches")[0] == 0.0254
    assert convert(90000, None)[2] == "unknown_unit"


def test_metadata_conversion_preserves_originals():
    from brc_tools.obs.research import metadata_frame

    p = payload()
    f = metadata_frame(p)
    assert f["elevation_m"][0] == 1524.0
    assert f["elevation_dem_m"][0] is None
    assert json.loads(f["metadata"][0])["ELEVATION"] == "5000"


def test_timeout_and_concurrent_worker(tmp_path, monkeypatch):
    def timeout(*a, **kw):
        raise requests.Timeout("secret token=do-not-print")

    monkeypatch.setattr(requests.sessions.Session, "send", timeout)
    b = Budget(tmp_path, "synoptic", "x", allowed=True)
    with b.transport():
        with pytest.raises(AcquisitionStopped, match="another"):
            with Budget(tmp_path, "synoptic", "y", allowed=True).transport():
                pass
        with pytest.raises(AcquisitionStopped) as e:
            requests.get("https://api.synopticdata.com/v2/stations/metadata")
        assert "do-not-print" not in str(e.value)
    with pytest.raises(AcquisitionStopped):
        b.acknowledge_redirect("not a redirect")


def test_cached_igra_archive_needs_no_budget(tmp_path):
    from brc_tools.api.soundings.archive import station_archive
    from brc_tools.obs.archive import digest, encode

    data = b"cached bytes"
    name = digest(data) + ".zip"
    atomic(tmp_path / name, data)
    receipt = tmp_path / "USM00072476-2026.json"
    atomic(receipt, encode(dict(file=name, sha256=digest(data))))
    assert station_archive("KGJT", root=tmp_path, budget=None, year=2026) == receipt
    (tmp_path / name).write_bytes(b"changed")
    with pytest.raises(ValueError, match="digest"):
        station_archive("KGJT", root=tmp_path, budget=None, year=2026)


def test_legacy_facade_remains_wide_without_live_import(monkeypatch):
    import sys
    import types

    import polars as pl

    from brc_tools.obs.source import ObsSource

    calls = []

    def request(**kwargs):
        calls.append(kwargs)
        frame = pl.DataFrame(
            {
                "stid": ["KVEL"],
                "date_time": [datetime(2026, 11, 1, tzinfo=timezone.utc)],
                "air_temp": [2.0],
            }
        )
        return types.SimpleNamespace(
            df=lambda: types.SimpleNamespace(
                synoptic=types.SimpleNamespace(pivot=lambda: frame)
            )
        )

    monkeypatch.setitem(
        sys.modules, "synoptic.services", types.SimpleNamespace(TimeSeries=request)
    )
    frame = ObsSource().timeseries(
        stids=["KVEL"],
        start="2026-11-01 00Z",
        end="2026-11-01 01Z",
        variables=["temp_2m"],
    )
    assert frame.height == 1 and "valid_time" in frame.columns
    assert "air_temp" in calls[0]["vars"]
    assert "temp_2m" in frame.columns or "temperature_2m" in frame.columns

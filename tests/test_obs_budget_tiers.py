"""Budget tiers: the pilot default is unchanged; the historical tier adds a batch cap of
60 and a rolling 24 h cap of 300; a 'no data' probe can be acknowledged, a quota stop
cannot."""

import json

import pytest
import requests

from brc_tools.obs.budget import TIERS, AcquisitionStopped, Budget

URL = "https://api.synopticdata.com/v2/stations/timeseries"


def _responder(monkeypatch, status=200, body=None, calls=None):
    body = body if body is not None else {"SUMMARY": {"RESPONSE_CODE": 1}}

    def send(self, req, **kw):
        if calls is not None:
            calls.append(req.url)
        r = requests.Response()
        r.status_code = status
        r._content = json.dumps(body).encode()
        return r

    monkeypatch.setattr(requests.sessions.Session, "send", send)


def _budget(root, tier, now, **kw):
    def sleep(t):
        now[0] += t

    return Budget(root, "synoptic", kw.pop("batch", "b1"), allowed=True, tier=tier,
                  clock=lambda: now[0], sleep=sleep, **kw)


def test_pilot_default_is_unchanged(tmp_path, monkeypatch):
    _responder(monkeypatch)
    now = [1000.0]
    b = _budget(tmp_path, "pilot", now)
    assert b.maximum == 8 and b.rolling_cap is None
    for _ in range(8):
        with b.transport():
            requests.get(URL)
    with pytest.raises(AcquisitionStopped, match="budget exhausted"):
        with b.transport():
            requests.get(URL)
    with pytest.raises(ValueError):
        Budget(tmp_path, "synoptic", "x", max_requests=9)  # pilot still caps at 8


def test_unknown_tier_and_over_tier_requests_refused(tmp_path):
    with pytest.raises(ValueError, match="unknown budget tier"):
        Budget(tmp_path, "synoptic", "x", tier="unlimited")
    with pytest.raises(ValueError):
        Budget(tmp_path, "synoptic", "x", tier="historical", max_requests=61)
    with pytest.raises(ValueError):
        Budget(tmp_path, "synoptic", "x", tier="historical", interval=10)


def test_historical_tier_allows_sixty_then_stops(tmp_path, monkeypatch):
    calls = []
    _responder(monkeypatch, calls=calls)
    now = [1000.0]
    b = _budget(tmp_path, "historical", now)
    assert b.maximum == TIERS["historical"]["max_requests"] == 60
    for _ in range(60):
        with b.transport():
            requests.get(URL)
    with pytest.raises(AcquisitionStopped, match="budget exhausted"):
        with b.transport():
            requests.get(URL)
    assert len(calls) == 60
    state = json.loads((tmp_path / "synoptic.json").read_text())
    assert all(e["tier"] == "historical" for e in state["batches"]["b1"])
    # spacing: 59 waits of 30 s between 60 requests
    assert now[0] - 1000.0 == pytest.approx(59 * 30.0)


def test_rolling_window_counts_every_batch_and_frees_with_time(tmp_path, monkeypatch):
    _responder(monkeypatch)
    now = [100000.0]
    # pre-seed 300 requests in other batches, 299 inside the window and 1 just outside
    entries_recent = [{"utc_epoch": now[0] - 3600.0 * 23, "path": "/x", "outcome": "success"} for _ in range(299)]
    entries_old = [{"utc_epoch": now[0] - 3600.0 * 25, "path": "/x", "outcome": "success"}]
    (tmp_path / "synoptic.json").write_text(json.dumps({"batches": {"old1": entries_recent, "old2": entries_old}, "last": 0}))
    b = _budget(tmp_path, "historical", now, batch="new")
    left_batch, left_window, wait = b.headroom()
    assert (left_batch, left_window, wait) == (60, 1, 0.0)
    with b.transport():
        requests.get(URL)  # the 300th in the window
    left_batch, left_window, wait = b.headroom()
    assert left_window == 0 and wait > 0
    with pytest.raises(AcquisitionStopped, match="rolling 24 h"):
        with b.transport():
            requests.get(URL)
    # the stop was raised before a request was recorded, so the ledger is not 'stopped'
    state = json.loads((tmp_path / "synoptic.json").read_text())
    assert state["stopped"] is None and len(state["batches"]["new"]) == 1
    now[0] += 3600.0 * 1.5  # the 299 entries at -23 h are now -24.5 h: window frees
    assert b.headroom()[1] == 299
    with b.transport():
        requests.get(URL)


def test_acknowledge_empty_probe_only_for_no_data(tmp_path, monkeypatch):
    now = [5000.0]
    # A 'no data' answer: HTTP 200, RESPONSE_CODE 2, benign message
    _responder(monkeypatch, 200, {"SUMMARY": {"RESPONSE_CODE": 2, "RESPONSE_MESSAGE": "No stations found for this request."}})
    b = _budget(tmp_path, "historical", now)
    with pytest.raises(AcquisitionStopped):
        with b.transport():
            requests.get(URL)
    with pytest.raises(AcquisitionStopped, match="stopped"):
        with b.transport():
            pytest.fail("must not enter")
    with pytest.raises(ValueError):
        b.acknowledge_empty_probe("   ")
    b.acknowledge_empty_probe("probe into 2015: token covers one year")
    state = json.loads((tmp_path / "synoptic.json").read_text())
    assert state["stopped"] is None and state["reviews"][0]["kind"] == "empty_probe"
    assert "secret" not in json.dumps(state)
    # A quota answer cannot be acknowledged this way
    _responder(monkeypatch, 200, {"SUMMARY": {"RESPONSE_CODE": 2, "RESPONSE_MESSAGE": "Quota exceeded for this token"}})
    with pytest.raises(AcquisitionStopped):
        with b.transport():
            requests.get(URL)
    with pytest.raises(AcquisitionStopped, match="no data"):
        b.acknowledge_empty_probe("trying anyway")
    # Nor a 403
    _responder(monkeypatch, 403, {})
    b2 = _budget(tmp_path, "historical", now, batch="b2")
    with pytest.raises(AcquisitionStopped):
        with b2.transport():
            requests.get(URL)
    with pytest.raises(AcquisitionStopped):
        b2.acknowledge_empty_probe("still trying")

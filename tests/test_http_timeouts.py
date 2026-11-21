"""brc_tools.nwp._http: no requests call made on our behalf can wait forever.

The 18-19 Nov 2026 hangs were one TLS connection to S3 that opened and then never
answered, while Herbie's ``requests.get(self.idx)`` passed no timeout. The first
test rebuilds that: a local server accepts the connection and sends nothing.
"""
from __future__ import annotations

import datetime as dt
import socket
import threading
import time

import pytest
import requests

from brc_tools.nwp import _http


@pytest.fixture(autouse=True)
def _restore_requests():
    _http._uninstall()
    yield
    _http._uninstall()


@pytest.fixture
def silent_server():
    """A TCP server that accepts connections and never sends a byte."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(4)
    held, stop = [], threading.Event()

    def accept():
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
                held.append(conn)          # keep it open, say nothing
            except OSError:
                continue

    t = threading.Thread(target=accept, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.getsockname()[1]}/hrrr.t12z.wrfsfcf00.grib2.idx"
    stop.set()
    t.join(timeout=2)
    for c in held:
        c.close()
    srv.close()


def test_a_silent_server_now_times_out_instead_of_hanging(silent_server):
    _http.ensure_request_timeouts((2.0, 0.5))
    t0 = time.monotonic()
    with pytest.raises(requests.exceptions.ReadTimeout):
        requests.get(silent_server)          # what Herbie does for every index
    assert time.monotonic() - t0 < 5


def test_head_is_covered_too(silent_server):
    _http.ensure_request_timeouts((2.0, 0.5))
    with pytest.raises(requests.exceptions.ReadTimeout):
        requests.head(silent_server)         # Herbie's file-exists check


class _Sent(Exception):
    pass


@pytest.fixture
def captured(monkeypatch):
    """Record the timeout each request is sent with, then stop before the network."""
    seen = []

    def send(self, request, **kwargs):
        seen.append(kwargs.get("timeout"))
        raise _Sent

    monkeypatch.setattr(requests.sessions.Session, "send", send)
    return seen


def _call(fn, *args, **kwargs):
    with pytest.raises(_Sent):
        fn(*args, **kwargs)


def test_no_timeout_gets_the_default(captured):
    _http.ensure_request_timeouts()
    _call(requests.get, "http://example.invalid/a.idx")
    assert captured == [_http.DEFAULT_TIMEOUT]


def test_explicit_none_also_gets_the_default(captured):
    _http.ensure_request_timeouts()
    _call(requests.get, "http://example.invalid/a.idx", timeout=None)
    assert captured == [_http.DEFAULT_TIMEOUT]


def test_an_explicit_timeout_is_kept(captured):
    _http.ensure_request_timeouts()
    _call(requests.get, "http://example.invalid/a.idx", timeout=30)
    _call(requests.Session().request, "GET", "http://example.invalid/b.idx", timeout=(3, 9))
    assert captured == [30, (3, 9)]


def test_installing_twice_wraps_once_and_updates_the_default(captured):
    _http.ensure_request_timeouts((1, 2))
    wrapped = requests.sessions.Session.request
    _http.ensure_request_timeouts((5, 6))
    assert requests.sessions.Session.request is wrapped
    _call(requests.get, "http://example.invalid/a.idx")
    assert captured == [(5, 6)]


def test_without_it_requests_is_unchanged(captured):
    _call(requests.get, "http://example.invalid/a.idx")
    assert captured == [None]


def test_nwpsource_fetch_installs_it(monkeypatch, tmp_path):
    from _nwp_fakes import lambert_grid, make_fake_herbie
    from brc_tools.nwp import source

    monkeypatch.setenv("BRC_TOOLS_LOCK_DIR", str(tmp_path))
    monkeypatch.delenv("BRC_TOOLS_HERBIE_CACHE", raising=False)
    monkeypatch.setattr(source, "Herbie", make_fake_herbie(lambert_grid()))
    assert _http._ORIGINAL_REQUEST is None
    source.NWPSource("hrrr").fetch("2026-11-21 05Z", [0], ["temp_2m"])
    assert _http._ORIGINAL_REQUEST is not None


def test_setup_herbie_installs_it(monkeypatch):
    from brc_tools.download import hrrr_access

    monkeypatch.setattr(hrrr_access, "Herbie", lambda *a, **k: object())
    assert _http._ORIGINAL_REQUEST is None
    hrrr_access.setup_herbie(dt.datetime(2026, 11, 21, 5), 1)
    assert _http._ORIGINAL_REQUEST is not None

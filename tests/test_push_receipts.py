"""Receipts, timestamps, retries and the post-upload visibility check in push_data.

These mock requests.get/post/head directly (not _post_json_to_url, as
test_push_data.py does) because the behaviour under test lives inside it.
"""
import json
import re
from unittest import mock

import pytest
import requests

from brc_tools.download import push_data

VALID_KEY = "a" * 40
STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z ")


def _resp(status=200, text="", payload=None):
    r = mock.Mock(status_code=status, text=text)
    r.json = mock.Mock(return_value=payload if payload is not None else {})
    return r


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """No test waits for a real retry pause; each starts with no exhausted host."""
    monkeypatch.delenv(push_data.UPLOAD_ATTEMPTS_ENV, raising=False)
    push_data._EXHAUSTED_HOSTS.clear()
    sleep = mock.Mock()
    monkeypatch.setattr(push_data.time, "sleep", sleep)
    yield sleep
    push_data._EXHAUSTED_HOSTS.clear()


@pytest.fixture
def receipts(tmp_path, monkeypatch):
    path = tmp_path / "receipts.jsonl"
    monkeypatch.setenv(push_data.RECEIPTS_ENV, str(path))
    monkeypatch.delenv("BASINWX_VERIFY_UPLOADS", raising=False)
    return path


@pytest.fixture
def one_file(tmp_path):
    f = tmp_path / "map_obs_20260924_0440Z.json"
    f.write_text("{}")
    return str(f)


def _lines(path):
    return [json.loads(l) for l in path.read_text().splitlines()]


class TestReceipts:
    def test_success_is_receipted_and_verified(self, receipts, one_file, capsys):
        served = "/api/static/observations/map_obs_20260924_0440Z.json"
        with mock.patch.object(push_data.requests, "get", return_value=_resp(200)), \
             mock.patch.object(push_data.requests, "post", return_value=_resp(200, payload={"path": served})), \
             mock.patch.object(push_data.requests, "head", return_value=_resp(200)) as head:
            assert push_data._post_json_to_url("https://a", one_file, "observations", VALID_KEY) is True

        head.assert_called_once_with("https://a" + served, timeout=10)
        (r,) = _lines(receipts)
        assert r == {
            "ts": r["ts"], "role": "PRIMARY", "url": "https://a", "data_type": "observations",
            "file": "map_obs_20260924_0440Z.json", "stage": "upload", "ok": True,
            "status": 200, "verified": True, "elapsed_ms": r["elapsed_ms"], "attempt": 1,
        }
        assert STAMP.match(r["ts"] + " ")
        assert isinstance(r["elapsed_ms"], int)
        assert "✅ uploaded" in capsys.readouterr().out

    def test_rejected_upload_keeps_the_server_reason(self, receipts, one_file):
        with mock.patch.object(push_data.requests, "get", return_value=_resp(200)), \
             mock.patch.object(push_data.requests, "post", return_value=_resp(413, text="<html>413 Request Entity Too Large")):
            assert push_data._post_json_to_url("https://b", one_file, "forecasts", VALID_KEY, role="MIRROR") is False
        (r,) = _lines(receipts)
        assert r["ok"] is False and r["status"] == 413 and r["role"] == "MIRROR"
        assert "413" in r["error"] and "verified" not in r

    def test_health_failure_is_its_own_stage(self, receipts, one_file, monkeypatch):
        monkeypatch.setenv(push_data.UPLOAD_ATTEMPTS_ENV, "1")
        with mock.patch.object(push_data.requests, "get", side_effect=requests.exceptions.ConnectionError("NameResolutionError: boom")):
            assert push_data._post_json_to_url("https://a", one_file, "observations", VALID_KEY) is False
        (r,) = _lines(receipts)
        assert r["stage"] == "health" and r["ok"] is False and r["status"] is None
        assert "NameResolutionError" in r["error"]

    def test_timeout_is_receipted(self, receipts, one_file, monkeypatch):
        monkeypatch.setenv(push_data.UPLOAD_ATTEMPTS_ENV, "1")
        with mock.patch.object(push_data.requests, "get", return_value=_resp(200)), \
             mock.patch.object(push_data.requests, "post", side_effect=requests.exceptions.Timeout()):
            assert push_data._post_json_to_url("https://a", one_file, "observations", VALID_KEY) is False
        (r,) = _lines(receipts)
        assert r["error"] == "timeout after 30s"

    def test_invisible_after_200_warns_but_still_counts_as_sent(self, receipts, one_file, capsys):
        with mock.patch.object(push_data.requests, "get", return_value=_resp(200)), \
             mock.patch.object(push_data.requests, "post", return_value=_resp(200, payload={"path": "/api/static/x/y.json"})), \
             mock.patch.object(push_data.requests, "head", return_value=_resp(404)):
            assert push_data._post_json_to_url("https://a", one_file, "x", VALID_KEY) is True
        assert _lines(receipts)[0]["verified"] is False
        assert "not visible" in capsys.readouterr().out

    def test_verification_can_be_switched_off(self, receipts, one_file, monkeypatch):
        monkeypatch.setenv("BASINWX_VERIFY_UPLOADS", "0")
        with mock.patch.object(push_data.requests, "get", return_value=_resp(200)), \
             mock.patch.object(push_data.requests, "post", return_value=_resp(200, payload={"path": "/p"})), \
             mock.patch.object(push_data.requests, "head") as head:
            assert push_data._post_json_to_url("https://a", one_file, "x", VALID_KEY) is True
        head.assert_not_called()
        assert _lines(receipts)[0]["verified"] is None

    def test_no_path_in_response_skips_verification(self, receipts, one_file):
        with mock.patch.object(push_data.requests, "get", return_value=_resp(200)), \
             mock.patch.object(push_data.requests, "post", return_value=_resp(200, payload={})), \
             mock.patch.object(push_data.requests, "head") as head:
            assert push_data._post_json_to_url("https://a", one_file, "x", VALID_KEY) is True
        head.assert_not_called()

    def test_unwritable_receipt_path_never_breaks_the_upload(self, tmp_path, one_file, monkeypatch, capsys):
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("")
        monkeypatch.setenv(push_data.RECEIPTS_ENV, str(blocker / "receipts.jsonl"))
        with mock.patch.object(push_data.requests, "get", return_value=_resp(200)), \
             mock.patch.object(push_data.requests, "post", return_value=_resp(200, payload={})):
            assert push_data._post_json_to_url("https://a", one_file, "x", VALID_KEY) is True
        assert "receipt not written" in capsys.readouterr().err

    def test_empty_env_disables_receipts(self, tmp_path, one_file, monkeypatch):
        monkeypatch.setenv(push_data.RECEIPTS_ENV, "")
        with mock.patch.object(push_data.requests, "get", return_value=_resp(200)), \
             mock.patch.object(push_data.requests, "post", return_value=_resp(200, payload={})):
            assert push_data._post_json_to_url("https://a", one_file, "x", VALID_KEY) is True
        assert not list(tmp_path.iterdir()) or all(p.name != "receipts.jsonl" for p in tmp_path.iterdir())


class TestTimestamps:
    def test_every_upload_line_starts_with_a_utc_stamp(self, receipts, one_file, capsys):
        with mock.patch.object(push_data.requests, "get", return_value=_resp(200)), \
             mock.patch.object(push_data.requests, "post", return_value=_resp(500, text="boom")):
            push_data._post_json_to_url("https://a", one_file, "x", VALID_KEY)
        out = [l for l in capsys.readouterr().out.splitlines() if l]
        assert len(out) >= 3
        assert all(STAMP.match(l) for l in out), out

    def test_bundle_alert_is_stamped_on_stderr(self, receipts, one_file, capsys):
        def fake(url, fpath, file_data, api_key, *, role="PRIMARY"):
            return role == "PRIMARY"
        with mock.patch.object(push_data, "_post_json_to_url", side_effect=fake):
            push_data.send_bundle_to_all(["https://p", "https://m"], [one_file], "x", VALID_KEY)
        err = capsys.readouterr().err
        assert push_data.FanoutSession.ALERT in err
        assert STAMP.match(err.splitlines()[-1])


DNS = requests.exceptions.ConnectionError(
    "HTTPSConnectionPool(host='basinwx.dev', port=443): Max retries exceeded with url: "
    "/api/health (Caused by NameResolutionError(\"Failed to resolve 'basinwx.dev' "
    "([Errno -2] Name or service not known)\"))")


class TestRetries:
    """A transient failure is tried again; a refusal is not (website ask P25)."""

    def test_one_failed_dns_lookup_no_longer_loses_the_file(self, receipts, one_file, no_sleep, capsys):
        # The shape of every one-host miss from 2026-09-28 to 2026-11-21.
        with mock.patch.object(push_data.requests, "get", side_effect=[DNS, _resp(200)]), \
             mock.patch.object(push_data.requests, "post", return_value=_resp(200, payload={})):
            assert push_data._post_json_to_url("https://basinwx.dev", one_file, "observations", VALID_KEY, role="MIRROR") is True
        first, second = _lines(receipts)
        assert (first["attempt"], first["stage"], first["ok"]) == (1, "health", False)
        assert (second["attempt"], second["stage"], second["ok"]) == (2, "upload", True)
        no_sleep.assert_called_once_with(push_data.RETRY_DELAYS_S[0])
        out = capsys.readouterr().out
        assert "retrying map_obs_20260924_0440Z.json in 5s (attempt 2 of 3)" in out
        assert "✅ uploaded map_obs_20260924_0440Z.json (attempt 2 of 3)" in out

    def test_gives_up_after_the_last_attempt(self, receipts, one_file, no_sleep, capsys):
        with mock.patch.object(push_data.requests, "get", side_effect=DNS) as get:
            assert push_data._post_json_to_url("https://a", one_file, "x", VALID_KEY) is False
        assert get.call_count == push_data.DEFAULT_UPLOAD_ATTEMPTS == 3
        assert [r["attempt"] for r in _lines(receipts)] == [1, 2, 3]
        assert [c.args[0] for c in no_sleep.call_args_list] == [5, 20]
        assert "gave up on map_obs_20260924_0440Z.json after 3 attempts" in capsys.readouterr().out
        assert "https://a" in push_data._EXHAUSTED_HOSTS

    def test_an_exhausted_host_gets_one_attempt_per_later_file(self, receipts, one_file, no_sleep):
        with mock.patch.object(push_data.requests, "get", side_effect=DNS) as get:
            push_data._post_json_to_url("https://a", one_file, "x", VALID_KEY)
            get.reset_mock(); no_sleep.reset_mock()
            assert push_data._post_json_to_url("https://a", one_file, "x", VALID_KEY) is False
        assert get.call_count == 1
        no_sleep.assert_not_called()

    def test_a_success_clears_the_exhausted_mark(self, receipts, one_file):
        push_data._EXHAUSTED_HOSTS.add("https://a")
        with mock.patch.object(push_data.requests, "get", return_value=_resp(200)), \
             mock.patch.object(push_data.requests, "post", return_value=_resp(200, payload={})):
            assert push_data._post_json_to_url("https://a", one_file, "x", VALID_KEY) is True
        assert "https://a" not in push_data._EXHAUSTED_HOSTS

    def test_the_mark_is_per_host(self, receipts, one_file):
        push_data._EXHAUSTED_HOSTS.add("https://a")
        with mock.patch.object(push_data.requests, "get", side_effect=DNS) as get:
            push_data._post_json_to_url("https://b", one_file, "x", VALID_KEY)
        assert get.call_count == 3

    @pytest.mark.parametrize("status", [502, 503, 504])
    def test_a_gateway_status_is_tried_again(self, receipts, one_file, status):
        with mock.patch.object(push_data.requests, "get", return_value=_resp(200)), \
             mock.patch.object(push_data.requests, "post", side_effect=[_resp(status, text="bad gateway"), _resp(200, payload={})]):
            assert push_data._post_json_to_url("https://a", one_file, "x", VALID_KEY) is True
        assert [(r["status"], r["attempt"]) for r in _lines(receipts)] == [(status, 1), (200, 2)]

    @pytest.mark.parametrize("status", [400, 401, 403, 413, 500])
    def test_a_refusal_is_final(self, receipts, one_file, no_sleep, status):
        with mock.patch.object(push_data.requests, "get", return_value=_resp(200)), \
             mock.patch.object(push_data.requests, "post", return_value=_resp(status, text="no")) as post:
            assert push_data._post_json_to_url("https://a", one_file, "x", VALID_KEY) is False
        assert post.call_count == 1
        no_sleep.assert_not_called()
        assert "https://a" not in push_data._EXHAUSTED_HOSTS

    def test_an_upload_timeout_is_tried_again(self, receipts, one_file):
        with mock.patch.object(push_data.requests, "get", return_value=_resp(200)), \
             mock.patch.object(push_data.requests, "post", side_effect=[requests.exceptions.Timeout(), _resp(200, payload={})]):
            assert push_data._post_json_to_url("https://a", one_file, "x", VALID_KEY) is True

    def test_a_tls_failure_is_not_tried_again(self, receipts, one_file, no_sleep):
        with mock.patch.object(push_data.requests, "get", side_effect=requests.exceptions.SSLError("certificate verify failed")) as get:
            assert push_data._post_json_to_url("https://a", one_file, "x", VALID_KEY) is False
        assert get.call_count == 1
        no_sleep.assert_not_called()

    @pytest.mark.parametrize("raw, expected", [("1", 1), ("5", 5), ("0", 1), ("-2", 1), ("lots", 3), ("", 3)])
    def test_attempts_come_from_the_environment(self, monkeypatch, raw, expected):
        monkeypatch.setenv(push_data.UPLOAD_ATTEMPTS_ENV, raw)
        assert push_data._upload_attempts() == expected

    def test_fanout_primary_survives_one_dns_failure(self, receipts, one_file):
        with mock.patch.object(push_data.requests, "get", side_effect=[DNS, _resp(200), _resp(200)]), \
             mock.patch.object(push_data.requests, "post", return_value=_resp(200, payload={})):
            results = push_data.send_json_to_all(["https://p", "https://m"], one_file, "x", VALID_KEY)
        assert results == {"https://p": True, "https://m": True}

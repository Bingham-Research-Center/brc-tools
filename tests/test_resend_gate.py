"""The station-metadata resend gate (BasinWX ask R1)."""

import json

from brc_tools.download.resend_gate import is_due, record_sent

SIX_HOURS = 6 * 3600


def _write(path, text):
    path.write_text(text)
    return path


def test_due_without_state(tmp_path):
    f = _write(tmp_path / "meta.json", '[{"stid": "KVEL"}]')
    assert is_due(f, tmp_path / "state.json", max_age_seconds=SIX_HOURS, now=1000.0)


def test_same_content_inside_window_is_not_due(tmp_path):
    f = _write(tmp_path / "meta.json", '[{"stid": "KVEL"}]')
    state = tmp_path / "state.json"
    record_sent(f, state, now=1000.0)
    assert not is_due(f, state, max_age_seconds=SIX_HOURS, now=1000.0 + SIX_HOURS - 1)


def test_same_content_is_due_again_after_window(tmp_path):
    f = _write(tmp_path / "meta.json", '[{"stid": "KVEL"}]')
    state = tmp_path / "state.json"
    record_sent(f, state, now=1000.0)
    assert is_due(f, state, max_age_seconds=SIX_HOURS, now=1000.0 + SIX_HOURS)


def test_changed_content_is_due_at_once(tmp_path):
    state = tmp_path / "state.json"
    record_sent(_write(tmp_path / "a.json", '[{"stid": "KVEL"}]'), state, now=1000.0)
    b = _write(tmp_path / "b.json", '[{"stid": "KVEL"}, {"stid": "KU69"}]')
    assert is_due(b, state, max_age_seconds=SIX_HOURS, now=1001.0)


def test_unreadable_state_means_due(tmp_path):
    f = _write(tmp_path / "meta.json", "[]")
    for bad in ("", "not json", json.dumps({"sha256": "x"}), json.dumps([1, 2])):
        state = _write(tmp_path / "state.json", bad)
        assert is_due(f, state, max_age_seconds=SIX_HOURS, now=1000.0), bad


def test_record_sent_writes_state_atomically(tmp_path):
    f = _write(tmp_path / "meta.json", "[]")
    state = tmp_path / "sub" / "state.json"
    record_sent(f, state, now=42.0)
    saved = json.loads(state.read_text())
    assert saved["sent_at"] == 42.0 and saved["file"] == "meta.json"
    assert [p.name for p in state.parent.iterdir()] == ["state.json"]

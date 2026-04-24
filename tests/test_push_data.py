"""Tests for load_config_urls and send_json_to_all fan-out semantics."""

import os
from unittest import mock

import pytest

from brc_tools.download import push_data


VALID_KEY = "a" * 32


@pytest.fixture
def env_clear(monkeypatch):
    monkeypatch.delenv("BASINWX_API_URLS", raising=False)
    monkeypatch.setenv("DATA_UPLOAD_API_KEY", VALID_KEY)
    return monkeypatch


class TestLoadConfigUrls:
    def test_env_var_wins(self, env_clear, tmp_path, monkeypatch):
        env_clear.setenv("BASINWX_API_URLS", "https://a.example, https://b.example/")
        monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path) if p == "~" else p)
        api_key, urls = push_data.load_config_urls()
        assert api_key == VALID_KEY
        assert urls == ["https://a.example", "https://b.example"]

    def test_plural_file_falls_back(self, env_clear, tmp_path, monkeypatch):
        config_dir = tmp_path / ".config" / "ubair-website"
        config_dir.mkdir(parents=True)
        (config_dir / "website_urls").write_text("https://one.example,https://two.example\n")
        monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path) if p == "~" else p)
        api_key, urls = push_data.load_config_urls()
        assert urls == ["https://one.example", "https://two.example"]

    def test_singular_file_back_compat(self, env_clear, tmp_path, monkeypatch):
        config_dir = tmp_path / ".config" / "ubair-website"
        config_dir.mkdir(parents=True)
        (config_dir / "website_url").write_text("https://only.example\n")
        monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path) if p == "~" else p)
        api_key, urls = push_data.load_config_urls()
        assert urls == ["https://only.example"]

    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("DATA_UPLOAD_API_KEY", raising=False)
        with pytest.raises(ValueError, match="DATA_UPLOAD_API_KEY"):
            push_data.load_config_urls()

    def test_wrong_length_key_raises(self, monkeypatch):
        monkeypatch.setenv("DATA_UPLOAD_API_KEY", "short")
        with pytest.raises(ValueError, match="32 characters"):
            push_data.load_config_urls()

    def test_no_source_raises(self, env_clear, tmp_path, monkeypatch):
        monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path) if p == "~" else p)
        with pytest.raises(FileNotFoundError):
            push_data.load_config_urls()


class TestSendJsonToAll:
    def test_empty_urls_raise(self, tmp_path):
        fpath = tmp_path / "x.json"
        fpath.write_text("{}")
        with pytest.raises(ValueError):
            push_data.send_json_to_all([], str(fpath), "observations", VALID_KEY)

    def test_primary_and_mirror_both_ok(self, tmp_path):
        fpath = tmp_path / "x.json"
        fpath.write_text("{}")
        with mock.patch.object(push_data, "_post_json_to_url", return_value=True) as m:
            results = push_data.send_json_to_all(
                ["https://a", "https://b"], str(fpath), "observations", VALID_KEY
            )
        assert results == {"https://a": True, "https://b": True}
        assert m.call_count == 2
        roles = [kw["role"] for _, kw in [(c.args, c.kwargs) for c in m.call_args_list]]
        assert roles == ["PRIMARY", "MIRROR"]

    def test_mirror_failure_is_non_fatal(self, tmp_path, capsys):
        fpath = tmp_path / "x.json"
        fpath.write_text("{}")
        with mock.patch.object(push_data, "_post_json_to_url", side_effect=[True, False]):
            results = push_data.send_json_to_all(
                ["https://primary", "https://mirror"], str(fpath), "observations", VALID_KEY
            )
        assert results == {"https://primary": True, "https://mirror": False}
        captured = capsys.readouterr().out
        assert "mirror uploads failed" in captured
        assert "https://mirror" in captured

    def test_primary_failure_raises(self, tmp_path):
        fpath = tmp_path / "x.json"
        fpath.write_text("{}")
        with mock.patch.object(push_data, "_post_json_to_url", side_effect=[False, True]):
            with pytest.raises(RuntimeError, match="Primary upload"):
                push_data.send_json_to_all(
                    ["https://primary", "https://mirror"], str(fpath), "observations", VALID_KEY
                )


class TestLegacyCompat:
    def test_load_config_returns_primary(self, env_clear):
        env_clear.setenv("BASINWX_API_URLS", "https://primary.example,https://mirror.example")
        api_key, url = push_data.load_config()
        assert api_key == VALID_KEY
        assert url == "https://primary.example"

    def test_send_json_to_server_signature_unchanged(self, tmp_path):
        fpath = tmp_path / "x.json"
        fpath.write_text("{}")
        with mock.patch.object(push_data, "_post_json_to_url", return_value=True) as m:
            push_data.send_json_to_server("https://a.example", str(fpath), "observations", VALID_KEY)
        m.assert_called_once()

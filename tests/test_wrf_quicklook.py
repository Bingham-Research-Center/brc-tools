"""Unit tests for the WRF-input quicklook obs overlay (synthetic obs; no network).

``obs_sanity_overlay`` reaches Synoptic via ``case_study.fetch_obs``; here that is
monkeypatched with a synthetic polars DataFrame (or None) so the overlay is exercised
fully offline. ``obs_sanity_overlay`` does a *function-local* import of ``fetch_obs``,
so the patch target is the source module attribute ``case_study.fetch_obs``.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import polars as pl

from brc_tools.nwp import case_study, wrf_quicklook


def _synthetic_obs() -> pl.DataFrame:
    """A KVEL temp_2m series shaped like ObsSource.timeseries output."""
    return pl.DataFrame(
        {
            "stid": ["KVEL", "KVEL", "KVEL"],
            "valid_time": [
                dt.datetime(2013, 1, 31, 12),
                dt.datetime(2013, 1, 31, 18),
                dt.datetime(2013, 2, 1, 0),
            ],
            "temp_2m": [-5.0, -8.0, -10.5],
        }
    )


def test_obs_sanity_overlay_renders_png(tmp_path, monkeypatch):
    monkeypatch.setattr(case_study, "fetch_obs", lambda **_kw: _synthetic_obs())
    out = wrf_quicklook.obs_sanity_overlay(
        case="t", event_date="2013-01-31", figure_dir=tmp_path
    )
    assert out is not None
    out = Path(out)
    assert out.exists() and out.suffix == ".png"
    assert out.parent == tmp_path  # honored figure_dir
    assert out.name == "obs_KVEL_temp_2m.png"


def test_obs_sanity_overlay_none_when_fetch_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(case_study, "fetch_obs", lambda **_kw: None)
    assert (
        wrf_quicklook.obs_sanity_overlay(
            case="t", event_date="2013-01-31", figure_dir=tmp_path
        )
        is None
    )


def test_obs_sanity_overlay_none_when_empty(tmp_path, monkeypatch):
    empty = pl.DataFrame({"stid": [], "valid_time": [], "temp_2m": []})
    monkeypatch.setattr(case_study, "fetch_obs", lambda **_kw: empty)
    assert (
        wrf_quicklook.obs_sanity_overlay(
            case="t", event_date="2013-01-31", figure_dir=tmp_path
        )
        is None
    )

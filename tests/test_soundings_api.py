"""Offline tests for brc_tools.api.soundings (no network).

Provider fetches are mocked at the siphon layer so the normalisation -- unit
conversion, schema, level filtering, sort order, and provider fallback -- is what
is under test, not the external archives.
"""

from __future__ import annotations

import sys
import types
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from brc_tools.api import soundings
from brc_tools.api.soundings import client as sc

VALID = datetime(2013, 2, 2, 12)


def test_station_registry_and_resolution():
    # The four domain-overlapping RAOB proxies are registered.
    assert set(soundings.STATIONS) == {"KSLC", "KGJT", "KRIW", "KDPG"}
    assert soundings.resolve_station("KSLC", "igra2") == "USM00072572"
    assert soundings.resolve_station("kslc", "wyoming") == "72572"      # case-insensitive
    # An IGRA2 id encodes the WMO number in its last 5 chars.
    for st in soundings.STATIONS.values():
        assert st.igra2.endswith(st.wyoming)
    # Unknown names pass through so callers can hand over a raw provider id.
    assert soundings.resolve_station("USM00099999", "igra2") == "USM00099999"


def _fake_siphon_igra2(monkeypatch, u_ms, v_ms):
    """Install a fake siphon IGRAUpperAir returning IGRA2-style m/s winds."""
    frame = pd.DataFrame(
        {
            "pressure": [1000.0, 900.0, 700.0],
            "temperature": [12.0, 8.0, np.nan],   # top level junk (no temperature)
            "dewpoint": [9.0, np.nan, np.nan],
            "u_wind": u_ms,
            "v_wind": v_ms,
        }
    )
    mod = types.ModuleType("siphon.simplewebservice.igra2")
    mod.IGRAUpperAir = types.SimpleNamespace(
        request_data=lambda valid, site: (frame, pd.DataFrame({"site_id": [site]}))
    )
    monkeypatch.setitem(sys.modules, "siphon.simplewebservice.igra2", mod)


def test_igra2_units_and_schema(monkeypatch):
    _fake_siphon_igra2(monkeypatch, u_ms=[5.0, 15.0, 20.0], v_ms=[1.0, 2.0, -3.0])
    df = soundings.fetch_sounding("KSLC", VALID, provider="igra2")

    assert df.columns == sc.CANONICAL_COLUMNS
    assert df.height == 2                         # the no-temperature level is dropped
    assert df["pressure_hpa"].to_list() == [1000.0, 900.0]   # sorted surface->top
    # m/s -> knots conversion applied to IGRA2 winds.
    assert df["u_kt"][0] == pytest.approx(5.0 * sc.MS_TO_KT)
    assert df["v_kt"][1] == pytest.approx(2.0 * sc.MS_TO_KT)
    assert df["provider"][0] == "igra2"
    assert df["station"][0] == "KSLC"


def test_auto_falls_back_to_wyoming(monkeypatch):
    # IGRA2 raises; Wyoming answers with knots (no conversion).
    def boom(site, valid):
        raise RuntimeError("igra2 offline")

    def wyo(site, valid):
        return {
            "pressure_hpa": np.array([1000.0, 850.0]),
            "temperature_c": np.array([12.0, 5.0]),
            "dewpoint_c": np.array([9.0, 0.0]),
            "u_kt": np.array([5.0, 10.0]),
            "v_kt": np.array([1.0, 0.0]),
        }

    monkeypatch.setitem(sc._PROVIDERS, "igra2", boom)
    monkeypatch.setitem(sc._PROVIDERS, "wyoming", wyo)
    df = soundings.fetch_sounding("KSLC", VALID, provider="auto")
    assert df["provider"][0] == "wyoming"
    assert df["u_kt"][0] == pytest.approx(5.0)     # knots kept verbatim


def test_returns_none_when_all_providers_fail(monkeypatch):
    def boom(site, valid):
        raise RuntimeError("down")

    monkeypatch.setitem(sc._PROVIDERS, "igra2", boom)
    monkeypatch.setitem(sc._PROVIDERS, "wyoming", boom)
    assert soundings.fetch_sounding("KSLC", VALID, provider="auto") is None


def test_fetch_soundings_multi_status(monkeypatch):
    def only_kslc(station, valid_time, *, provider="auto"):
        import polars as pl
        if station != "KSLC":
            return None
        return pl.DataFrame(
            {
                "station": ["KSLC"], "valid_time": [valid_time], "pressure_hpa": [850.0],
                "temperature_c": [5.0], "dewpoint_c": [0.0], "u_kt": [10.0],
                "v_kt": [0.0], "provider": ["igra2"],
            }
        )

    monkeypatch.setattr(sc, "fetch_sounding", only_kslc)
    df, status = soundings.fetch_soundings(["KSLC", "KGJT"], VALID)
    assert status == {"KSLC": "igra2", "KGJT": None}
    assert df.height == 1

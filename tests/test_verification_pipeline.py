"""The verification chain end to end on synthetic data: NWPSource.fetch ->
extract_at_waypoints, ObsSource.timeseries -> align_obs_to_nwp -> paired_scores.

Obs are built from the same analytic truth the fake model serves, offset by a known
amount (model 1.5 K warm, 200 Pa low), so the scores have exact expected values. The
obs at :25 and :45 past each hour are deliberately wrong: only a correct nearest-time
join (to :05) gives the expected numbers.
"""

from __future__ import annotations

import datetime as dt
import logging

import numpy as np
import polars as pl
import pytest

pytest.importorskip("synoptic.services")
import synoptic.services  # noqa: E402
from _nwp_fakes import (  # noqa: E402
    SFC_MESSAGES,
    field_value,
    lambert_grid,
    long_obs_frame,
    make_fake_herbie,
    make_fake_timeseries,
)

from brc_tools.nwp import alignment, source  # noqa: E402
from brc_tools.nwp.alignment import align_obs_to_nwp, harmonize_units  # noqa: E402
from brc_tools.nwp.source import NWPSource, load_lookups  # noqa: E402
from brc_tools.obs.source import ObsSource  # noqa: E402
from brc_tools.verify.deterministic import paired_scores  # noqa: E402

LU = load_lookups()
INIT = dt.datetime(2026, 11, 21, 5)
HOURS = [0, 1, 2, 3]
GROUP = "basin_full"
WARM_K = 1.5
LOW_PA = 200.0
GAP = ("QV4", 2)  # Vernal's temperature is missing at f02


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("BRC_TOOLS_LOCK_DIR", str(tmp_path))
    monkeypatch.delenv("BRC_TOOLS_HERBIE_CACHE", raising=False)


def _nearest_index(ds, lat, lon):
    lon_q = lon % 360.0
    d2 = (ds.latitude.values - lat) ** 2 + (ds.longitude.values - lon_q) ** 2
    return np.unravel_index(np.argmin(d2), d2.shape)


def _run_pipeline(monkeypatch):
    monkeypatch.setattr(source, "Herbie", make_fake_herbie(lambert_grid()))
    src = NWPSource("hrrr")
    ds = src.fetch(INIT, HOURS, ["temp_2m", "mslp"], region="uinta_basin")
    nwp_df = src.extract_at_waypoints(ds, group=GROUP)

    wps = {LU["waypoints"][w]["reference_stid"]: LU["waypoints"][w] for w in LU["waypoint_groups"][GROUP]}
    lat2d = ds.latitude.values
    lon180 = ((ds.longitude.values + 180.0) % 360.0) - 180.0

    def truth(stid, base, fxx):
        yi, xi = _nearest_index(ds, wps[stid]["lat"], wps[stid]["lon"])
        return float(field_value(base, fxx, lat2d[yi, xi], lon180[yi, xi]))

    def values(stid, lat, lon, t, var):
        minutes = int((t - INIT).total_seconds() // 60)
        fxx, past = divmod(minutes, 60)
        if past != 5:
            return 999.0  # off-hour report: wrong on purpose
        if var == "air_temp":
            if (stid, fxx) == GAP:
                return None
            return truth(stid, SFC_MESSAGES["TMP:2 m above ground"][1], fxx) - 273.15 - WARM_K
        if var == "sea_level_pressure":
            return truth(stid, SFC_MESSAGES["MSLMA:mean sea level"][1], fxx) + LOW_PA
        return None

    times = [INIT + dt.timedelta(minutes=m) for m in range(5, 60 * len(HOURS), 20)]
    stations = {s: (w["lat"], w["lon"], w["elevation_m"]) for s, w in wps.items()}

    def frame_for(*, stid, vars, **_):
        return long_obs_frame({s: stations[s] for s in stid}, times, values=values, variables=vars)

    monkeypatch.setattr(synoptic.services, "TimeSeries", make_fake_timeseries(frame_for))
    obs_df = ObsSource().timeseries(waypoint_group=GROUP, start=INIT,
                                    end=INIT + dt.timedelta(hours=len(HOURS)),
                                    variables=["temp_2m", "mslp"])
    return nwp_df, obs_df


def test_alignment_pairs_each_model_hour_with_the_nearest_report(monkeypatch):
    nwp_df, obs_df = _run_pipeline(monkeypatch)
    paired = align_obs_to_nwp(obs_df, nwp_df, variables=["temp_2m", "mslp"])

    assert paired.height == nwp_df.height
    assert {"temp_2m_nwp", "temp_2m_obs", "mslp_nwp", "mslp_obs"} <= set(paired.columns)
    diff = (paired["temp_2m_nwp"] - paired["temp_2m_obs"]).drop_nulls()
    np.testing.assert_allclose(diff.to_numpy(), WARM_K, atol=1e-9)  # NWP K -> obs C
    gap = paired.filter((pl.col("waypoint") == "vernal")
                        & (pl.col("valid_time") == INIT + dt.timedelta(hours=GAP[1])))
    assert gap["temp_2m_obs"].to_list() == [None]


def test_paired_scores_recover_the_planted_bias(monkeypatch):
    nwp_df, obs_df = _run_pipeline(monkeypatch)
    scores = paired_scores(nwp_df, obs_df, ["temp_2m", "mslp"])

    group = LU["waypoint_groups"][GROUP]
    assert scores.height == 2 * len(group)
    for row in scores.iter_rows(named=True):
        planted = WARM_K if row["variable"] == "temp_2m" else -LOW_PA
        assert row["bias"] == pytest.approx(planted, abs=1e-6)
        assert row["mae"] == pytest.approx(abs(planted), abs=1e-6)
        assert row["rmse"] == pytest.approx(abs(planted), abs=1e-6)
        assert row["correlation"] == pytest.approx(1.0, abs=1e-6)
        gap = row["waypoint"] == "vernal" and row["variable"] == "temp_2m"
        assert row["n_obs"] == len(HOURS) - (1 if gap else 0)


def test_outside_the_tolerance_nothing_is_paired(monkeypatch):
    nwp_df, obs_df = _run_pipeline(monkeypatch)
    paired = align_obs_to_nwp(obs_df, nwp_df, variables=["temp_2m"], tolerance_minutes=4)
    assert paired["temp_2m_obs"].null_count() == paired.height


# ── unit harmonisation ───────────────────────────────────────────────────


def _frames(var, nwp_value, obs_value):
    t = [INIT]
    nwp = pl.DataFrame({"waypoint": ["vernal"], "valid_time": t, var: [nwp_value]})
    obs = pl.DataFrame({"waypoint": ["vernal"], "valid_time": t, var: [obs_value]})
    return nwp, obs


def test_soil_moisture_fraction_becomes_percent():
    nwp, obs = _frames("soil_moisture", 0.25, 25.0)
    nwp2, _ = harmonize_units(nwp, obs, ["soil_moisture"])
    assert nwp2["soil_moisture"][0] == pytest.approx(25.0)
    _, obs2 = harmonize_units(nwp, obs, ["soil_moisture"], target="nwp")
    assert obs2["soil_moisture"][0] == pytest.approx(0.25)


def test_same_quantity_spelt_two_ways_is_left_alone(caplog):
    nwp, obs = _frames("precip_accum", 3.0, 3.0)
    with caplog.at_level(logging.WARNING, logger="brc_tools.nwp.alignment"):
        nwp2, obs2 = harmonize_units(nwp, obs, ["precip_accum", "solar_radiation", "snow_water_equiv"])
    assert nwp2["precip_accum"][0] == 3.0 and obs2["precip_accum"][0] == 3.0
    assert not caplog.records


def test_every_registry_unit_pair_is_converted_or_declared_the_same(caplog):
    """A new alias whose NWP and Synoptic units differ must say how to convert."""
    pairs = [(k, a) for k, a in LU["aliases"].items() if a.get("units") and a.get("synoptic_units")]
    names = [k for k, _ in pairs]
    frame = pl.DataFrame({"waypoint": ["x"], "valid_time": [INIT], **{n: [1.0] for n in names}})
    with caplog.at_level(logging.WARNING, logger="brc_tools.nwp.alignment"):
        harmonize_units(frame, frame, names)
        harmonize_units(frame, frame, names, target="nwp")
    assert not caplog.records, [r.getMessage() for r in caplog.records]


def test_a_pair_with_no_converter_warns_instead_of_passing_silently(monkeypatch, caplog):
    lu = load_lookups()
    patched = dict(lu, aliases=dict(lu["aliases"], odd={"output_var": "odd", "units": "furlong",
                                                        "synoptic_units": "m"}))
    monkeypatch.setattr(alignment, "load_lookups", lambda: patched)
    nwp, obs = _frames("odd", 1.0, 1.0)
    with caplog.at_level(logging.WARNING, logger="brc_tools.nwp.alignment"):
        harmonize_units(nwp, obs, ["odd"])
    assert any("furlong" in r.getMessage() for r in caplog.records)

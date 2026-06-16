"""Unit tests for WRF-input GRIB staging (mocked Herbie; no network by default).

A live smoke test that hits real S3 is gated behind ``RUN_LIVE_HERBIE=1`` and the
``live`` marker, skipped in the default suite.
"""

from __future__ import annotations

import hashlib
import os
import socket
from pathlib import Path

import pandas as pd
import pytest
import requests

from brc_tools.nwp import wrf_staging
from brc_tools.nwp._cache import validate_cached_grib
from brc_tools.nwp.wrf_staging import (
    StagedFile,
    _canonical_staging_path,
    _fxx_bucket,
    _install_ipv4_only,
    _interval_hours_for_sources,
    _ipv4_only_requested,
    _lead_search_regex,
    _member_token,
    _nam_cycle_times,
    _sha256,
    build_contract,
    build_manifest,
    plan_case,
    stage_nam_analysis,
    stage_reforecast,
    verify_manifest,
    write_manifest,
)

_FULL_LEADS = list(range(3, 61, 3))  # 3..60 h, mimics a Days:1-10 inventory slice

_VALID_GRIB = b"GRIB" + b"\x00" * 1400  # passes validate_cached_grib (magic + size)


# ── Fake Herbie ──────────────────────────────────────────────────────────────


class FakeHerbie:
    """Stand-in for ``herbie.Herbie`` — writes a tiny valid GRIB, no network."""

    init_count = 0
    download_count = 0
    last_search = None
    inventory_rows = [f"{h} hour fcst" for h in _FULL_LEADS]

    def __init__(self, date, *, model, member, fxx, variable_level, save_dir, **kw):
        type(self).init_count += 1
        self.date = date
        self.model = model
        self.member = member
        self.fxx = fxx
        self.variable_level = variable_level
        self.save_dir = Path(save_dir)
        self.grib_source = "aws"
        token = _member_token(member)
        self.SOURCES = {
            "aws": (
                "https://noaa-gefs-retrospective.s3.amazonaws.com/GEFSv12/reforecast/"
                f"2013/2013013100/{token}/Days:1-10/{variable_level}_2013013100_{token}.grib2"
            )
        }
        self._cache_path = self.save_dir / f"_cache_{variable_level}_{token}.grib2"

    def inventory(self, *_a, **_k):
        return pd.DataFrame({"forecast_time": list(type(self).inventory_rows)})

    def download(self, *_a, **_k):
        type(self).download_count += 1
        type(self).last_search = _k.get("search", _a[0] if _a else None)
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self._cache_path.write_bytes(_VALID_GRIB)
        return self._cache_path


@pytest.fixture
def fake_herbie(monkeypatch):
    FakeHerbie.init_count = 0
    FakeHerbie.download_count = 0
    FakeHerbie.last_search = None
    FakeHerbie.inventory_rows = [f"{h} hour fcst" for h in _FULL_LEADS]
    monkeypatch.setattr(wrf_staging, "Herbie", FakeHerbie)
    return FakeHerbie


# ── pure helpers ─────────────────────────────────────────────────────────────


def test_member_token_mapping():
    assert _member_token(0) == "c00"
    assert _member_token(1) == "p01"
    assert _member_token(4) == "p04"
    for bad in (5, -1):
        with pytest.raises(ValueError):
            _member_token(bad)


def test_fxx_bucket_logic():
    for fxx in (0, 12, 48, 240):
        assert _fxx_bucket(fxx) == "Days:1-10"
    for fxx in (241, 384):
        assert _fxx_bucket(fxx) == "Days:10-16"


def test_canonical_staging_path():
    p = _canonical_staging_path(Path("/root"), "case1", "gefs_reforecast", "c00", "tmp_2m.grib2")
    assert p == Path("/root/case1/gefs_reforecast/c00/tmp_2m.grib2")
    p1 = _canonical_staging_path(Path("/root"), "case1", "gefs_reforecast", "p01", "tmp_2m.grib2")
    assert p1.parent.name == "p01"


def test_sha256_and_size(tmp_path):
    blob = b"hello-grib-bytes" * 100
    f = tmp_path / "x.bin"
    f.write_bytes(blob)
    assert _sha256(f) == hashlib.sha256(blob).hexdigest()
    assert f.stat().st_size == len(blob)


def test_lookups_gefs_reforecast_parses():
    cfg = wrf_staging.load_lookups()["models"]["gefs_reforecast"]
    assert cfg["init_cadence_hours"] == 24
    assert cfg["members"] == [0, 1, 2, 3, 4]
    assert cfg["crop_method"] == "lonlat_shift_then_sel"
    tokens = cfg["wps_variable_levels"]
    assert tokens  # non-empty
    # the S3-confirmed corrections (not the analogy-guessed tokens)
    assert "hgt_pres_abv700mb" in tokens  # 700 hPa split
    assert "spfh_2m" in tokens and "rh_2m" not in tokens  # specific, not relative
    assert "ugrd_hgt" in tokens and "ugrd_10m" not in tokens  # height-level 10 m winds


def test_staged_file_schema():
    from dataclasses import asdict

    sf = StagedFile(
        source="gefs_reforecast", herbie_model="gefs_reforecast", member="c00",
        member_int=0, init_time="2013-01-31T00:00:00Z", variable_level="tmp_2m",
        fxx_bucket="Days:1-10", lead_times=[12, 24], product="GEFSv12/reforecast",
        local_path="/x/tmp_2m.grib2", remote_url="https://example/x.grib2",
        size_bytes=123, sha256="abc", created_at="2026-06-11T00:00:00Z",
    )
    d = asdict(sf)
    expected = {
        "source", "herbie_model", "member", "member_int", "init_time",
        "variable_level", "fxx_bucket", "lead_times", "product", "local_path",
        "remote_url", "size_bytes", "sha256", "created_at", "lead_times_source",
    }
    assert set(d) == expected
    assert d["init_time"].endswith("Z") and isinstance(d["member_int"], int)
    assert d["lead_times_source"] == "inventory"  # default when not given


def test_nam_cycle_enumeration():
    import datetime as dt

    init = dt.datetime(2013, 1, 31, 0, tzinfo=dt.timezone.utc)
    cycles = _nam_cycle_times(init, (12, 48), cadence_hours=6, pad_cycles=0)
    assert [c.strftime("%Y%m%d_%H%M") for c in cycles] == [
        "20130131_1200", "20130131_1800",
        "20130201_0000", "20130201_0600", "20130201_1200", "20130201_1800",
        "20130202_0000",
    ]
    # off-grid window start snaps DOWN to the 6 h cycle grid (13Z -> 12Z)
    assert _nam_cycle_times(init, (13, 18), 6, 0)[0].strftime("%H%M") == "1200"
    # pad_cycles widens the window by one cycle each end (12Z - 6h -> 06Z)
    assert _nam_cycle_times(init, (12, 18), 6, 1)[0].strftime("%H%M") == "0600"


def test_canonical_staging_path_memberless():
    p = _canonical_staging_path(Path("/root"), "c", "nam_analysis", "", "namanl_218_x.grb")
    assert p == Path("/root/c/nam_analysis/namanl_218_x.grb")  # no member dir


def test_lookups_nam_analysis_parses():
    cfg = wrf_staging.load_lookups()["models"]["nam_analysis"]
    assert cfg["cadence_hours"] == 6
    assert "{yyyymmdd}" in cfg["filename_template"]
    assert cfg["url_template"].startswith("https://www.ncei.noaa.gov/")


# ── stager (mocked Herbie) ───────────────────────────────────────────────────


def test_stage_reforecast_moves_into_layout(tmp_path, fake_herbie):
    staged = stage_reforecast(
        init_time="2013-01-31 00Z",
        variable_levels=["tmp_2m", "weasd_sfc"],
        member=0,
        output_root=tmp_path,
        case="t",
        herbie_save_dir=tmp_path / "cache",
    )
    assert len(staged) == 2
    for sf in staged:
        dest = Path(sf.local_path)
        assert dest.exists() and validate_cached_grib(dest)
        assert dest.parent == tmp_path / "t" / "gefs_reforecast" / "c00"
        assert sf.member == "c00" and sf.member_int == 0
        assert sf.lead_times == _FULL_LEADS  # whole bucket parsed from inventory
        assert sf.lead_times_source == "inventory"
        assert sf.sha256 and sf.size_bytes == len(_VALID_GRIB)
        assert sf.remote_url and sf.remote_url.endswith(".grib2")
    assert fake_herbie.last_search is None  # whole-file download, no byte-range subset
    # files were MOVED out of the Herbie cache, not copied
    assert not any((tmp_path / "cache").glob("_cache_*.grib2"))


def test_stage_reforecast_skips_existing(tmp_path, fake_herbie):
    dest = _canonical_staging_path(
        tmp_path, "t", "gefs_reforecast", "c00", "tmp_2m_2013013100_c00.grib2"
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_VALID_GRIB)

    staged = stage_reforecast(
        init_time="2013-01-31 00Z",
        variable_levels=["tmp_2m"],
        member=0,
        output_root=tmp_path,
        case="t",
        herbie_save_dir=tmp_path / "cache",
        overwrite=False,
    )
    assert len(staged) == 1
    assert fake_herbie.init_count == 0  # Herbie never constructed
    assert fake_herbie.download_count == 0


def test_skip_existing_labels_idx_and_no_idx(tmp_path, fake_herbie):
    dest = _canonical_staging_path(
        tmp_path, "t", "gefs_reforecast", "c00", "tmp_2m_2013013100_c00.grib2"
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_VALID_GRIB)

    kw = dict(
        init_time="2013-01-31 00Z", variable_levels=["tmp_2m"], member=0,
        output_root=tmp_path, case="t", herbie_save_dir=tmp_path / "cache",
    )

    # (a) no co-located idx -> empty lead_times, explicitly labelled "skip-no-idx"
    staged = stage_reforecast(**kw)
    assert staged[0].lead_times == []
    assert staged[0].lead_times_source == "skip-no-idx"

    # (b) a co-located <dest>.idx is parsed offline -> recovered leads, labelled "idx"
    Path(str(dest) + ".idx").write_text(
        "1:0:d=2013013100:TMP:2 m above ground:12 hour fcst:ENS=low-res ctl\n"
        "2:100:d=2013013100:TMP:2 m above ground:24 hour fcst:ENS=low-res ctl\n"
        "3:200:d=2013013100:TMP:2 m above ground:36 hour fcst:ENS=low-res ctl\n"
    )
    staged = stage_reforecast(**kw)
    assert staged[0].lead_times == [12, 24, 36]
    assert staged[0].lead_times_source == "idx"
    assert fake_herbie.download_count == 0  # both runs hit the skip path, no download


def test_validate_tokens_raises_on_empty_inventory(tmp_path, fake_herbie):
    fake_herbie.inventory_rows = []  # simulate a bad/absent token
    with pytest.raises(ValueError, match="bogus_token"):
        stage_reforecast(
            init_time="2013-01-31 00Z",
            variable_levels=["bogus_token"],
            member=0,
            output_root=tmp_path,
            case="t",
            herbie_save_dir=tmp_path / "cache",
        )


def test_lead_search_regex():
    import re

    inv = pd.DataFrame({"forecast_time": [f"{h} hour fcst" for h in _FULL_LEADS]})
    rgx, leads = _lead_search_regex(inv, 12, 48)
    assert leads == [12, 15, 18, 21, 24, 27, 30, 33, 36, 39, 42, 45, 48]
    assert rgx == r":(?:12|15|18|21|24|27|30|33|36|39|42|45|48) hour fcst:"
    # leading ':' guards 12 vs 112; trailing ' hour' guards 12 vs 120
    assert re.search(rgx, ":TMP:2 m above ground:12 hour fcst:ENS=low-res ctl")
    assert not re.search(rgx, ":TMP:2 m above ground:112 hour fcst:ENS=low-res ctl")
    assert not re.search(rgx, ":HGT:500 mb:120 hour fcst:ENS=low-res ctl")
    # accumulation-style leads (no integer 'N hour fcst' in window) -> None
    inv2 = pd.DataFrame({"forecast_time": ["0-3 hour acc", "0-6 hour acc"]})
    assert _lead_search_regex(inv2, 12, 48) == (None, [])


def test_lead_subset_passes_search_and_subsets(tmp_path, fake_herbie):
    staged = stage_reforecast(
        init_time="2013-01-31 00Z", variable_levels=["tmp_2m"], member=0,
        output_root=tmp_path, case="t", herbie_save_dir=tmp_path / "cache",
        fxx_window=(12, 48), lead_subset=True,
    )
    assert fake_herbie.last_search == r":(?:12|15|18|21|24|27|30|33|36|39|42|45|48) hour fcst:"
    assert staged[0].lead_times == [12, 15, 18, 21, 24, 27, 30, 33, 36, 39, 42, 45, 48]


def test_remote_url_recorded(tmp_path, fake_herbie):
    staged = stage_reforecast(
        init_time="2013-01-31 00Z",
        variable_levels=["tmp_2m"],
        member=0,
        output_root=tmp_path,
        case="t",
        herbie_save_dir=tmp_path / "cache",
    )
    assert staged[0].remote_url.startswith("https://noaa-gefs-retrospective.s3.amazonaws.com/")


# ── NAM analysis stager (mocked HTTP) ────────────────────────────────────────


class FakeResponse:
    """Stand-in for a streamed ``requests`` response yielding a tiny valid GRIB."""

    def __init__(self, status_code=200, content=_VALID_GRIB):
        self.status_code = status_code
        self._content = content

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")

    def iter_content(self, chunk_size=1):
        yield self._content


class FakeGet:
    """Records requested URLs/timeouts; 404s any URL containing a ``missing`` token."""

    def __init__(self):
        self.urls = []
        self.timeouts = []
        self.missing = set()

    def __call__(self, url, stream=False, timeout=None):
        self.urls.append(url)
        self.timeouts.append(timeout)
        code = 404 if any(m in url for m in self.missing) else 200
        return FakeResponse(status_code=code)


@pytest.fixture
def fake_nam_http(monkeypatch):
    fg = FakeGet()
    monkeypatch.setattr(wrf_staging.requests, "get", fg)
    return fg


def test_stage_nam_analysis_layout_and_manifest(tmp_path, fake_nam_http):
    staged = stage_nam_analysis(
        init_time="2013-01-31 00Z",
        fxx_window=(12, 48),
        output_root=tmp_path,
        case="t",
    )
    assert len(staged) == 7  # 6-hourly cycles 12Z Jan31 .. 00Z Feb2
    for sf in staged:
        dest = Path(sf.local_path)
        assert dest.exists() and validate_cached_grib(dest)
        assert dest.parent == tmp_path / "t" / "nam_analysis"  # no member dir
        assert dest.name.startswith("namanl_218_") and dest.name.endswith("_000.grb")
        assert sf.source == "nam_analysis" and sf.member == "" and sf.member_int == 0
        assert sf.variable_level == "all" and sf.lead_times == [0]
        assert sf.sha256 and sf.size_bytes == len(_VALID_GRIB)
        assert sf.remote_url.startswith("https://www.ncei.noaa.gov/")
    assert len(fake_nam_http.urls) == 7  # one whole-file GET per cycle


def test_stage_nam_skips_missing_cycle(tmp_path, fake_nam_http):
    fake_nam_http.missing.add("20130201_0600")  # one interior cycle 404s
    staged = stage_nam_analysis(
        init_time="2013-01-31 00Z", fxx_window=(12, 48),
        output_root=tmp_path, case="t",
    )
    assert len(staged) == 6  # missing cycle skipped, not fatal
    assert all("20130201_0600" not in sf.local_path for sf in staged)


def test_stage_nam_all_missing_raises(tmp_path, fake_nam_http):
    fake_nam_http.missing.add("namanl_218")  # in every URL -> every cycle 404s
    with pytest.raises(RuntimeError, match="missing/unreachable"):
        stage_nam_analysis(
            init_time="2013-01-31 00Z", fxx_window=(12, 48),
            output_root=tmp_path, case="t",
        )


def test_stage_nam_skips_existing(tmp_path, fake_nam_http):
    dest = _canonical_staging_path(
        tmp_path, "t", "nam_analysis", "", "namanl_218_20130131_1200_000.grb"
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_VALID_GRIB)
    staged = stage_nam_analysis(
        init_time="2013-01-31 00Z", fxx_window=(12, 12),  # single 12Z cycle
        output_root=tmp_path, case="t", overwrite=False,
    )
    assert len(staged) == 1
    assert fake_nam_http.urls == []  # already staged -> no HTTP call


# ── manifest ─────────────────────────────────────────────────────────────────


def test_build_manifest_shape():
    sf = StagedFile(
        source="gefs_reforecast", herbie_model="gefs_reforecast", member="c00",
        member_int=0, init_time="2013-01-31T00:00:00Z", variable_level="tmp_2m",
        fxx_bucket="Days:1-10", lead_times=[12, 24], product="GEFSv12/reforecast",
        local_path="/x/tmp_2m.grib2", remote_url="https://example/x.grib2",
        size_bytes=123, sha256="abc", created_at="2026-06-11T00:00:00Z",
    )
    m = build_manifest(
        case="jan2013_basin_gefs",
        region="uinta_basin_wide",
        requested_window=("2013-01-31T12:00:00Z", "2013-02-02T00:00:00Z"),
        interval_hours=3,
        sources=["gefs_reforecast"],
        staged=[sf],
    )
    assert m["schema_version"] == wrf_staging.MANIFEST_SCHEMA_VERSION
    assert m["case"]["bbox"] == {"sw": [38.8, -111.5], "ne": [41.7, -107.8]}
    assert m["case"]["sources"] == ["gefs_reforecast"]
    assert m["provenance"]["generated_at"].endswith("Z")
    assert "git_sha" in m["provenance"] and "tool_version" in m["provenance"]
    assert m["provenance"]["total_bytes"] == 123  # sum of staged size_bytes
    assert m["provenance"]["elapsed_seconds"] is None  # not passed -> null
    assert len(m["staged_files"]) == 1
    assert m["staged_files"][0]["variable_level"] == "tmp_2m"


def test_manifest_records_total_bytes_and_elapsed():
    def _sf(size: int) -> StagedFile:
        return StagedFile(
            source="nam_analysis", herbie_model="", member="", member_int=0,
            init_time="2013-01-31T12:00:00Z", variable_level="all", fxx_bucket="analysis",
            lead_times=[0], product="x", local_path="/x/f", remote_url="h",
            size_bytes=size, sha256="a", created_at="2026-06-15T00:00:00Z",
        )

    m = build_manifest(
        case="c", region="uinta_basin_wide",
        requested_window=("2013-01-31T12:00:00Z", "2013-02-02T00:00:00Z"),
        interval_hours=6, sources=["nam_analysis"], staged=[_sf(100), _sf(250)],
        elapsed_seconds=1.23456,
    )
    assert m["provenance"]["total_bytes"] == 350  # footprint = sum of size_bytes
    assert m["provenance"]["elapsed_seconds"] == 1.235  # rounded to 3 dp

    m0 = build_manifest(
        case="c", region="uinta_basin_wide",
        requested_window=("2013-01-31T12:00:00Z", "2013-02-02T00:00:00Z"),
        interval_hours=6, sources=["nam_analysis"], staged=[],
    )
    assert m0["provenance"]["total_bytes"] == 0
    assert m0["provenance"]["elapsed_seconds"] is None  # unmeasured


def test_write_manifest_roundtrips(tmp_path):
    import json

    m = build_manifest(
        case="c", region="uinta_basin_wide",
        requested_window=("2013-01-31T12:00:00Z", "2013-02-02T00:00:00Z"),
        interval_hours=3, sources=["gefs_reforecast"], staged=[],
    )
    path = wrf_staging.write_manifest(m, tmp_path / "c")
    assert path.name == "manifest_c.json"
    reloaded = json.loads(path.read_text())
    assert reloaded["manifest_kind"] == "wrf_input_staging"


# ── IPv4-only + timeout hardening ────────────────────────────────────────────


@pytest.fixture
def restore_getaddrinfo():
    """Snapshot/restore ``socket.getaddrinfo`` around an IPv4-only install."""
    original = socket.getaddrinfo
    try:
        yield
    finally:
        socket.getaddrinfo = original


def _fake_getaddrinfo_mixed(host, port, family=0, *a, **k):
    return [
        (socket.AF_INET6, None, None, "", ("::1", port, 0, 0)),
        (socket.AF_INET, None, None, "", ("127.0.0.1", port)),
    ]


def test_ipv4_only_requested_env(monkeypatch):
    monkeypatch.delenv("BRC_TOOLS_HTTP_IPV4_ONLY", raising=False)
    assert _ipv4_only_requested() is False
    monkeypatch.setenv("BRC_TOOLS_HTTP_IPV4_ONLY", "1")
    assert _ipv4_only_requested() is True
    monkeypatch.setenv("BRC_TOOLS_HTTP_IPV4_ONLY", "0")
    assert _ipv4_only_requested() is False


def test_install_ipv4_only_filters_and_is_idempotent(restore_getaddrinfo):
    socket.getaddrinfo = _fake_getaddrinfo_mixed
    original = _install_ipv4_only()
    assert original is _fake_getaddrinfo_mixed
    families = {r[0] for r in socket.getaddrinfo("ncei.noaa.gov", 443)}
    assert families == {socket.AF_INET}  # AF_INET6 entries dropped
    assert _install_ipv4_only() is None  # already tagged -> no-op


def test_nam_passes_connect_read_timeout_tuple(tmp_path, fake_nam_http):
    stage_nam_analysis(
        init_time="2013-01-31 00Z", fxx_window=(12, 12),
        output_root=tmp_path, case="t",
        connect_timeout=7.0, read_timeout=88.0,
    )
    assert fake_nam_http.timeouts
    assert all(t == (7.0, 88.0) for t in fake_nam_http.timeouts)


# ── plan / dry-run (offline) ─────────────────────────────────────────────────


def test_plan_case_nam_offline(tmp_path):
    plan = plan_case(
        case="t", init_time="2013-01-31 00Z", output_root=tmp_path,
        fxx_window=(12, 48), sources=("nam_analysis",),
    )
    assert len(plan) == 7  # 6-hourly cycles, same as stage_nam_analysis
    assert all(e["source"] == "nam_analysis" for e in plan)
    assert all(e["url"].startswith("https://www.ncei.noaa.gov/") for e in plan)
    assert all(e["est_bytes"] for e in plan)
    assert plan[0]["local_path"].endswith("_000.grb")


def test_plan_case_reforecast_offline(tmp_path):
    plan = plan_case(
        case="t", init_time="2013-01-31 00Z", output_root=tmp_path,
        members=(0,), variable_levels=["tmp_2m", "weasd_sfc"],
        sources=("gefs_reforecast",),
    )
    assert len(plan) == 2
    assert all(e["member"] == "c00" for e in plan)
    assert all(
        e["url"].startswith("https://noaa-gefs-retrospective.s3.amazonaws.com/")
        for e in plan
    )
    assert all(e["est_bytes"] is None for e in plan)  # reforecast size unknown offline


# ── manifest integrity ───────────────────────────────────────────────────────


def _nam_staged(p: Path) -> StagedFile:
    return StagedFile(
        source="nam_analysis", herbie_model="", member="", member_int=0,
        init_time="2013-01-31T12:00:00Z", variable_level="all", fxx_bucket="analysis",
        lead_times=[0], product="namanl_218", local_path=str(p), remote_url="https://x",
        size_bytes=p.stat().st_size, sha256=_sha256(p), created_at="2026-06-13T00:00:00Z",
    )


def test_verify_manifest_pass_and_detects_corruption(tmp_path):
    f1 = tmp_path / "a.grib2"; f1.write_bytes(_VALID_GRIB)
    f2 = tmp_path / "b.grib2"; f2.write_bytes(_VALID_GRIB + b"x")
    m = build_manifest(
        case="c", region="uinta_basin_wide",
        requested_window=("2013-01-31T12:00:00Z", "2013-02-02T00:00:00Z"),
        interval_hours=6, sources=["nam_analysis"],
        staged=[_nam_staged(f1), _nam_staged(f2)],
    )
    mpath = write_manifest(m, tmp_path)
    report = verify_manifest(mpath)
    assert report["ok"] and report["n_ok"] == 2

    f1.unlink()                          # -> missing
    f2.write_bytes(_VALID_GRIB + b"DIFFERENT")  # -> size/sha mismatch
    report = verify_manifest(mpath)
    assert not report["ok"] and report["n_ok"] == 0
    problems = {Path(r["local_path"]).name: r["problem"] for r in report["results"]}
    assert problems["a.grib2"] == "missing"
    assert "size" in problems["b.grib2"] or "sha256" in problems["b.grib2"]


# ── case contract + interval derivation ──────────────────────────────────────


def test_interval_hours_for_sources():
    lu = wrf_staging.load_lookups()
    assert _interval_hours_for_sources(("nam_analysis",), lu) == 6
    assert _interval_hours_for_sources(("gefs_reforecast",), lu) == 3
    assert _interval_hours_for_sources(("gefs_reforecast", "nam_analysis"), lu) == 3


def test_build_contract_nam_only():
    m = build_manifest(
        case="jan2013_basin_gefs", region="uinta_basin_wide",
        requested_window=("2013-01-31T12:00:00Z", "2013-02-02T00:00:00Z"),
        interval_hours=6, sources=["nam_analysis"],
        staged=[_nam_staged_stub("nam_analysis")],
    )
    c = build_contract(m)
    assert c["wps_fg_name"] == ["NAM"]
    assert c["interval_seconds"] == 21600 and c["interval_hours"] == 6
    assert c["source_file_counts"] == {"nam_analysis": 1}
    assert c["cadence_hours"]["nam_analysis"] == 6


def test_build_contract_two_stream():
    m = build_manifest(
        case="c", region="uinta_basin_wide",
        requested_window=("2013-01-31T12:00:00Z", "2013-02-02T00:00:00Z"),
        interval_hours=3, sources=["gefs_reforecast", "nam_analysis"],
        staged=[_nam_staged_stub("gefs_reforecast"), _nam_staged_stub("nam_analysis")],
    )
    c = build_contract(m)
    assert c["wps_fg_name"] == ["GEFS", "NAM"]
    assert c["interval_seconds"] == 10800
    assert c["source_file_counts"] == {"gefs_reforecast": 1, "nam_analysis": 1}


def test_stage_case_writes_contract_and_derived_interval(tmp_path, fake_nam_http):
    import json

    wrf_staging.stage_case(
        case="t", init_time="2013-01-31 00Z", region="uinta_basin_wide",
        output_root=tmp_path, fxx_window=(12, 12), sources=("nam_analysis",),
        quicklook=False,
    )
    contract = json.loads((tmp_path / "t" / "contract_t.json").read_text())
    assert contract["wps_fg_name"] == ["NAM"] and contract["interval_seconds"] == 21600
    manifest = json.loads((tmp_path / "t" / "manifest_t.json").read_text())
    assert manifest["case"]["interval_hours"] == 6  # derived, not the blind default 3


def _nam_staged_stub(source: str) -> StagedFile:
    """Minimal StagedFile (no real file) for contract-shape tests."""
    return StagedFile(
        source=source, herbie_model="", member="", member_int=0,
        init_time="2013-01-31T12:00:00Z", variable_level="all", fxx_bucket="analysis",
        lead_times=[0], product="x", local_path="/x/f", remote_url="h",
        size_bytes=1, sha256="a", created_at="2026-06-13T00:00:00Z",
    )


# ── opt-in live smoke ────────────────────────────────────────────────────────


@pytest.mark.live
@pytest.mark.skipif(
    not os.environ.get("RUN_LIVE_HERBIE"),
    reason="set RUN_LIVE_HERBIE=1 to hit real S3 reforecast download",
)
def test_live_single_variable_single_member(tmp_path):
    staged = stage_reforecast(
        init_time="2013-01-31 00Z",
        variable_levels=["tmp_2m"],
        member=0,
        output_root=tmp_path,
        case="live_smoke",
        herbie_save_dir=tmp_path / "cache",
    )
    assert len(staged) == 1
    p = Path(staged[0].local_path)
    assert p.exists() and validate_cached_grib(p)
    assert staged[0].sha256 and staged[0].lead_times


@pytest.mark.live
@pytest.mark.skipif(
    not os.environ.get("RUN_LIVE_NCEI"),
    reason="set RUN_LIVE_NCEI=1 to hit the real NCEI NAM analysis archive",
)
def test_live_nam_single_cycle(tmp_path):
    staged = stage_nam_analysis(
        init_time="2013-01-31 00Z",
        fxx_window=(12, 12),  # one analysis cycle (~115 MB)
        output_root=tmp_path,
        case="live_nam_smoke",
    )
    assert len(staged) == 1
    p = Path(staged[0].local_path)
    assert p.exists() and validate_cached_grib(p)
    assert staged[0].source == "nam_analysis"
    assert staged[0].size_bytes > 1_000_000  # a real NAM file, not a stub

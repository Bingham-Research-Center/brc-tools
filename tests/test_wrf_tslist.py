"""Unit tests for brc_tools.nwp.wrf_tslist.

Synthetic fixtures written to ``tmp_path``, matching the repo convention -- real
WRF output is never touched by the suite.  The formats reproduced here are taken
from the Ashley control run: a 19-column ``.TS`` and a 45-level profile, both
headed by the same line, with ``ts_hour`` printed to six decimals so a 3 s step
appears as 0.000833 h.
"""

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from brc_tools.nwp.wrf_tslist import (
    PROFILE_KINDS,
    TS_COLUMNS,
    list_ts_stations,
    parse_ts_header,
    read_ts,
    read_ts_profile,
    read_ts_profiles,
    read_tslist,
    ts_path,
)

HEADER = (
    "spotter point              2  1 SPOT  ( 40.411,-109.511) "
    "( 208, 169) ( 40.414,-109.512) 1622.9 meters  2025-10-11_23:00:00"
)
DT_S = 3.0


def _ts_row(step: int) -> str:
    hour = step * DT_S / 3600.0
    # domain, ts_hour, id, i, j then the 14 surface values
    vals = [2, f"{hour:.6f}", 1, 208, 169]
    u, v = 3.0, 4.0  # speed 5, direction 216.87
    vals += [
        f"{293.0 + 0.001 * step:.5f}", "0.00823", f"{u:.5f}", f"{v:.5f}",
        f"{82805.5 - step:.5f}", "315.12485", "233.66777", "74.25152",
        "12.14620", "295.36874", "290.70139", "0.00000", "0.00000", "0.00000",
    ]
    return " " + "  ".join(str(x) for x in vals)


def _write_ts(tmp_path, prefix="SPOT", domain=2, n=5):
    path = tmp_path / f"{prefix}.d{domain:02d}.TS"
    path.write_text("\n".join([HEADER] + [_ts_row(k) for k in range(1, n + 1)]) + "\n")
    return path


def _write_profile(tmp_path, kind="TH", prefix="SPOT", domain=2, n=5, nlev=45):
    rows = []
    for k in range(1, n + 1):
        hour = k * DT_S / 3600.0
        levels = [f"{300.0 + j:.5f}" for j in range(nlev)]
        rows.append(f"  {hour:.6f}  " + "  ".join(levels))
    path = tmp_path / f"{prefix}.d{domain:02d}.{kind}"
    path.write_text("\n".join([HEADER] + rows) + "\n")
    return path


class TestHeader:
    def test_parses_every_field(self):
        h = parse_ts_header(HEADER)
        assert h.name == "spotter point"
        assert (h.domain, h.ts_id, h.prefix) == (2, 1, "SPOT")
        assert (h.request_lat, h.request_lon) == (40.411, -109.511)
        assert (h.grid_i, h.grid_j) == (208, 169)
        assert h.elevation_m == pytest.approx(1622.9)
        assert h.init_time == datetime(2025, 10, 11, 23, tzinfo=timezone.utc)

    @pytest.mark.parametrize(
        "name",
        ["Dinosaur NM A3822", "Jensen COOPJENU1", "Vernal West PC353", "Little Mountain PC266"],
    )
    def test_names_with_spaces_and_digits(self, name):
        # Real station names carry both, so the head must be split from the right
        # rather than by column position.
        line = HEADER.replace("spotter point", name, 1)
        assert parse_ts_header(line).name == name

    def test_rejects_a_non_header_line(self):
        with pytest.raises(ValueError, match="not a WRF time-series header"):
            parse_ts_header(" 2  0.000833  1  208  169  293.0")


class TestReadTS:
    def test_shape_and_columns(self, tmp_path):
        df = read_ts(_write_ts(tmp_path, n=4))
        assert df.height == 4
        for col in TS_COLUMNS:
            assert col in df.columns
        for col in ("valid_time", "station", "name", "terrain_m",
                    "wind_speed_10m", "wind_dir_10m"):
            assert col in df.columns

    def test_time_axis_is_exactly_uniform(self, tmp_path):
        # The point of snapping: ts_hour's six decimals turn 3 s into 2.9988 s,
        # and unsnapped that accumulates into a ragged axis that breaks filtering
        # on minute boundaries.
        df = read_ts(_write_ts(tmp_path, n=20))
        t = df["valid_time"].to_numpy()
        steps = np.unique(np.diff(t).astype("timedelta64[ms]").astype(int))
        assert steps.tolist() == [int(DT_S * 1000)]
        assert df["valid_time"][0] == datetime(2025, 10, 11, 23, 0, 3, tzinfo=timezone.utc)

    def test_derived_wind(self, tmp_path):
        df = read_ts(_write_ts(tmp_path))
        assert df["wind_speed_10m"][0] == pytest.approx(5.0)
        # u=3, v=4 blows toward the north-east, so it comes FROM the south-west.
        assert df["wind_dir_10m"][0] == pytest.approx(216.87, abs=0.01)

    def test_derive_wind_can_be_switched_off(self, tmp_path):
        df = read_ts(_write_ts(tmp_path), derive_wind=False)
        assert "wind_speed_10m" not in df.columns

    def test_header_travels_with_the_rows(self, tmp_path):
        # So several stations can be concatenated and grouped.
        df = read_ts(_write_ts(tmp_path))
        assert set(df["station"].unique()) == {"SPOT"}
        assert df["terrain_m"][0] == pytest.approx(1622.9)

    def test_rejects_a_ragged_record(self, tmp_path):
        path = _write_ts(tmp_path, n=3)
        path.write_text(path.read_text() + " 2  0.001  1  208\n")
        with pytest.raises(ValueError, match="expected 19 columns"):
            read_ts(path)

    def test_rejects_header_only_file(self, tmp_path):
        path = tmp_path / "SPOT.d02.TS"
        path.write_text(HEADER + "\n")
        with pytest.raises(ValueError, match="no records"):
            read_ts(path)


class TestProfiles:
    def test_read_one_profile(self, tmp_path):
        header, times, values = read_ts_profile(_write_profile(tmp_path, n=6))
        assert values.shape == (6, 45)
        assert len(times) == 6
        assert header.prefix == "SPOT"
        # level 0 is the lowest model level
        assert values[0, 0] == pytest.approx(300.0)

    def test_read_several_kinds_on_a_common_axis(self, tmp_path):
        for kind in ("PH", "TH", "UU", "VV"):
            _write_profile(tmp_path, kind=kind, n=4)
        out = read_ts_profiles(tmp_path, "SPOT", 2)
        assert out["TH"].shape == (4, 45)
        assert len(out["valid_times"]) == 4
        assert out["header"].prefix == "SPOT"

    def test_mismatched_time_axes_raise(self, tmp_path):
        # A run that is still writing can leave one kind short; truncating
        # silently would misalign a time-height section.
        _write_profile(tmp_path, kind="PH", n=6)
        _write_profile(tmp_path, kind="TH", n=4)
        with pytest.raises(ValueError, match="still be writing"):
            read_ts_profiles(tmp_path, "SPOT", 2, kinds=("PH", "TH"))

    def test_every_documented_kind_is_a_valid_path(self, tmp_path):
        for kind in PROFILE_KINDS:
            assert ts_path(tmp_path, "SPOT", 2, kind).name == f"SPOT.d02.{kind}"

    def test_unknown_kind_is_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="unknown time-series kind"):
            ts_path(tmp_path, "SPOT", 2, "XX")


class TestTslistInput:
    def test_reads_the_twelve_location_format(self, tmp_path):
        path = tmp_path / "tslist"
        path.write_text(
            "#-----------------------------------------------#\n"
            "# 24 characters for name | pfx |  LAT  |   LON  |\n"
            "#-----------------------------------------------#\n"
            "spotter point             SPOT   40.411 -109.511\n"
            "Vernal airport KVEL       KVEL   40.443 -109.513\n"
            "Little Mountain PC266     P266   40.542 -109.700\n"
        )
        locs = read_tslist(path)
        assert [l.prefix for l in locs] == ["SPOT", "KVEL", "P266"]
        assert locs[0].name == "spotter point"
        assert locs[2].lat == pytest.approx(40.542)
        assert locs[2].lon == pytest.approx(-109.700)

    def test_unparseable_line_raises(self, tmp_path):
        path = tmp_path / "tslist"
        path.write_text("# comment\nnot a station line\n")
        with pytest.raises(ValueError, match="unparseable tslist line"):
            read_tslist(path)


def test_list_ts_stations(tmp_path):
    for prefix in ("KVEL", "SPOT", "P266"):
        _write_ts(tmp_path, prefix=prefix, domain=2)
    _write_ts(tmp_path, prefix="OTHR", domain=1)
    assert list_ts_stations(tmp_path, 2) == ["KVEL", "P266", "SPOT"]
    assert list_ts_stations(tmp_path, 1) == ["OTHR"]

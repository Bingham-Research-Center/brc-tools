"""Tests for brc_tools.visualize.tracer_origin and .timeheight.

The renderers are smoke-tested (a PNG is written, and a section without the
tracers it needs says so rather than drawing a blank).  What is asserted properly
is the *encoding*: opacity carries the confidence in the attribution, and getting
that ramp wrong is what makes a 13-%-against-12-% argmax look like a finding.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest
from _wrf_synthetic import make_synthetic_wrf

from brc_tools.nwp import wrf_section as ws
from brc_tools.visualize import timeheight as tim
from brc_tools.visualize import tracer_origin as tro

LABELS = ["one", "two", "three"]


@pytest.fixture
def section():
    plane = ws.load_plane(make_synthetic_wrf(tracers=3), extras=("tracers",))
    return ws.section_from_plane(plane, (40.05, -109.95), (40.45, -109.55),
                                 n_points=12)


class TestPalette:
    def test_no_colour_is_a_neutral_grey(self):
        """Faded toward white, a desaturated hue lands on the untagged colour --
        so "mixed air" and "no tagged air" become the same pixel."""
        for hexcode in tro.SOURCE_COLOURS:
            r, g, b = (int(hexcode[i:i + 2], 16) for i in (1, 3, 5))
            assert max(r, g, b) - min(r, g, b) > 40, hexcode

    def test_it_warns_rather_than_silently_reusing_a_colour(self, capsys):
        colours = tro.source_colours(len(tro.SOURCE_COLOURS) + 2)
        assert "WARN" in capsys.readouterr().out
        assert colours[0] == colours[len(tro.SOURCE_COLOURS)]


class TestPurityAlpha:
    def test_a_single_source_is_fully_opaque(self):
        assert tro.purity_alpha(1.0, 8) == pytest.approx(1.0)

    def test_an_n_way_tie_sits_at_the_floor(self):
        """The ramp starts at 1/n, not 0: no data can ever reach below an n-way
        tie, so a scale anchored at zero would draw a four-source mixture and an
        eight-source one equally solid."""
        assert tro.purity_alpha(1 / 8, 8) == pytest.approx(tro._ALPHA_MIN)
        assert tro.purity_alpha(1 / 3, 3) == pytest.approx(tro._ALPHA_MIN)

    def test_it_never_vanishes(self):
        """A tied cell still holds tagged air; alpha 0 would make it read as
        untagged, which is a different finding."""
        assert tro.purity_alpha(0.0, 8) >= tro._ALPHA_MIN > 0.0

    def test_nan_purity_stays_nan(self):
        assert np.isnan(tro.purity_alpha(np.nan, 8))


class TestOriginRenderers:
    def test_curtain_writes_a_file(self, tmp_path, section):
        out = tro.plot_origin_curtain(section, tmp_path / "o.png", labels=LABELS,
                                      title="t", y_top_m=2200.0, dpi=60)
        assert out.exists() and out.stat().st_size > 0

    def test_curtain_in_agl_writes_a_file(self, tmp_path, section):
        out = tro.plot_origin_curtain(section, tmp_path / "a.png", labels=LABELS,
                                      title="t", vertical="agl", y_top_m=400.0,
                                      y_bottom_m=-10.0, dpi=60)
        assert out.exists()

    def test_a_section_without_tracers_says_how_to_get_them(self, tmp_path):
        plane = ws.load_plane(make_synthetic_wrf())
        bare = ws.section_from_plane(plane, (40.05, -109.95), (40.45, -109.55),
                                     n_points=8)
        with pytest.raises(ValueError, match="load_plane"):
            tro.plot_origin_curtain(bare, tmp_path / "x.png", labels=LABELS,
                                    title="t")

    def test_spectrum_writes_a_file(self, tmp_path, section):
        stack = np.asarray(section.tracers2d)[:, :, 0]
        height = np.asarray(section.height2d)[:, 0] - section.terrain1d[0]
        out = tro.plot_tracer_spectrum(stack, height, tmp_path / "s.png",
                                       labels=LABELS, title="t",
                                       theta_col=section.theta2d[:, 0],
                                       top_m=400.0, dpi=60)
        assert out.exists()

    def test_map_writes_a_file(self, tmp_path):
        plane = ws.load_plane(make_synthetic_wrf(tracers=3), extras=("tracers",))
        out = tro.plot_origin_map(plane.lon2d, plane.lat2d, plane.terrain,
                                  plane.tracers[:, 0], tmp_path / "m.png",
                                  labels=LABELS, title="t", overlays={}, dpi=60)
        assert out.exists()


# --------------------------------------------------------------------------- #
# time-height
# --------------------------------------------------------------------------- #
def _profiles(nt=6, nlev=5):
    z = np.broadcast_to(np.arange(nlev) * 100.0 + 50.0, (nt, nlev)).astype(float)
    th = np.broadcast_to(np.arange(nlev) * 2.0 + 280.0, (nt, nlev)).astype(float).copy()
    th += np.arange(nt).reshape(nt, 1)          # 1 K of warming per output time
    return {"PH": z + 1500.0, "TH": th,
            "UU": np.full((nt, nlev), 3.0), "VV": np.full((nt, nlev), 4.0),
            "WW": np.full((nt, nlev), 0.1), "QV": np.full((nt, nlev), 0.002)}


class TestTimeHeightFields:
    def test_tables_are_keyed_alike(self):
        assert (sorted(tim.FIELD_LABEL) == sorted(tim.FIELD_STYLE)
                == sorted(tim.FIELD_REQUIRES))

    def test_every_field_has_a_style(self):
        from brc_tools.visualize.style import VAR_STYLES

        assert all(v in VAR_STYLES for v in tim.FIELD_STYLE.values())

    def test_theta_change_is_against_the_first_time_at_fixed_height(self):
        change = tim.derive_field(_profiles(), "theta_change")
        assert change[0] == pytest.approx(0.0)
        assert change[-1] == pytest.approx(5.0)

    def test_speed_is_the_magnitude(self):
        assert tim.derive_field(_profiles(), "speed") == pytest.approx(5.0)

    def test_theta_grad_uses_the_height_axis(self):
        """2 K per 100 m on this synthetic column."""
        assert tim.derive_field(_profiles(), "theta_grad") == pytest.approx(2.0)

    def test_an_unknown_field_is_refused(self):
        with pytest.raises(KeyError, match="unknown time-height field"):
            tim.derive_field(_profiles(), "nope")

    def test_a_missing_profile_kind_names_it(self):
        prof = _profiles()
        del prof["WW"]
        with pytest.raises(KeyError, match="WW"):
            tim.derive_field(prof, "w")


class TestTimeHeightMesh:
    def test_corners_bracket_the_centres(self):
        prof = _profiles()
        t = np.arange(6, dtype=float)
        X, Y = tim.timeheight_mesh(t, prof["PH"])
        assert X.shape == Y.shape == (7, 6)
        assert X[0, 0] < t[0] and X[-1, 0] > t[-1]
        assert Y[0, 0] < prof["PH"][0, 0] < Y[0, -1]

    def test_it_writes_a_file(self, tmp_path):
        from brc_tools.visualize.style import get_style

        prof = _profiles()
        t0 = datetime(2025, 11, 21, 12)
        times = [t0 + timedelta(minutes=10 * i) for i in range(6)]
        out = tim.plot_time_height(
            times, prof["PH"] - 1500.0, tim.derive_field(prof, "theta"),
            tmp_path / "th.png", style=get_style("theta"), title="t",
            theta=prof["TH"], wind=(prof["UU"], prof["VV"]),
            y_top_m=500.0, local_offset_h=-7.0, dpi=60)
        assert out.exists() and out.stat().st_size > 0

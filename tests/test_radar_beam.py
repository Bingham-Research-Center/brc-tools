"""Unit tests for brc_tools.radar.beam.

The anchor case is CHK-BEAM from the Ashley rotating-cell experiment, which is
independently confirmed: KGJX sits on Grand Mesa at 3046 m, 189 km from Vernal
(valley floor 1622 m), and under the standard 4/3-Earth model its beam centre
over Vernal is ~3.5 km AGL at 0.0 deg, ~5.2 km at 0.5 deg and ~7.5 km at 1.2 deg.
Those three numbers are why no observed couplet over the Basin may be called
low-level, so they are the numbers this module has to reproduce.
"""

import numpy as np
import pytest

from brc_tools.radar.beam import (
    EARTH_RADIUS_M,
    REFRACTION_K,
    beam_edges_asl,
    beam_height_agl,
    beam_height_asl,
    beam_surface_asl,
    great_circle_distance_m,
    sample_on_beam,
)
from brc_tools.radar.sites import get_site

KGJX_ALT_M = 3046.0
VERNAL_FLOOR_M = 1622.0
RANGE_M = 189_000.0


class TestCHKBeam:
    @pytest.mark.parametrize(
        "elev_deg, expected_km",
        [(0.0, 3.5), (0.5, 5.2), (1.2, 7.5)],
    )
    def test_beam_height_over_vernal(self, elev_deg, expected_km):
        agl = beam_height_agl(RANGE_M, elev_deg, KGJX_ALT_M, VERNAL_FLOOR_M)
        # 0.1 km tolerance: the confirmed values are quoted to that precision.
        assert agl / 1000.0 == pytest.approx(expected_km, abs=0.1)

    def test_lowest_scan_is_well_above_the_boundary_layer(self):
        # The claim this supports: nothing below ~3 km AGL over the Basin was
        # sampled at all -- so surface stations are the only access to the layer
        # where the gust lived.
        assert beam_height_agl(RANGE_M, 0.0, KGJX_ALT_M, VERNAL_FLOOR_M) > 3_000.0

    def test_beam_edges_bracket_the_centre_and_span_kilometres(self):
        lower, upper = beam_edges_asl(RANGE_M, 0.0, KGJX_ALT_M)
        centre = beam_height_asl(RANGE_M, 0.0, KGJX_ALT_M)
        assert lower < centre < upper
        # The 0.95 deg beamwidth spans well over a kilometre at 189 km.
        assert (upper - lower) > 1_000.0
        # Worth stating precisely, because it qualifies the "nothing below ~3 km"
        # claim: that is true of the beam CENTRE. The lower half-power edge of the
        # 0.0 deg scan still reaches ~2 km AGL, at reduced gain. So the honest
        # statement is about where the beam was centred, not a hard floor on
        # sensitivity -- and it is still far above the layer the gust lived in.
        assert 1_800.0 < (lower - VERNAL_FLOOR_M) < 2_200.0


class TestGeometry:
    def test_height_increases_with_range_and_elevation(self):
        h = beam_height_asl(np.array([50e3, 100e3, 200e3]), 0.5, 1000.0)
        assert np.all(np.diff(h) > 0)
        angles = [beam_height_asl(150e3, e, 1000.0) for e in (0.0, 0.5, 1.5, 3.0)]
        assert np.all(np.diff(angles) > 0)

    def test_zero_range_is_the_antenna(self):
        assert beam_height_asl(0.0, 0.0, 2000.0) == pytest.approx(2000.0)
        assert beam_height_asl(0.0, 15.0, 2000.0) == pytest.approx(2000.0)

    def test_refraction_keeps_the_beam_closer_to_the_ground(self):
        # Refraction bends the beam DOWNWARD, toward the Earth. The 4/3 model
        # encodes that by straightening the beam over a flatter Earth, so the
        # larger effective radius makes the surface fall away more slowly and the
        # beam ends up LOWER than the unrefracted case -- it sees further, and
        # deeper, than pure geometry would allow.
        refr = beam_height_asl(200e3, 0.0, 0.0, refraction=REFRACTION_K)
        geom = beam_height_asl(200e3, 0.0, 0.0, refraction=1.0)
        assert refr < geom

    def test_curvature_term_matches_the_closed_form(self):
        # At zero elevation the height above the antenna is the classic
        # r^2 / (2 k a) to leading order.
        r = 100e3
        approx = r**2 / (2.0 * REFRACTION_K * EARTH_RADIUS_M)
        assert beam_height_asl(r, 0.0, 0.0) == pytest.approx(approx, rel=1e-4)

    def test_great_circle_distance_kgjx_to_vernal(self):
        site = get_site("kgjx")  # case-insensitive on purpose
        d = great_circle_distance_m(site.lat, site.lon, 40.4550, -109.5300)
        assert d / 1000.0 == pytest.approx(189.0, abs=3.0)

    def test_unknown_site_names_the_alternatives(self):
        with pytest.raises(KeyError, match="KGJX"):
            get_site("KNOPE")


class TestBeamSurfaceAndSampling:
    @staticmethod
    def _grid():
        lat = np.linspace(40.2, 40.7, 5)
        lon = np.linspace(-109.9, -109.2, 6)
        return np.meshgrid(lat, lon, indexing="ij")

    def test_surface_climbs_away_from_the_radar(self):
        lat2d, lon2d = self._grid()
        surf = beam_surface_asl(lat2d, lon2d, get_site("KGJX"), 0.5)
        assert surf.shape == lat2d.shape
        # KGJX is south-east of the grid, so the north-west corner is furthest
        # and must carry the highest beam.
        assert surf[-1, 0] > surf[0, -1]
        assert np.all(surf > 4_000.0)

    def test_longitude_convention_does_not_matter(self):
        lat2d, lon2d = self._grid()
        a = beam_surface_asl(lat2d, lon2d, get_site("KGJX"), 0.5)
        b = beam_surface_asl(lat2d, lon2d + 360.0, get_site("KGJX"), 0.5)
        np.testing.assert_allclose(a, b)

    def test_sample_on_beam_picks_the_right_level(self):
        # Build a column where the field equals height, so a correct sample
        # returns the beam height itself.
        ny, nx, nz = 4, 3, 12
        z = np.empty((nz, ny, nx))
        for k in range(nz):
            z[k] = 1000.0 + 1000.0 * k
        field = z.copy()
        target = np.full((ny, nx), 5500.0)
        out = sample_on_beam(field, z, target)
        np.testing.assert_allclose(out, target, rtol=1e-6)

    def test_sample_is_nan_where_the_beam_is_outside_the_column(self):
        ny, nx, nz = 2, 2, 5
        z = np.stack([np.full((ny, nx), 1000.0 + 500.0 * k) for k in range(nz)])
        field = np.zeros_like(z)
        target = np.array([[500.0, 3000.0], [1e9, 2000.0]])
        out = sample_on_beam(field, z, target)
        assert np.isnan(out[0, 0])  # below the lowest level
        assert np.isnan(out[1, 0])  # above the model top
        assert not np.isnan(out[0, 1])
        assert not np.isnan(out[1, 1])

    def test_varying_surface_beats_a_constant_height(self):
        # The point of the whole module: on a real beam the sampled height varies
        # by kilometres across a 600 m nest's footprint, so a fixed 1 km AGL
        # comparison is not the same measurement.
        lat2d, lon2d = self._grid()
        surf = beam_surface_asl(lat2d, lon2d, get_site("KGJX"), 0.5)
        assert (surf.max() - surf.min()) > 1_000.0

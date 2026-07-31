"""Tests for brc_tools.nwp.wrf_section -- transect sampling and grid coverage.

The point of most of these is the failure the sampler used to have silently:
nearest-neighbour has no upper bound, so a transect running off the nest kept
returning the boundary column for the rest of its length and drew a flat,
entirely physical-looking curtain.  The synthetic grid spans lat 40.0-40.5 and
lon -110.0 to -109.5, so a line pushed east of -109.5 is provably off it.
"""

from __future__ import annotations

import numpy as np
import pytest
from _wrf_synthetic import make_synthetic_wrf

from brc_tools.nwp import wrf_section as ws


@pytest.fixture
def plane():
    return ws.load_plane(make_synthetic_wrf(convective=True))


# Inside the synthetic grid (lat 40.0..40.5, lon -110.0..-109.5).
INSIDE_A = (40.1, -109.9)
INSIDE_B = (40.4, -109.6)


class TestGridSpacing:
    def test_matches_the_synthetic_grid_step(self, plane):
        # 0.1 deg steps: 11.06 km in latitude, 111.32*0.1*cos(40) = 8.53 km in
        # longitude.  The median over both axes must land between the two.
        spacing = ws.grid_spacing_km(plane.lat2d, plane.lon2d)
        assert 8.0 < spacing < 11.5

    def test_a_single_column_grid_is_refused(self):
        with pytest.raises(ValueError, match="two columns"):
            ws.grid_spacing_km(np.array([[40.0]]), np.array([[-110.0]]))


class TestSectionCoverage:
    def test_a_transect_inside_the_nest_is_fully_covered(self, plane):
        cov = ws.section_coverage(plane, INSIDE_A, INSIDE_B, n_points=50)
        assert cov.fully_inside
        assert cov.n_inside == cov.n_points == 50
        assert cov.inside_fraction == 1.0
        assert cov.first_outside_km is None
        assert "on-grid" in cov.describe()

    def test_a_transect_running_off_the_east_edge_is_partly_covered(self, plane):
        # Starts inside, ends ~1.5 deg east of the grid's last column.
        cov = ws.section_coverage(plane, (40.25, -109.75), (40.25, -108.0), n_points=100)
        assert not cov.fully_inside
        assert 0.0 < cov.inside_fraction < 1.0
        # It began on the grid, so the departure is reported at a distance, not None.
        assert cov.first_outside_km is not None and cov.first_outside_km > 0.0
        assert cov.worst_gap_km > cov.tolerance_km
        assert "leaves the grid" in cov.describe()

    def test_a_transect_entirely_off_the_grid_covers_nothing(self, plane):
        cov = ws.section_coverage(plane, (45.0, -100.0), (45.5, -99.0), n_points=30)
        assert cov.n_inside == 0
        assert cov.inside_fraction == 0.0
        assert not cov.fully_inside
        # Outside from terminus A onward reads better than "leaves at 0.0 km".
        assert cov.first_outside_km is None
        assert "from the start" in cov.describe()

    def test_accepts_bare_lat_lon_so_it_can_run_before_load_plane(self, plane):
        # The preflight must not require the expensive 3-D read.
        from_plane = ws.section_coverage(plane, INSIDE_A, INSIDE_B, n_points=40)
        from_arrays = ws.section_coverage(
            plane.lat2d, INSIDE_A, INSIDE_B, lon2d=plane.lon2d, n_points=40
        )
        assert from_arrays == from_plane

    def test_bare_lat_without_lon_is_a_type_error(self, plane):
        with pytest.raises(TypeError, match="both lat2d and lon2d"):
            ws.section_coverage(plane.lat2d, INSIDE_A, INSIDE_B)

    def test_an_explicit_tolerance_overrides_the_grid_derived_one(self, plane):
        loose = ws.section_coverage(
            plane, (40.25, -109.75), (40.25, -108.0), n_points=100, max_gap_km=1e6
        )
        assert loose.fully_inside  # nothing is 1000 km from this grid


class TestOffGridBlanking:
    def test_an_on_grid_section_blanks_nothing(self, plane):
        sec = ws.section_from_plane(plane, INSIDE_A, INSIDE_B, n_points=40)
        assert not sec.offgrid1d.any()
        assert np.isfinite(sec.speed2d).all()
        assert np.isfinite(sec.theta2d).all()

    def test_off_grid_columns_are_nan_not_the_edge_column(self, plane):
        sec = ws.section_from_plane(
            plane, (40.25, -109.75), (40.25, -108.0), n_points=100
        )
        off = sec.offgrid1d
        assert off.any() and not off.all(), "expected a partly off-grid transect"

        # The defect: every off-grid sample used to carry the boundary column's
        # value, so the curtain ran flat instead of stopping.
        assert np.isnan(sec.speed2d[:, off]).all()
        assert np.isnan(sec.theta2d[:, off]).all()
        assert np.isnan(sec.temp2d[:, off]).all()
        assert np.isnan(sec.along2d[:, off]).all()
        assert np.isnan(sec.w2d[:, off]).all()
        assert np.isnan(sec.refl2d[:, off]).all()
        # ...and the on-grid part is untouched.
        assert np.isfinite(sec.speed2d[:, ~off]).all()

    def test_geometry_survives_so_the_axes_stay_defined(self, plane):
        sec = ws.section_from_plane(
            plane, (40.25, -109.75), (40.25, -108.0), n_points=100
        )
        # Blanking the heights or the terrain would break the curtain's y-axis and
        # its terrain fill; only the data is missing, not the frame.
        assert np.isfinite(sec.height2d).all()
        assert np.isfinite(sec.height_w2d).all()
        assert np.isfinite(sec.terrain1d).all()
        assert np.isfinite(sec.distance_km).all()

    def test_coverage_and_the_sampler_agree_on_what_is_off_grid(self, plane):
        a, b, n = (40.25, -109.75), (40.25, -108.0), 100
        cov = ws.section_coverage(plane, a, b, n_points=n)
        sec = ws.section_from_plane(plane, a, b, n_points=n)
        assert int((~sec.offgrid1d).sum()) == cov.n_inside

    def test_a_generous_tolerance_restores_the_old_behaviour(self, plane):
        sec = ws.section_from_plane(
            plane, (40.25, -109.75), (40.25, -108.0), n_points=100, max_gap_km=1e6
        )
        assert not sec.offgrid1d.any()
        assert np.isfinite(sec.speed2d).all()


class TestSectionNormalComponent:
    """The wind crossing the section, which the in-plane vectors discard.

    Sign convention: ``+normal`` is INTO THE PAGE -- the left-hand normal of
    A->B -- so on a west-to-east transect drawn with A at the left, northerly
    flow is positive.  These pin that down, because a sign error here is
    invisible in the figure and reverses the meaning of every curtain.
    """

    @staticmethod
    def _uniform(plane, east, north):
        """Replace the plane's wind with a uniform (east, north) field."""
        plane.ue = np.full_like(plane.ue, float(east))
        plane.ve = np.full_like(plane.ve, float(north))
        return plane

    def test_northerly_flow_is_positive_into_the_page_on_a_west_east_line(self, plane):
        # A due-north wind (v = +10) across a west-to-east cut.
        sec = ws.section_from_plane(self._uniform(plane, 0.0, 10.0),
                                    (40.2, -109.9), (40.2, -109.6), n_points=20)
        assert np.allclose(sec.normal2d, 10.0)
        assert np.allclose(sec.along2d, 0.0)

    def test_reversing_the_transect_reverses_the_sign(self, plane):
        """A->B and B->A are the same ground seen from opposite sides, so the
        viewer's 'into the page' flips.  If it did not, the convention would be
        a property of the compass rather than of the figure."""
        p = self._uniform(plane, 0.0, 10.0)
        west_east = ws.section_from_plane(p, (40.2, -109.9), (40.2, -109.6), n_points=20)
        east_west = ws.section_from_plane(p, (40.2, -109.6), (40.2, -109.9), n_points=20)
        assert np.allclose(west_east.normal2d, -east_west.normal2d)

    def test_along_and_normal_are_orthogonal_and_conserve_speed(self, plane):
        """Whatever the line's bearing, the two components must decompose the
        horizontal wind exactly -- no energy invented or lost by the rotation."""
        sec = ws.section_from_plane(self._uniform(plane, 6.0, -8.0),
                                    INSIDE_A, INSIDE_B, n_points=20)
        assert np.allclose(np.hypot(sec.along2d, sec.normal2d), 10.0)
        assert np.allclose(sec.speed2d, 10.0)

    def test_offgrid_samples_are_blanked_in_the_normal_field_too(self, plane):
        """The blanking must cover every data field; a component that escaped it
        would redraw the edge-column artefact the sampler exists to prevent."""
        sec = ws.section_from_plane(self._uniform(plane, 3.0, 4.0),
                                    (40.2, -109.9), (40.2, -109.0), n_points=40)
        assert sec.offgrid1d.any()
        assert np.isnan(sec.normal2d[:, sec.offgrid1d]).all()
        assert not np.isnan(sec.normal2d[:, ~sec.offgrid1d]).any()

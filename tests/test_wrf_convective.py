"""Unit tests for brc_tools.nwp.wrf_convective."""

from datetime import datetime

import numpy as np
import pytest
from _wrf_synthetic import make_synthetic_auxhist, make_synthetic_wrf

from brc_tools.nwp import wrf_convective as wc


class TestAuxStreamTimes:
    def test_decodes_char_times(self):
        ds = make_synthetic_auxhist()
        times = wc._times_in(ds)
        assert times == [
            datetime(2025, 10, 12, 2, 0),
            datetime(2025, 10, 12, 2, 1),
            datetime(2025, 10, 12, 2, 2),
        ]

    def test_decodes_byte_scalars_too(self):
        # xarray's concat_characters default yields S19 scalars rather than a
        # per-character array; str() on those gives "b'2025-...'" and parses as
        # nothing, so both forms must work.
        assert wc._stamp_text(np.bytes_(b"2025-10-12_02:00:00")) == "2025-10-12_02:00:00"
        assert wc._stamp_text(np.frombuffer(b"2025-10-12_02:00:00", dtype="S1")) == (
            "2025-10-12_02:00:00"
        )
        assert wc._stamp_text(b"2025-10-12_02:00:00\x00") == "2025-10-12_02:00:00"

    def test_nocolons_stamps_parse(self):
        ds = make_synthetic_auxhist(times=["2025-10-12_02_00_00", "2025-10-12_02_01_00"])
        assert wc._times_in(ds) == [datetime(2025, 10, 12, 2, 0), datetime(2025, 10, 12, 2, 1)]

    def test_missing_times_variable_raises(self):
        ds = make_synthetic_auxhist().drop_vars("Times")
        with pytest.raises(KeyError, match="no Times"):
            wc._times_in(ds)

    def test_aux_prefix(self):
        assert wc.aux_prefix(2) == "auxhist2_d02_"
        assert wc.aux_prefix(1, stream=3) == "auxhist3_d01_"


class TestResetOnHistoryGuard:
    """The single easiest way to publish a wrong swath, so it must be refused."""

    @pytest.mark.parametrize("name", ["WSPD10MAX", "UP_HELI_MAX", "REFD_MAX", "HAIL_MAX2D"])
    def test_max_fields_are_refused(self, name):
        ds = make_synthetic_auxhist()
        with pytest.raises(ValueError, match="resets on the HISTORY write"):
            wc.aux_field(ds, name)

    def test_the_error_says_where_to_read_it_instead(self):
        ds = make_synthetic_auxhist()
        with pytest.raises(ValueError, match="from wrfout instead"):
            wc.aux_field(ds, "WSPD10MAX")

    def test_ordinary_fields_are_served(self):
        ds = make_synthetic_auxhist()
        out = wc.aux_field(ds, "REFD_COM", 1)
        assert out.shape == (6, 6)
        assert np.allclose(out, 45.0)

    def test_frame_index_selects_the_right_frame(self):
        ds = make_synthetic_auxhist(times=["2025-10-12_02:00:00", "2025-10-12_02:01:00"])
        ds["T2"][1] = 300.0
        assert np.allclose(wc.aux_field(ds, "T2", 0), 288.0)
        assert np.allclose(wc.aux_field(ds, "T2", 1), 300.0)


class TestAttachGridCoords:
    def test_borrows_coordinates_from_a_wrfout(self):
        aux = make_synthetic_auxhist(ny=6, nx=6)
        assert "XLAT" not in aux  # the trap
        coords = wc.attach_grid_coords(aux, make_synthetic_wrf(ny=6, nx=6))
        assert set(coords) == {"latitude", "longitude", "terrain_height"}
        for arr in coords.values():
            assert arr.shape == (6, 6)
        assert coords["longitude"].max() <= 180.0

    def test_wrong_domain_is_caught(self):
        aux = make_synthetic_auxhist(ny=6, nx=6)
        with pytest.raises(ValueError, match="wrong domain"):
            wc.attach_grid_coords(aux, make_synthetic_wrf(ny=8, nx=8))


class TestHighestCrossing:
    def test_picks_the_highest_not_the_lowest_crossing(self):
        # A tent profile crosses 40 dBZ twice. An echo TOP is the upper crossing;
        # reusing an isentrope-lid routine would return the lower one.
        nz, ny, nx = 5, 2, 2
        field = np.zeros((nz, ny, nx))
        field[:, :, :] = np.array([10.0, 45.0, 60.0, 45.0, 10.0]).reshape(nz, 1, 1)
        z = np.arange(nz).reshape(nz, 1, 1) * 1000.0 + np.zeros((nz, ny, nx))
        top = wc.highest_crossing(field, z, 40.0)
        # Between level 3 (45 dBZ, 3000 m) and level 4 (10 dBZ, 4000 m):
        # frac = (40 - 45)/(10 - 45) = 0.1428 -> 3142.9 m
        assert np.allclose(top, 3142.857, atol=0.01)

    def test_nan_where_never_reached(self):
        nz = 4
        field = np.full((nz, 2, 2), 5.0)
        z = np.arange(nz).reshape(nz, 1, 1) * 1000.0 + np.zeros((nz, 2, 2))
        assert np.all(np.isnan(wc.highest_crossing(field, z, 40.0)))

    def test_unresolved_top_returns_the_model_top(self):
        # Still above threshold at the top level: report the top, do not extrapolate.
        nz = 3
        field = np.full((nz, 1, 1), 50.0)
        z = np.arange(nz).reshape(nz, 1, 1) * 1000.0 + np.zeros((nz, 1, 1))
        assert wc.highest_crossing(field, z, 40.0)[0, 0] == pytest.approx(2000.0)

    def test_echo_top_from_a_dataset(self):
        ds = make_synthetic_wrf(nz=7, ny=4, nx=4, convective=True)
        top = wc.echo_top_height(ds, threshold_dbz=40.0)
        assert top.shape == (4, 4)
        assert np.isnan(top[0, 0])  # the deliberately echo-free column
        assert np.isfinite(top[1, 1])


class TestVorticity:
    def test_uniform_flow_has_no_vorticity(self):
        # The fixture has U = 5, V = 2 everywhere.
        ds = make_synthetic_wrf(nz=4, ny=6, nx=6)
        assert np.allclose(wc.vertical_vorticity(ds), 0.0)

    def test_shear_line_produces_cyclonic_vorticity(self):
        # dv/dx > 0 across the grid is cyclonic in the northern hemisphere.
        ds = make_synthetic_wrf(nz=3, ny=5, nx=5)
        v = ds["V"].values.copy()
        nx = v.shape[-1]
        v[...] = np.linspace(-5.0, 5.0, nx).reshape(1, 1, 1, nx)
        ds["V"] = (ds["V"].dims, v)
        zeta = wc.vertical_vorticity(ds)
        assert np.all(zeta > 0)

    def test_storm_relative_winds_subtract_the_motion(self):
        ds = make_synthetic_wrf(nz=3, ny=4, nx=4)
        u, v = wc.storm_relative_winds(ds, 5.0, 2.0)
        assert np.allclose(u, 0.0)
        assert np.allclose(v, 0.0)


class TestSwathAndCentroid:
    @staticmethod
    def _grid(ny=40, nx=40):
        lat = np.linspace(40.2, 40.7, ny)
        lon = np.linspace(-109.9, -109.2, nx)
        return np.meshgrid(lat, lon, indexing="ij")

    def test_locality_matters(self):
        # Two separate features: one at the target point, one far away. Without
        # `near` the answer is the bounding box of both, which is not a width.
        lat2d, lon2d = self._grid()
        field = np.zeros_like(lat2d)
        field[19:21, 18:22] = 50.0  # near the middle
        field[0:2, 0:2] = 50.0  # far corner
        near = (float(lat2d[20, 20]), float(lon2d[20, 20]))
        wide = wc.swath_width_km(lat2d, lon2d, field, 45.0)
        local = wc.swath_width_km(lat2d, lon2d, field, 45.0, near=near, radius_km=10.0)
        assert local < wide / 2.0

    def test_returns_zero_when_nothing_exceeds(self):
        lat2d, lon2d = self._grid()
        assert wc.swath_width_km(lat2d, lon2d, np.zeros_like(lat2d), 45.0) == 0.0

    def test_ns_and_ew_axes_differ_for_an_elongated_feature(self):
        lat2d, lon2d = self._grid()
        field = np.zeros_like(lat2d)
        field[20:22, 5:35] = 50.0  # thin in latitude, long in longitude
        ns = wc.swath_width_km(lat2d, lon2d, field, 45.0, axis="ns")
        ew = wc.swath_width_km(lat2d, lon2d, field, 45.0, axis="ew")
        assert ew > 5 * ns

    def test_bad_axis_raises(self):
        lat2d, lon2d = self._grid()
        with pytest.raises(ValueError, match="axis must be"):
            wc.swath_width_km(lat2d, lon2d, np.ones_like(lat2d) * 50, 45.0, axis="up")

    def test_centroid_none_when_no_echo(self):
        lat2d, lon2d = self._grid()
        assert wc.reflectivity_centroid(lat2d, lon2d, np.zeros_like(lat2d)) is None

    def test_centroid_weights_toward_the_core(self):
        lat2d, lon2d = self._grid()
        refl = np.zeros_like(lat2d)
        refl[10:13, 10:13] = 40.0
        refl[30:33, 30:33] = 70.0  # much stronger
        lat, lon, n = wc.reflectivity_centroid(lat2d, lon2d, refl)
        assert lat > float(lat2d[21, 0])  # pulled toward the strong cell
        assert n == 18

    def test_largest_cluster_isolates_one_storm(self):
        lat2d, lon2d = self._grid()
        refl = np.zeros_like(lat2d)
        refl[5:7, 5:7] = 50.0  # small
        refl[25:32, 25:32] = 50.0  # large
        full = wc.reflectivity_centroid(lat2d, lon2d, refl)
        one = wc.reflectivity_centroid(lat2d, lon2d, refl, largest_cluster=True)
        assert one[2] == 49  # 7x7
        assert full[2] == 53  # 49 + 4
        assert one[0] > full[0]  # no longer dragged south by the small cell

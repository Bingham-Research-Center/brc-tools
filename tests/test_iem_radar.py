"""Unit tests for brc_tools.radar.iem (Iowa State IEM RIDGE Level-III).

Synthetic palette PNGs and world files, so the decoding, the dBZ scaling and the
georeferencing are all checked without a network.  The scaling matters more than
usual here: the payload is an 8-bit palette index, so a wrong offset or step
silently yields a plausible-looking reflectivity field.
"""

import os
from datetime import datetime

import numpy as np
import pytest

Image = pytest.importorskip("PIL.Image")

from brc_tools.radar import iem  # noqa: E402

# The real transform from GJX 2025-10-12 02:18Z.
_DX = 0.010687
_UL_X = -113.557309
_UL_Y = 44.405309


def _write_scan(tmp_path, indices, *, name="GJX_N0B_202510120218", dx=_DX, rotated=False):
    array = np.asarray(indices, dtype=np.uint8)
    image = Image.new("P", (array.shape[1], array.shape[0]))
    image.putpalette([i // 3 % 256 for i in range(768)])
    image.putdata(array.ravel().tolist())
    png = tmp_path / f"{name}.png"
    image.save(png)
    wld = tmp_path / f"{name}.wld"
    rot = "0.5\n0.5\n" if rotated else "0.0\n0.0\n"
    wld.write_text(f"{dx}\n{rot}{-dx}\n{_UL_X}\n{_UL_Y}\n")
    return png, wld


class TestDbzScaling:
    def test_index_zero_is_missing(self):
        assert np.isnan(iem.dbz_from_index(np.array([0]))[0])

    @pytest.mark.parametrize(
        "index, dbz",
        [(1, -32.0), (65, 0.0), (140, 37.5), (180, 57.5), (194, 64.5), (255, 95.0)],
    )
    def test_documented_ramp(self, index, dbz):
        # -32 dBZ at index 1, 0.5 dBZ per step. Verified against the palette on a
        # real scan: index 140 is olive (~37 dBZ), 180 dark red (~57).
        assert iem.dbz_from_index(np.array([index]))[0] == pytest.approx(dbz)

    def test_monotonic(self):
        values = iem.dbz_from_index(np.arange(1, 256))
        assert np.all(np.diff(values) > 0)


class TestWorldFile:
    def test_parses_the_real_transform(self, tmp_path):
        _png, wld = _write_scan(tmp_path, np.zeros((2, 2)))
        dx, dy, ul_x, ul_y = iem.read_world_file(wld)
        assert dx == pytest.approx(_DX)
        assert dy == pytest.approx(-_DX)  # rows run north to south
        assert (ul_x, ul_y) == (pytest.approx(_UL_X), pytest.approx(_UL_Y))

    def test_rotation_is_refused(self, tmp_path):
        # A rotated tile would mis-georeference everything downstream, so refuse
        # rather than quietly dropping the rotation terms.
        _png, wld = _write_scan(tmp_path, np.zeros((2, 2)), rotated=True)
        with pytest.raises(ValueError, match="rotated world files"):
            iem.read_world_file(wld)

    def test_wrong_length_is_refused(self, tmp_path):
        path = tmp_path / "bad.wld"
        path.write_text("1.0\n2.0\n")
        with pytest.raises(ValueError, match="expected 6 world-file values"):
            iem.read_world_file(path)


class TestReadRidge:
    def test_decodes_values_and_grid(self, tmp_path):
        indices = np.array([[0, 140], [180, 194]])
        png, wld = _write_scan(tmp_path, indices)
        field = iem.read_ridge(png, wld, mask_below_dbz=None)

        assert field.site_id == "GJX"
        assert field.product == "N0B"
        assert field.elevation_deg == 0.5
        assert field.valid_time == datetime(2025, 10, 12, 2, 18)
        assert np.isnan(field.values[0, 0])
        assert field.values[0, 1] == pytest.approx(37.5)
        assert field.values[1, 1] == pytest.approx(64.5)

    def test_latitude_descends_and_longitude_ascends(self, tmp_path):
        png, wld = _write_scan(tmp_path, np.full((4, 4), 100))
        field = iem.read_ridge(png, wld)
        assert np.all(np.diff(field.lat) < 0)
        assert np.all(np.diff(field.lon) > 0)
        assert field.lon[0] == pytest.approx(_UL_X)
        assert field.lat[0] == pytest.approx(_UL_Y)

    def test_mask_below_threshold(self, tmp_path):
        # 100 -> 17.5 dBZ, below the 5 dBZ floor is index 65 -> 0 dBZ.
        png, wld = _write_scan(tmp_path, np.array([[65, 100]]))
        field = iem.read_ridge(png, wld, mask_below_dbz=5.0)
        assert np.isnan(field.values[0, 0])
        assert field.values[0, 1] == pytest.approx(17.5)

    def test_velocity_product_is_refused(self, tmp_path):
        # Returning unscaled palette indices labelled m/s would be worse than
        # refusing, so the module refuses until the ramp is verified.
        png, wld = _write_scan(tmp_path, np.zeros((2, 2)), name="GJX_N0S_202510120218")
        with pytest.raises(NotImplementedError, match="not verified"):
            iem.read_ridge(png, wld)

    def test_non_palette_image_is_refused(self, tmp_path):
        path = tmp_path / "GJX_N0B_202510120218.png"
        Image.new("RGB", (4, 4)).save(path)
        _p, wld = _write_scan(tmp_path, np.zeros((2, 2)), name="other")
        with pytest.raises(ValueError, match="expected a palette image"):
            iem.read_ridge(path, wld)


class TestSubset:
    def _field(self, tmp_path):
        png, wld = _write_scan(tmp_path, np.full((200, 200), 140))
        return iem.read_ridge(png, wld)

    def test_crops_to_the_extent(self, tmp_path):
        field = self._field(tmp_path)
        small = field.subset((-113.0, -112.8, 43.5, 43.7))
        assert small.values.shape[0] < field.values.shape[0]
        assert small.extent[0] >= -113.01
        assert small.extent[3] <= 43.71

    def test_no_overlap_raises(self, tmp_path):
        field = self._field(tmp_path)
        with pytest.raises(ValueError, match="does not overlap"):
            field.subset((10.0, 11.0, 10.0, 11.0))


class TestNaming:
    @pytest.mark.parametrize("given, want", [("KGJX", "GJX"), ("GJX", "GJX"), ("kgjx", "GJX")])
    def test_icao_to_ridge_site(self, given, want):
        assert iem.iem_site(given) == want

    def test_directory_url(self):
        url = iem.ridge_dir_url("KGJX", datetime(2025, 10, 12), "N0B")
        assert url.endswith("/2025/10/12/GIS/ridge/GJX/N0B")

    def test_unknown_product_is_refused(self):
        with pytest.raises(KeyError, match="N0B"):
            iem.ridge_dir_url("KGJX", datetime(2025, 10, 12), "ZZZ")

    def test_only_elevation_one_is_offered(self):
        # RIDGE carries the lowest tilt only. A test says so, because a future
        # reader will want 1.2 deg and needs to know it is not here.
        assert {spec[0] for spec in iem.RIDGE_PRODUCTS.values()} == {0.5}


def test_plan_dataset_shape(tmp_path):
    png, wld = _write_scan(tmp_path, np.full((5, 7), 140))
    field = iem.read_ridge(png, wld)
    dataset = iem.to_plan_dataset(field)
    assert dataset["refl_beam"].shape == (5, 7)
    assert dataset["latitude"].shape == (5, 7)
    assert dataset["longitude"].shape == (5, 7)


@pytest.mark.live
@pytest.mark.skipif(
    not os.environ.get("RUN_LIVE_RADAR"),
    reason="set RUN_LIVE_RADAR=1 to hit the real IEM RIDGE archive",
)
class TestLive:
    """Needs mesonet.agron.iastate.edu.

    Opt-in, matching the ``RUN_LIVE_HERBIE`` / ``RUN_LIVE_NCEI`` gates in
    ``test_wrf_staging.py``.  These pass from a DTN; they fail in a restricted
    sandbox, which is a fact about the sandbox and not about the archive.
    """

    def test_scans_exist_for_the_ashley_window(self):
        scans = iem.available_scans(
            "KGJX", datetime(2025, 10, 12, 2, 0), datetime(2025, 10, 12, 3, 0)
        )
        assert len(scans) >= 10  # ~4-5 minute cadence

    def test_observed_sweep_over_ashley_valley(self):
        field = iem.observed_sweep(
            "KGJX", datetime(2025, 10, 12, 2, 20),
            extent=(-109.75, -109.25, 40.28, 40.62),
        )
        assert field is not None
        finite = field.values[np.isfinite(field.values)]
        assert finite.size > 100
        assert 40.0 < finite.max() < 70.0

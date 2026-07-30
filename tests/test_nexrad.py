"""Unit tests for brc_tools.radar.nexrad.

The sweep-selection and geolocation logic is exercised against a stub volume that
mimics MetPy's ``Level2File`` structure, so no binary fixture and no network are
needed.  The network functions are marked ``live`` -- the archive hosts are not
reachable from a restricted sandbox, and a live fetch belongs in a DTN job.
"""

import os
from datetime import datetime
from types import SimpleNamespace

import numpy as np
import pytest

from brc_tools.radar import nexrad as nx
from brc_tools.radar.beam import beam_height_asl
from brc_tools.radar.sites import get_site


def _ray(az_deg: float, el_deg: float, moments: dict):
    """A ray shaped like MetPy's: index 0 the data header, index 4 the moments."""
    hdr = SimpleNamespace(az_angle=az_deg, el_angle=el_deg)
    return (hdr, None, None, None, moments)


def _moment(num_gates=10, gate_width=0.25, first_gate=2.125, value=35.0, seed=None):
    """``(header, data)`` for one moment.  Widths are in KM, as MetPy reports."""
    hdr = SimpleNamespace(num_gates=num_gates, gate_width=gate_width, first_gate=first_gate)
    data = np.full(num_gates, float(value))
    if seed is not None:
        data = data + seed
    return (hdr, data)


def make_volume(elevations=(0.5, 1.2, 2.4), n_az=8, *, moment=b"REF", stid="KGJX"):
    """A stub with the same duck type as ``metpy.io.Level2File``."""
    sweeps = []
    for el in elevations:
        rays = [
            _ray(az, el, {moment: _moment(value=30.0 + 10.0 * el)})
            for az in np.linspace(0.0, 315.0, n_az)
        ]
        sweeps.append(rays)
    return SimpleNamespace(
        sweeps=sweeps, stid=stid, dt=datetime(2025, 10, 12, 2, 25), vol_hdr=None
    )


class TestSweepSelection:
    def test_elevations_are_reported(self):
        assert nx.sweep_elevations(make_volume()) == pytest.approx([0.5, 1.2, 2.4])

    @pytest.mark.parametrize("want, expect", [(0.5, 0.5), (1.2, 1.2), (2.5, 2.4)])
    def test_picks_the_nearest_sweep(self, want, expect):
        sweep = nx.sweep_from_level2(make_volume(), want)
        assert sweep.elevation_deg == pytest.approx(expect)

    def test_refuses_a_distant_tilt_rather_than_substituting(self):
        # A beam-matched comparison is only meaningful at the tilt you asked for,
        # so a VCP lacking it must be an error, not a quiet substitution.
        with pytest.raises(ValueError, match="no sweep within"):
            nx.sweep_from_level2(make_volume(), 0.0)

    def test_the_error_lists_what_is_available(self):
        with pytest.raises(ValueError, match=r"0\.5.*1\.2.*2\.4"):
            nx.sweep_from_level2(make_volume(), 8.0)

    def test_missing_moment_reports_what_is_carried(self):
        vol = make_volume(moment=b"REF")
        with pytest.raises(ValueError, match="carries the VEL moment"):
            nx.sweep_from_level2(vol, 0.5, moment=b"VEL")

    def test_split_cut_velocity_is_found_on_the_sibling_sweep(self):
        """Real VCPs pair the low tilts: one sweep has REF, its twin has VEL.

        A KGJX volume reads [-0.04, -0.04, 0.44, 0.44, 1.49, 1.49, ...]. Taking
        simply the nearest sweep would land a velocity request on the
        reflectivity half and fail, which matters because the observed couplet
        this whole module exists to place is a VELOCITY signature.
        """
        ref_only = make_volume(elevations=(0.44,), moment=b"REF")
        vel_only = make_volume(elevations=(0.44,), moment=b"VEL")
        vol = SimpleNamespace(
            sweeps=[ref_only.sweeps[0], vel_only.sweeps[0]],
            stid="KGJX",
            dt=datetime(2025, 10, 12, 2, 25),
        )
        assert nx.sweep_from_level2(vol, 0.5, moment=b"REF").moment == "REF"
        assert nx.sweep_from_level2(vol, 0.5, moment=b"VEL").moment == "VEL"

    def test_real_vcp_tilts_resolve_the_chk_beam_angles(self):
        # Nominal spotter-reported angles are 0.0 / 0.5 / 1.2 deg, but a real VCP
        # scans -0.04 / 0.44 / 1.49. The default tolerance must still resolve all
        # three, and the sweep must report the ACTUAL tilt, since that is what the
        # beam height has to be computed from.
        vol = make_volume(elevations=(-0.04, 0.44, 1.49, 2.5))
        assert nx.sweep_from_level2(vol, 0.0).elevation_deg == pytest.approx(-0.04)
        assert nx.sweep_from_level2(vol, 0.5).elevation_deg == pytest.approx(0.44)
        assert nx.sweep_from_level2(vol, 1.2).elevation_deg == pytest.approx(1.49)

    def test_empty_volume_raises(self):
        with pytest.raises(ValueError, match="no sweeps"):
            nx.sweep_from_level2(SimpleNamespace(sweeps=[]), 0.5)

    def test_metadata_travels(self):
        sweep = nx.sweep_from_level2(make_volume(), 0.5)
        assert sweep.site_id == "KGJX"
        assert sweep.valid_time == datetime(2025, 10, 12, 2, 25)
        assert sweep.moment == "REF"

    def test_bytes_station_id_is_decoded(self):
        vol = make_volume()
        vol.stid = b"KGJX"
        assert nx.sweep_from_level2(vol, 0.5).site_id == "KGJX"

    def test_azimuths_come_back_sorted(self):
        vol = make_volume()
        vol.sweeps[0] = list(reversed(vol.sweeps[0]))
        az = nx.sweep_from_level2(vol, 0.5).azimuth_deg
        assert np.all(np.diff(az) > 0)

    def test_ranges_are_metres_not_kilometres(self):
        # MetPy reports gate_width/first_gate in km; a missed conversion here
        # would put every gate 1000x too close and silently wreck the geolocation.
        sweep = nx.sweep_from_level2(make_volume(), 0.5)
        assert sweep.range_m[0] == pytest.approx(2125.0)
        assert sweep.range_m[1] - sweep.range_m[0] == pytest.approx(250.0)

    def test_masked_gates_become_nan(self):
        vol = make_volume()
        hdr, data = vol.sweeps[0][0][4][b"REF"]
        masked = np.ma.masked_array(data, mask=[True] + [False] * (data.size - 1))
        vol.sweeps[0][0][4][b"REF"] = (hdr, masked)
        values = nx.sweep_from_level2(vol, 0.5).values
        assert np.isnan(values).any()


class TestGeolocation:
    def test_shapes_and_keys(self):
        sweep = nx.sweep_from_level2(make_volume(n_az=12), 0.5)
        geo = nx.geolocate_sweep(sweep, "KGJX")
        assert set(geo) == {"latitude", "longitude", "height_asl_m"}
        for arr in geo.values():
            assert arr.shape == sweep.values.shape

    def test_site_is_taken_from_the_sweep_when_omitted(self):
        sweep = nx.sweep_from_level2(make_volume(stid="KGJX"), 0.5)
        a = nx.geolocate_sweep(sweep)
        b = nx.geolocate_sweep(sweep, get_site("KGJX"))
        np.testing.assert_allclose(a["latitude"], b["latitude"])

    def test_due_north_ray_increases_latitude_only(self):
        vol = make_volume(elevations=(0.5,), n_az=4)
        # Replace azimuths with cardinal directions.
        for ray, az in zip(vol.sweeps[0], (0.0, 90.0, 180.0, 270.0)):
            ray[0].az_angle = az
        sweep = nx.sweep_from_level2(vol, 0.5)
        geo = nx.geolocate_sweep(sweep, "KGJX")
        site = get_site("KGJX")
        north, east = geo["latitude"][0], geo["longitude"][0]
        assert np.all(np.diff(north) > 0)  # heading north, latitude climbs
        assert north[-1] > site.lat
        assert np.all(np.diff(geo["longitude"][1]) > 0)  # heading east

    def test_heights_match_the_beam_module(self):
        # Observed and simulated must sit on the SAME surface, so this has to be
        # the same function the model sampler uses, not a parallel formula.
        sweep = nx.sweep_from_level2(make_volume(), 1.2)
        geo = nx.geolocate_sweep(sweep, "KGJX")
        site = get_site("KGJX")
        expected = beam_height_asl(sweep.range_m, sweep.elevation_deg, site.alt_m)
        np.testing.assert_allclose(geo["height_asl_m"][0], expected)

    def test_longitudes_are_wrapped(self):
        sweep = nx.sweep_from_level2(make_volume(), 0.5)
        lon = nx.geolocate_sweep(sweep, "KGJX")["longitude"]
        assert lon.min() >= -180.0 and lon.max() <= 180.0


class TestCacheAndNaming:
    def test_cache_dir_respects_the_env_var(self, tmp_path, monkeypatch):
        monkeypatch.setenv(nx.CACHE_ENV, str(tmp_path / "radar"))
        assert nx.cache_dir() == tmp_path / "radar"

    def test_cache_dir_default_is_outside_any_checkout(self, monkeypatch):
        monkeypatch.delenv(nx.CACHE_ENV, raising=False)
        path = nx.cache_dir()
        assert "gits" not in path.parts
        assert path.parts[-3:] == (".cache", "brc-tools", "nexrad")

    @pytest.mark.parametrize(
        "name, expect",
        [
            ("KGJX20251012_021500_V06", datetime(2025, 10, 12, 2, 15, 0)),
            # The GCS mirror's hourly bundles use 14 consecutive digits with no
            # separator; missing this silently drops every key from that mirror.
            (
                "NWS_NEXRAD_NXL2DPBL_KGJX_20251012020000_20251012025959.tar",
                datetime(2025, 10, 12, 2, 0, 0),
            ),
            ("Level2_KGJX_20251012_0215.ar2v", None),
            ("nonsense", None),
        ],
    )
    def test_time_from_name(self, name, expect):
        assert nx._time_from_name(name) == expect

    def test_fetch_skips_an_already_cached_file(self, tmp_path):
        dest = tmp_path / "KGJX20251012_021500_V06"
        dest.write_bytes(b"already here")
        # No network: if it tried to download, requests would fail on this URL.
        out = nx.fetch_volume(
            "https://example.invalid/KGJX20251012_021500_V06", dest_dir=tmp_path
        )
        assert out == dest
        assert out.read_bytes() == b"already here"


@pytest.mark.live
@pytest.mark.skipif(
    not os.environ.get("RUN_LIVE_RADAR"),
    reason="set RUN_LIVE_RADAR=1 to hit the real Level-II archive",
)
class TestLive:
    """Needs a reachable Level-II mirror; run from a DTN, not a sandbox.

    Opt-in, matching the ``RUN_LIVE_HERBIE`` / ``RUN_LIVE_NCEI`` gates in
    ``test_wrf_staging.py``: a default ``pytest tests/`` must not depend on a
    network.  These two currently fail even from a DTN -- anonymous access to the
    AWS bucket (:data:`~brc_tools.radar.nexrad.DEFAULT_MIRROR`) returns 403 from
    CHPC for every date tried, listing and object GET alike, while the GCS mirror
    is reachable but its coverage stops before Sept 2025.  That is the same
    dead end recorded in ``docs/nwp/NWP-SOURCE-MATRIX.md``, which is why the
    convective engine compares against IEM RIDGE Level-III instead.
    """

    def test_available_volumes_for_the_ashley_window(self):
        volumes = nx.available_volumes(
            "KGJX", datetime(2025, 10, 12, 2, 0), datetime(2025, 10, 12, 3, 0)
        )
        assert volumes, "expected KGJX volumes in the 02-03Z window"
        assert all(url.startswith("http") for _, url in volumes)

    def test_nearest_volume(self):
        found = nx.nearest_volume("KGJX", datetime(2025, 10, 12, 2, 25))
        assert found is not None


class TestMirrors:
    def test_known_mirrors_resolve(self):
        assert nx._mirror_url("aws").startswith("https://noaa-nexrad-level2")
        assert nx._mirror_url("gcs").startswith("https://storage.googleapis.com")

    def test_a_full_url_passes_through(self):
        assert nx._mirror_url("https://example.org/bucket") == "https://example.org/bucket"

    def test_unknown_mirror_names_the_alternatives(self):
        with pytest.raises(KeyError, match="aws"):
            nx._mirror_url("azure")

    def test_default_mirror_is_the_authoritative_archive(self):
        # The GCS mirror's coverage stops before Sept 2025, so it must not be the
        # default for a case that could be any date.
        assert nx.DEFAULT_MIRROR == "aws"


class TestKeyListingParser:
    """The ListBucketResult dialect, against the real shape both mirrors return."""

    @staticmethod
    def _xml(keys, truncated=False):
        items = "".join(f"<Contents><Key>{k}</Key></Contents>" for k in keys)
        return (
            "<?xml version='1.0' encoding='UTF-8'?>"
            "<ListBucketResult xmlns='http://doc.s3.amazonaws.com/2006-03-01'>"
            f"<Name>bucket</Name><IsTruncated>{str(truncated).lower()}</IsTruncated>"
            f"{items}</ListBucketResult>"
        ).encode()

    def test_parses_keys(self, monkeypatch):
        payload = self._xml(
            [
                "2025/10/12/KGJX/KGJX20251012_021500_V06",
                "2025/10/12/KGJX/KGJX20251012_022000_V06",
            ]
        )
        calls = []

        class FakeResponse:
            content = payload

            def raise_for_status(self):
                return None

        def fake_get(url, params=None, timeout=None):
            calls.append((url, params))
            return FakeResponse()

        import requests

        monkeypatch.setattr(requests, "get", fake_get)
        keys = nx.list_keys("2025/10/12/KGJX/", mirror="aws")
        assert len(keys) == 2
        assert keys[0].endswith("_021500_V06")
        assert calls[0][1]["prefix"] == "2025/10/12/KGJX/"

    def test_empty_listing_is_not_an_error(self, monkeypatch):
        # An empty prefix is exactly what an out-of-coverage date returns, and it
        # must read as "nothing there", not as a failure.
        class FakeResponse:
            content = TestKeyListingParser._xml([])

            def raise_for_status(self):
                return None

        import requests

        monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse())
        assert nx.list_keys("2025/10/12/KGJX/", mirror="gcs") == []


class TestTarBundles:
    def test_iterates_members(self, tmp_path):
        # The GCS mirror publishes hourly .tar bundles rather than single volumes.
        import io
        import tarfile

        bundle = tmp_path / "NWS_NEXRAD_NXL2DPBL_KGJX_20251012020000_20251012025959.tar"
        with tarfile.open(bundle, "w") as archive:
            for name, blob in (("KGJX20251012_020318_V06", b"one"),
                               ("KGJX20251012_020845_V06", b"two")):
                info = tarfile.TarInfo(name)
                info.size = len(blob)
                archive.addfile(info, io.BytesIO(blob))

        members = list(nx.iter_tar_volumes(bundle))
        assert [n for n, _ in members] == [
            "KGJX20251012_020318_V06",
            "KGJX20251012_020845_V06",
        ]
        assert members[0][1] == b"one"

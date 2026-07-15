"""Offline tests for the NASA CMR + GIBS MODIS context renderer."""

from __future__ import annotations

import hashlib
import io
import json
from datetime import datetime, timezone

import matplotlib
import numpy as np
import pytest

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from brc_tools.satellite import modis

TARGET = datetime(2013, 2, 2, 18, tzinfo=timezone.utc)
BBOX = (-111.8, 39.2, -108.2, 41.5)


def _entry(platform: str) -> dict:
    if platform == "Terra":
        short = "MOD02HKM"
        granule_id = "MOD02HKM.A2013033.1815.061.example.hdf"
        start, end = "2013-02-02T18:15:00.000Z", "2013-02-02T18:20:00.000Z"
        concept, collection = "G-TERRA", "C-TERRA"
    else:
        short = "MYD02HKM"
        granule_id = "MYD02HKM.A2013033.1955.061.example.hdf"
        start, end = "2013-02-02T19:55:00.000Z", "2013-02-02T20:00:00.000Z"
        concept, collection = "G-AQUA", "C-AQUA"
    return {
        "producer_granule_id": granule_id,
        "time_start": start,
        "time_end": end,
        "id": concept,
        "collection_concept_id": collection,
        "day_night_flag": "DAY",
        "links": [
            {
                "rel": "http://esipfed.org/ns/fedsearch/1.1/data#",
                "href": f"https://example.test/{short}.hdf",
            },
            {
                "rel": "http://esipfed.org/ns/fedsearch/1.1/browse#",
                "href": f"https://example.test/{short}.jpg",
            },
        ],
    }


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    pixels = np.zeros((12, 18, 3), dtype=float)
    pixels[..., 0] = np.linspace(0.1, 0.9, 18)
    pixels[..., 1] = 0.65
    pixels[..., 2] = np.linspace(0.9, 0.2, 18)
    plt.imsave(buffer, pixels, format="png")
    return buffer.getvalue()


class FakeResponse:
    def __init__(self, *, payload=None, content=b"", url="https://example.test"):
        self._payload = payload
        self.content = content
        self.url = url
        self.headers = {"Content-Type": "image/png" if content else "application/json"}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self):
        self.calls = []
        self.png = _png_bytes()

    def get(self, url, *, params, timeout, headers):
        self.calls.append((url, dict(params), timeout, dict(headers)))
        if url == modis.CMR_GRANULES_URL:
            platform = "Terra" if params["short_name"] == "MOD02HKM" else "Aqua"
            return FakeResponse(payload={"feed": {"entry": [_entry(platform)]}})
        if url == modis.GIBS_WMS_URL:
            request_url = modis._prepared_url(url, params)
            return FakeResponse(content=self.png, url=request_url)
        raise AssertionError(f"unexpected URL {url}")


class NoNetworkSession:
    def get(self, *args, **kwargs):
        raise AssertionError("network should not be used in offline mode")


def test_parse_utc_requires_explicit_zone():
    assert modis.parse_utc("2013-02-02T18:00:00Z") == TARGET
    assert modis.parse_utc("2013-02-02T11:00:00-07:00") == TARGET
    with pytest.raises(ValueError, match="explicit UTC offset"):
        modis.parse_utc("2013-02-02T18:00:00")


def test_discovery_selects_closest_midpoint_and_reuses_cache(tmp_path):
    session = FakeSession()
    result = modis.discover_granules(
        TARGET, BBOX, cache_dir=tmp_path, session=session
    )

    assert result.selected.platform == "Terra"
    assert result.selected.time_start.hour == 18
    assert result.selected.offset_seconds(TARGET) == 17.5 * 60
    assert result.center == pytest.approx((-110.0, 40.35))
    assert len(result.candidates) == 2
    assert len(session.calls) == 2
    assert result.cache_file.exists()

    cached = modis.discover_granules(
        TARGET,
        BBOX,
        cache_dir=tmp_path,
        offline=True,
        session=NoNetworkSession(),
    )
    assert cached.selected.producer_granule_id == result.selected.producer_granule_id


def test_gibs_product_layer_and_offline_cache(tmp_path):
    session = FakeSession()
    granule = modis._granule_from_entry(_entry("Terra"), "Terra")
    image = modis.fetch_gibs_image(
        granule,
        BBOX,
        "snow-false-color",
        width=720,
        cache_dir=tmp_path,
        session=session,
    )

    assert image.layer == "MODIS_Terra_CorrectedReflectance_Bands721"
    assert image.date == "2013-02-02"
    assert image.sha256 == hashlib.sha256(image.content).hexdigest()
    assert image.cache_file.exists()
    gibs_call = session.calls[-1]
    assert gibs_call[1]["SRS"] == "EPSG:4326"
    assert gibs_call[1]["TIME"] == "2013-02-02"

    cached = modis.fetch_gibs_image(
        granule,
        BBOX,
        "snow-false-color",
        width=720,
        cache_dir=tmp_path,
        offline=True,
        session=NoNetworkSession(),
    )
    assert cached.sha256 == image.sha256


def test_render_context_writes_figure_and_provenance(tmp_path, monkeypatch):
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
    session = FakeSession()
    stem = tmp_path / "output" / "modis_uinta_20130202_1800"
    result = modis.render_context(
        TARGET,
        BBOX,
        stem,
        width=720,
        products=("true-color", "snow-false-color"),
        formats=("png", "pdf"),
        markers={"Vernal": (-109.529, 40.455)},
        cache_dir=tmp_path / "cache",
        session=session,
    )

    assert stem.with_suffix(".png").exists()
    assert stem.with_suffix(".pdf").exists()
    assert result.provenance_path.exists()
    provenance = json.loads(result.provenance_path.read_text())
    assert provenance["selected_granule"]["platform"] == "Terra"
    assert provenance["selected_granule"]["midpoint_utc"] == "2013-02-02T18:17:30Z"
    assert provenance["gibs"]["time_dimension"].startswith("calendar date")
    assert provenance["rendering"]["resolved_height_pixels"] == 460
    assert provenance["rendering"]["markers"]["Vernal"]["lon"] == -109.529
    assert provenance["rendering"]["runtime_versions"]["requests"]
    assert set(provenance["rendering"]["outputs"]) == {
        "modis_uinta_20130202_1800.png",
        "modis_uinta_20130202_1800.pdf",
    }

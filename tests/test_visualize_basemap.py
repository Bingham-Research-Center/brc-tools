"""Unit tests for brc_tools.visualize.basemap (fail-soft reference overlays)."""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from brc_tools.visualize import basemap as bm


def test_add_reference_overlays_never_raises_without_data(monkeypatch):
    # Force "no staged shapefiles" and assert the overlay is a silent no-op.
    monkeypatch.setattr(bm, "_load_records", lambda layer, res: ())
    fig, ax = plt.subplots()
    bm.add_reference_overlays(ax, (-110.0, -109.0, 40.0, 41.0),
                              layers={"states": True, "roads": True,
                                      "rivers": True, "lakes": True})
    plt.close(fig)


def test_add_reference_overlays_all_off_is_noop():
    fig, ax = plt.subplots()
    # all layers off -> returns immediately, even if shapely/cartopy were present
    bm.add_reference_overlays(ax, (-110.0, -109.0, 40.0, 41.0),
                              layers={"states": False, "roads": False,
                                      "rivers": False, "lakes": False})
    plt.close(fig)


def test_draw_waypoints_skips_out_of_extent_and_declutters():
    fig, ax = plt.subplots()
    wps = {
        "A": {"lat": 40.5, "lon": -109.5},   # inside
        "B": {"lat": 40.51, "lon": -109.51},  # inside but ~collides with A -> label suppressed
        "Far": {"lat": 10.0, "lon": 10.0},    # far outside extent -> dropped entirely
    }
    bm.draw_waypoints(ax, wps, extent=(-110.0, -109.0, 40.0, 41.0))
    texts = {t.get_text().strip() for t in ax.texts}
    assert "A" in texts
    assert "Far" not in texts          # out-of-extent waypoint not labelled
    assert "B" not in texts            # decluttered (too close to A)
    # A and B markers are still both plotted (only the label was suppressed)
    assert len(ax.lines) == 2
    plt.close(fig)

"""Unit tests for brc_tools.visualize.domains (synthetic outlines)."""

from __future__ import annotations

from _wrf_synthetic import make_synthetic_wrf

from brc_tools.nwp import wrf_output as wo
from brc_tools.visualize.domains import plot_domain_boxes


def test_plot_domain_boxes_writes_png(tmp_path, monkeypatch):
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
    ds = make_synthetic_wrf(nz=4, ny=10, nx=10)
    outline = wo.domain_outline(ds, label="d01")
    out = tmp_path / "domains.png"

    result = plot_domain_boxes(
        [outline],
        out,
        terrain=wo.surface_field(ds, "HGT"),
        terrain_lonlat=(wo.surface_field(ds, "XLONG"), wo.surface_field(ds, "XLAT")),
        waypoints={"horsepool": {"lat": 40.3, "lon": -109.7}},
        title="Nested domains",
    )

    assert result == out
    assert out.exists() and out.stat().st_size > 0

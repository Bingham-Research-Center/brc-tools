"""Unit tests for brc_tools.visualize.crosssection (synthetic sections)."""

from __future__ import annotations

from _wrf_synthetic import make_synthetic_wrf

from brc_tools.nwp import wrf_output as wo
from brc_tools.visualize.crosssection import (
    _waypoints_on_section,
    plot_wrf_section,
    plot_wrf_section_difference,
)


def test_waypoints_on_section_keeps_near_and_drops_far():
    ds = make_synthetic_wrf(nz=8, ny=12, nx=16)
    sec = wo.build_section(ds, "EW")
    mid = sec.lon_line.size // 2
    on_line = {"lat": float(sec.lat_line[mid]), "lon": float(sec.lon_line[mid])}
    far = {"lat": float(sec.lat_line[mid]) + 5.0, "lon": float(sec.lon_line[mid]) + 5.0}
    hits = _waypoints_on_section(sec, {"On": on_line, "Off": far}, max_offset_km=5.0)
    names = {name for _d, name, _off, _terr in hits}
    assert "On" in names and "Off" not in names


def test_plot_wrf_section_ew_with_insets(tmp_path, monkeypatch):
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
    ds = make_synthetic_wrf(nz=8, ny=12, nx=16)
    sec = wo.build_section(ds, "EW")
    out = tmp_path / "section_ew.png"

    result = plot_wrf_section(
        sec, out, title="EW section", locator_terrain=wo.surface_field(ds, "HGT")
    )

    assert result == out
    assert out.exists() and out.stat().st_size > 0


def test_plot_wrf_section_ns_no_shallow_inset(tmp_path, monkeypatch):
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
    ds = make_synthetic_wrf(nz=8, ny=12, nx=16)
    sec = wo.build_section(ds, "NS")
    out = tmp_path / "section_ns.png"

    plot_wrf_section(sec, out, title="NS section", shallow_inset=False)

    assert out.exists() and out.stat().st_size > 0


def test_plot_wrf_section_difference_writes_png(tmp_path, monkeypatch):
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
    ds = make_synthetic_wrf(nz=8, ny=12, nx=16)
    sec_a = wo.build_section(ds, "EW")
    sec_b = wo.build_section(ds, "EW")
    out = tmp_path / "section_diff.png"

    plot_wrf_section_difference(sec_a, sec_b, out, title="A - B", limit=5.0)

    assert out.exists() and out.stat().st_size > 0

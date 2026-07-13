"""Unit tests for brc_tools.visualize.heatdeficit (field + difference maps)."""

from __future__ import annotations

import numpy as np
import pytest
from _wrf_synthetic import make_synthetic_wrf

from brc_tools.nwp import wrf_output as wo
from brc_tools.visualize.heatdeficit import (
    plot_heatdeficit_difference,
    plot_heatdeficit_field,
)
from brc_tools.visualize.style import get_style


@pytest.fixture
def grid():
    ds = make_synthetic_wrf(nz=8, ny=10, nx=10)
    return {
        "lon": wo.surface_field(ds, "XLONG"),
        "lat": wo.surface_field(ds, "XLAT"),
        "hgt": wo.surface_field(ds, "HGT"),
        "field": wo.heat_deficit_field(ds, 1900.0) / 1e6,
    }


def test_plot_heatdeficit_field_writes_png(tmp_path, monkeypatch, grid):
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
    out = tmp_path / "hd_field.png"

    plot_heatdeficit_field(
        grid["lon"], grid["lat"], grid["field"], out,
        style=get_style("heat_deficit"), crest_terrain=grid["hgt"], crest_m=1900.0,
        title="heat deficit", waypoints={"Site": {"lat": 40.3, "lon": -109.7}},
    )

    assert out.exists() and out.stat().st_size > 0


def test_plot_heatdeficit_difference_writes_png(tmp_path, monkeypatch, grid):
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
    out = tmp_path / "hd_diff.png"

    # a - b with a scaled-down b so the difference is non-trivial
    plot_heatdeficit_difference(
        grid["lon"], grid["lat"], grid["field"], grid["field"] * 0.5, out,
        limit=2.5, crest_terrain=grid["hgt"], crest_m=1900.0, title="GFS - NAM",
    )

    assert out.exists() and out.stat().st_size > 0


def test_difference_adaptive_limit(tmp_path, monkeypatch, grid):
    """limit=None must not raise (adaptive symmetric limit path)."""
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
    out = tmp_path / "hd_diff_adaptive.png"
    zeros = np.zeros_like(grid["field"])

    plot_heatdeficit_difference(
        grid["lon"], grid["lat"], grid["field"], zeros, out,
        limit=None, title="adaptive",
    )

    assert out.exists() and out.stat().st_size > 0

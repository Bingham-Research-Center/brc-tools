from __future__ import annotations

import numpy as np

from brc_tools.visualize.grid import (
    plot_grid_field,
    plot_vertical_section,
    terrain_contour_levels,
)


def test_terrain_contour_levels_are_bounded() -> None:
    terrain = np.linspace(1350.0, 2600.0, 100).reshape(10, 10)

    levels = terrain_contour_levels(terrain)

    assert levels is not None
    assert 4 <= len(levels) <= 34


def test_plot_grid_field_writes_png(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
    y, x = np.mgrid[0:12, 0:14]
    lon = -110.0 + x * 0.01
    lat = 40.0 + y * 0.01
    field = np.sin(x / 4.0) + np.cos(y / 3.0)
    terrain = 1500.0 + x * 8.0 + y * 5.0
    out = tmp_path / "grid.png"

    result = plot_grid_field(
        lon,
        lat,
        field,
        out,
        title="Synthetic grid",
        colorbar_label="value",
        contour=terrain,
        contour_levels=terrain_contour_levels(terrain),
        contour_label=True,
        wind_u=np.ones_like(field),
        wind_v=np.zeros_like(field),
    )

    assert result == out
    assert out.exists()
    assert out.stat().st_size > 0


def test_plot_vertical_section_writes_png(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
    distance = np.linspace(0.0, 40.0, 20)
    height = np.tile(np.linspace(0.0, 2500.0, 12).reshape(-1, 1), (1, distance.size))
    field = 290.0 + height / 600.0 + np.sin(distance / 10.0)
    pblh = 500.0 + 50.0 * np.cos(distance / 8.0)
    out = tmp_path / "section.png"

    result = plot_vertical_section(
        distance,
        height,
        field,
        out,
        title="Synthetic section",
        colorbar_label="K",
        line_y=pblh,
        line_label="PBLH",
    )

    assert result == out
    assert out.exists()
    assert out.stat().st_size > 0

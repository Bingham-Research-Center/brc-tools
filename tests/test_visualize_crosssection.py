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


def test_reflectivity_curtain_from_a_convective_run(tmp_path, monkeypatch):
    """A reflectivity section rides the same machinery as a wind section.

    Exercises the whole additive path: REFL_10CM -> WRFPlane.refl ->
    NWPSection.refl2d -> the curtain's "refl" shade key.
    """
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
    from brc_tools.nwp.wrf_section import extract_wrf_section
    from brc_tools.visualize.style import get_style
    from brc_tools.visualize.wrf_curtain import plot_wrf_curtain

    ds = make_synthetic_wrf(nz=8, ny=12, nx=16, convective=True)
    sec = extract_wrf_section(ds, (40.05, -109.95), (40.45, -109.35), n_points=40)
    assert sec.refl2d is not None
    assert sec.refl2d.shape == sec.theta2d.shape

    out = tmp_path / "refl_curtain.png"
    result = plot_wrf_curtain(sec, out, shade="refl", style=get_style("refl"),
                              title="reflectivity section", y_top_m=9000.0)
    assert result == out
    assert out.exists() and out.stat().st_size > 0


def test_reflectivity_shade_is_refused_without_reflectivity(tmp_path, monkeypatch):
    """A drainage run has no REFL_10CM, and the failure must be explicit."""
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
    import pytest as _pytest

    from brc_tools.nwp.wrf_section import extract_wrf_section
    from brc_tools.visualize.wrf_curtain import plot_wrf_curtain

    ds = make_synthetic_wrf(nz=6, ny=8, nx=8)  # convective=False
    sec = extract_wrf_section(ds, (40.05, -109.95), (40.35, -109.45), n_points=20)
    assert sec.refl2d is None
    with _pytest.raises(ValueError, match="carries no refl2d"):
        plot_wrf_curtain(sec, tmp_path / "x.png", shade="refl", title="t")


# --------------------------------------------------------------------------- #
# saying which wind, in which plane
# --------------------------------------------------------------------------- #
def test_every_shade_has_a_field_a_style_and_a_label():
    """The tables are keyed on the same names on purpose.  A shade with a field
    but no style is how a theta curtain came out on a 0-15 m/s wind ramp: the
    engine fell back to a fixed key rather than failing.

    A shade is sourced either from a stored section attribute (``SHADE_FIELD``)
    or computed from the section (``SHADE_DERIVED``); the union is what must
    match the style and label tables.
    """
    from brc_tools.visualize import wrf_curtain as wc
    from brc_tools.visualize.style import VAR_STYLES

    sourced = set(wc.SHADE_FIELD) | set(wc.SHADE_DERIVED)
    assert sourced == set(wc.SHADE_STYLE) == set(wc.SHADE_LABEL)
    # A shade must come from exactly one place: both would make which one wins a
    # question about statement order in the renderer.
    assert not (set(wc.SHADE_FIELD) & set(wc.SHADE_DERIVED))
    for shade, key in wc.SHADE_STYLE.items():
        assert key in VAR_STYLES, f"shade {shade!r} maps to unknown style {key!r}"


def test_shade_style_keys_are_distinct_for_distinct_quantities():
    """Wind speed, theta and reflectivity must not share a scale -- that shared
    fallback is exactly what made a curtain lie about its own units."""
    from brc_tools.visualize.wrf_curtain import shade_style_key

    keys = {shade: shade_style_key(shade) for shade in ("speed", "theta", "refl", "w")}
    assert len(set(keys.values())) == 4


def test_wind_shade_labels_state_magnitude_or_component():
    from brc_tools.visualize.wrf_curtain import SHADE_LABEL

    assert "magnitude" in SHADE_LABEL["speed"]
    assert "into page" in SHADE_LABEL["normal"]
    assert "toward B" in SHADE_LABEL["along"]


def test_orientation_note_names_the_bearing_and_the_into_page_direction():
    """A signed fill is uninterpretable without knowing which way the viewer
    faces, so the stamp must resolve 'into the page' to a compass direction."""
    import types

    import numpy as np

    from brc_tools.visualize.wrf_curtain import orientation_note

    west_to_east = types.SimpleNamespace(
        lat_line=np.array([40.2, 40.2]), lon_line=np.array([-110.0, -109.5]))
    note = orientation_note(west_to_east)
    assert "090" in note
    assert note.endswith("into page = N")

    south_to_north = types.SimpleNamespace(
        lat_line=np.array([40.0, 40.5]), lon_line=np.array([-110.0, -110.0]))
    assert orientation_note(south_to_north).endswith("into page = W")

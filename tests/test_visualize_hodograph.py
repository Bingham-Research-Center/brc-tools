"""Unit tests for brc_tools.visualize.hodograph."""

import numpy as np
import pytest

from brc_tools.visualize.hodograph import plot_hodograph


def _profile(n=40, top_m=9000.0):
    z = np.linspace(10.0, top_m, n)
    speed = 3.0 + 4.0 * z / 1000.0
    angle = np.deg2rad(200.0 + 60.0 * z / top_m)
    return -speed * np.sin(angle), -speed * np.cos(angle), z


def test_renders_and_returns_the_path(tmp_path, monkeypatch):
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
    u, v, z = _profile()
    out = tmp_path / "hodo.png"
    result = plot_hodograph(u, v, z, out, title="test hodograph")
    assert result == out
    assert out.exists() and out.stat().st_size > 0


def test_storm_motions_are_optional_and_both_can_be_drawn(tmp_path, monkeypatch):
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
    u, v, z = _profile()
    out = tmp_path / "hodo_motions.png"
    plot_hodograph(
        u, v, z, out, title="with motions",
        storm_motion=(14.8, 7.4),
        observed_motion=(11.3, 4.1),
        observed_motion_label="observed",
        annotation="0-6 km shear 31.6 m/s",
    )
    assert out.stat().st_size > 0


def test_max_height_truncates_the_trace(tmp_path, monkeypatch):
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
    u, v, z = _profile(top_m=15000.0)
    a = tmp_path / "deep.png"
    b = tmp_path / "shallow.png"
    plot_hodograph(u, v, z, a, title="deep", max_height_m=15000.0)
    plot_hodograph(u, v, z, b, title="shallow", max_height_m=3000.0)
    # A shorter trace with tighter rings makes a materially different figure.
    assert a.stat().st_size != b.stat().st_size


def test_mismatched_shapes_are_rejected(tmp_path):
    u, v, z = _profile()
    with pytest.raises(ValueError, match="share a shape"):
        plot_hodograph(u[:-1], v, z, tmp_path / "x.png", title="t")


def test_too_few_points_below_the_cap_is_rejected(tmp_path):
    u, v, z = _profile(n=10, top_m=9000.0)
    with pytest.raises(ValueError, match="at least two finite points"):
        plot_hodograph(u, v, z, tmp_path / "x.png", title="t", max_height_m=5.0)


def test_nans_are_tolerated(tmp_path, monkeypatch):
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
    u, v, z = _profile()
    u = u.copy()
    u[5] = np.nan
    out = tmp_path / "hodo_nan.png"
    plot_hodograph(u, v, z, out, title="with a gap")
    assert out.stat().st_size > 0

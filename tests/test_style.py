"""Unit tests for brc_tools.visualize.style."""

from __future__ import annotations

import numpy as np

from brc_tools.visualize import style as st


def test_registry_theta_range_is_clipped_low_layer():
    s = st.get_style("theta")
    assert (s.vmin, s.vmax) == (270.0, 300.0)
    assert s.cmap == "RdYlBu_r"


def test_diff_style_is_symmetric_diverging():
    d = st.diff_style("theta")
    assert d.diverging is True
    assert d.cmap == "RdBu_r"
    assert d.vmin == -5.0 and d.vmax == 5.0
    assert d.label.startswith(r"$\Delta$")


def test_diff_style_feedback_uses_smaller_limit():
    assert st.diff_style("theta", feedback=True).vmax == 3.0


def test_diff_style_explicit_limit():
    d = st.diff_style("snow_depth", limit=0.1)
    assert (d.vmin, d.vmax) == (-0.1, 0.1)


def test_shared_range_robust():
    a = np.array([0.0, 1.0, 2.0, 3.0, 100.0])  # outlier trimmed by 99th pct
    lo, hi = st.shared_range(a, np.array([0.5, 1.5]))
    assert lo <= 0.5
    assert hi < 100.0


def test_symmetric_limit_capped():
    a = np.array([-2.0, 5.0, -8.0])
    assert st.symmetric_limit(a, cap=4.0) == 4.0


def test_resolve_style_default_is_fixed():
    assert st.resolve_style("theta_2m") == st.get_style("theta_2m")


def test_resolve_style_autoscale_nulls_limits():
    base = st.get_style("theta_2m")
    a = st.resolve_style("theta_2m", autoscale=True)
    assert a.vmin is None and a.vmax is None
    assert a.cmap == base.cmap and a.label == base.label


def test_resolve_style_override_wins_over_autoscale():
    ov = st.VarStyle("viridis", "custom", vmin=1.0, vmax=2.0)
    got = st.resolve_style("theta_2m", overrides={"theta_2m": ov}, autoscale=True)
    assert got is ov


def test_use_publication_style_sets_rcparams(tmp_path, monkeypatch):
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
    import matplotlib

    st.use_publication_style(dpi=300)
    assert matplotlib.rcParams["savefig.dpi"] == 300
    assert matplotlib.rcParams["mathtext.fontset"] == "stixsans"
    assert matplotlib.rcParams["font.family"] == ["sans-serif"]
    assert "Nimbus Sans" in matplotlib.rcParams["font.sans-serif"]

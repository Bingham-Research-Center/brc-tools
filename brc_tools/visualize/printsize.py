"""Figures drawn at the size they are printed, for A4 reports with 2 cm margins.

Figures drawn 12-18 in wide with 6-10 pt text and shrunk to a 6.69 in text block print
their text at 2-5 pt (the gigawatts September report).  Here a figure is created at its
printed width and ``save`` refuses one that is wider than the text block, carries text
below ``MIN_PT``, or stacks two y-scales on one panel.  Include the result unscaled.

    from brc_tools.visualize.printsize import use_style, figure, save
    use_style()
    fig, ax = figure("text", 3.6)
    ...
    save(fig, "fig_example", outdir)

Colour rules (validated with the dataviz palette checker on a light surface):
  * ``CATEGORICAL`` is a fixed order for lines and bars: assign in sequence, never cycle past 8.
  * magnitude -> ``SEQ`` (one hue, more is darker); signed quantity -> ``DIV`` (blue-grey-red).
  * one y-axis per panel: two measures are two panels.  Text is ink, never the series colour.

First written for ub-wx drainage-canyons-gigawatts (analysis/iter5/_style.py); graduated
here when a second experiment needed it.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LightSource, LinearSegmentedColormap  # noqa: E402

TEXT_W = 6.69          # in: A4, 2 cm margins (\textwidth = 170 mm)
HALF_W = 3.25          # in: two figures side by side
MAX_H = 9.0            # in: leaves room for a caption
MIN_PT = 9.0
BASE_PT = 10.0

SURFACE, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
CATEGORICAL = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948")
_BLUES = ("#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b")
SEQ = LinearSegmentedColormap.from_list("print_seq", _BLUES)
SEQ_R = SEQ.reversed()
DIV = LinearSegmentedColormap.from_list("print_div", ("#0d366b", "#256abf", "#86b6ef", "#f0efec", "#f0a3a2",
                                                      "#d03b3b", "#7f1d1d"))
HILLSHADE = LinearSegmentedColormap.from_list("print_hill", ("#8d8b85", "#fcfcfb"))


def use_style(dpi: int = 300, base_pt: float = BASE_PT) -> None:
    try:
        from brc_tools.visualize.style import use_publication_style
        use_publication_style(dpi=dpi)
    except Exception:                       # noqa: BLE001 - the overrides below stand alone
        pass
    plt.rcParams.update({
        "font.size": base_pt, "axes.titlesize": base_pt + 0.5, "axes.labelsize": base_pt,
        "xtick.labelsize": base_pt - 1, "ytick.labelsize": base_pt - 1, "legend.fontsize": base_pt - 1,
        "legend.title_fontsize": base_pt - 1, "figure.titlesize": base_pt + 1,
        "figure.dpi": 110, "savefig.dpi": dpi, "savefig.bbox": "standard",
        "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white",
        "figure.constrained_layout.use": True,
        "text.color": INK, "axes.labelcolor": INK, "axes.titlecolor": INK,
        "xtick.color": INK2, "ytick.color": INK2, "axes.edgecolor": AXIS, "axes.linewidth": 0.8,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "grid.linestyle": "-",
        "axes.axisbelow": True, "lines.linewidth": 1.6, "lines.markersize": 5.5,
        "legend.frameon": False, "pdf.fonttype": 42,
        "axes.prop_cycle": matplotlib.cycler(color=list(CATEGORICAL)),
    })


def figure(width: str | float = "text", height: float = 3.6, **subplot_kw):
    """A figure at its printed size; ``width`` is 'text', 'half' or inches (<= TEXT_W)."""
    w = {"text": TEXT_W, "half": HALF_W}.get(width, width)
    if w > TEXT_W + 1e-6 or height > MAX_H + 1e-6:
        raise ValueError(f"figure {w:.2f} x {height:.2f} in exceeds the printed page ({TEXT_W} x {MAX_H} in)")
    return plt.subplots(figsize=(w, height), **subplot_kw)


def small_text(fig) -> list[tuple[float, str]]:
    bad = []
    for t in fig.findobj(matplotlib.text.Text):
        s = t.get_text().strip()
        if s and t.get_visible() and t.get_fontsize() < MIN_PT - 1e-6:
            bad.append((round(float(t.get_fontsize()), 1), s[:40]))
    return bad


def twin_axes(fig) -> int:
    boxes = [tuple(round(v, 4) for v in ax.get_position().bounds) for ax in fig.axes
             if ax.get_visible() and ax.get_label() != "<colorbar>"]
    return len(boxes) - len(set(boxes))


def save(fig, name: str, outdir: str | Path, *, fmt: str | tuple[str, ...] = ("pdf", "png"), strict: bool = True) -> Path:
    """Write ``outdir/name.<fmt>`` at the figure's own size after the checks; returns the
    first path.  pdflatex takes the .pdf; the .png is for looking at."""
    w, h = fig.get_size_inches()
    if w > TEXT_W + 1e-6:
        raise ValueError(f"{name}: {w:.2f} in wide; the text block is {TEXT_W} in")
    fig.canvas.draw()
    bad = small_text(fig)
    if bad and strict:
        raise ValueError(f"{name}: text below {MIN_PT} pt: {bad[:6]}")
    if twin_axes(fig) and strict:
        raise ValueError(f"{name}: a panel has two y-scales; use two panels")
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    fmts = (fmt,) if isinstance(fmt, str) else tuple(fmt)
    paths = [outdir / f"{name}.{f}" for f in fmts]
    for p in paths:
        fig.savefig(p)
    plt.close(fig)
    print(f"saved {paths[0]} ({w:.2f} x {h:.2f} in)", flush=True)
    return paths[0]


def hillshade(z: np.ndarray, res: float, *, azdeg: float = 315.0, altdeg: float = 40.0, exag: float = 1.5) -> np.ndarray:
    """Hillshade in [0, 1] of a north-up DEM (NaN filled with the minimum)."""
    zz = np.where(np.isnan(z), np.nanmin(z), z)
    return LightSource(azdeg=azdeg, altdeg=altdeg).hillshade(zz, vert_exag=exag, dx=res, dy=res)

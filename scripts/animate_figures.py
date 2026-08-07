"""Stitch a WRF figure-engine output root's PNG frames into GIFs (Pillow only).

    python scripts/animate_figures.py --root <figures root> --config <case.toml> --domain 2

Both sweep engines (``wrf_winds.py``, ``wrf_convective.py``) write

    <root>/<YYYYMMDD_HHMM>/<view>/<kind>_<YYYYMMDD_HHMM>.png

so a "kind" -- one panel type for one view, e.g. ``topdown_theta_2m_d02`` -- is a
frame series scattered across the time directories.  This gathers each kind and
writes ``<root>/animations/<kind>.gif``, a sibling of the time directories.

Follows the convention already set by ``ub-wx``'s ``cases/*/animate.py``: Pillow
only (no ffmpeg, no imageio), scaled to a 1000 px width, 400 ms a frame, looping.
The view tag is part of the kind, so two views of the same nest never collide.

**A GIF paces frames evenly in wall-clock time regardless of their valid times.**
A run swept hourly for its first half and every 15 minutes for its second animates
as though the whole night ran at one speed.  ``--require-even`` refuses to write a
GIF whose frames are not evenly spaced rather than let that pass silently.
"""
from __future__ import annotations

import argparse
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from PIL import Image

from brc_tools.nwp import wrf_engine as we

#: Frame stamp the engines append to every figure name, and the time-directory name.
STAMP_FMT = "%Y%m%d_%H%M"
STAMP_RE = re.compile(r"^(?P<kind>.+)_(?P<stamp>\d{8}_\d{4})$")

TARGET_W = 1000
DURATION_MS = 400


def _scaled(path: Path) -> Image.Image:
    im = Image.open(path).convert("RGB")
    w, h = im.size
    return im.resize((TARGET_W, round(h * TARGET_W / w))) if w > TARGET_W else im


def _time_dirs(root: Path) -> list[Path]:
    """The ``<YYYYMMDD_HHMM>`` directories, oldest first.

    Matched by parsing the name, not by glob: ``animations`` and any other sibling
    the engine or a user drops in the root must not be walked as a valid time.
    """
    out = []
    for d in root.iterdir():
        if not d.is_dir():
            continue
        try:
            datetime.strptime(d.name, STAMP_FMT)
        except ValueError:
            continue
        out.append(d)
    return sorted(out, key=lambda p: p.name)


def _view_of(kind: str, tags: list[str]) -> str | None:
    """Which view tag a time-directory-level frame belongs to, or None.

    The ``aux`` family writes into the time directory rather than a per-view
    subdirectory, carrying its view in the name instead
    (``plan_llws_d02_ashley_aux_<stamp>.png``).  ``tags`` must be longest-first:
    ``d02`` is a prefix of ``d02_ashley``, so a shortest-first scan would file every
    zoomed frame under the full nest.
    """
    padded = f"{kind}_"
    for tag in tags:
        if f"_{tag}_" in padded:
            return tag
    return None


def _tags_for_domain(config: Path, domain: int) -> set[str]:
    """View tags belonging to one nest, read from the case TOML.

    A tag does not carry its domain -- ``d02_ashley`` is a zoomed view of domain 2 --
    so "the innermost domain" is only answerable from the config that defined it.
    """
    cfg = we.load_config(config)
    tags = {d.get("tag", f"d{d['domain']:02d}") for d in cfg.get("domains", [])
            if int(d["domain"]) == domain}
    if not tags:
        known = sorted({int(d["domain"]) for d in cfg.get("domains", [])})
        raise SystemExit(f"no [[domains]] entry with domain = {domain}; config has {known}")
    return tags


def _even_spacing(stamps: list[datetime]) -> tuple[bool, str]:
    """Whether frames are evenly spaced, and a description of the cadence."""
    if len(stamps) < 3:
        return True, "n/a"
    gaps = {int((b - a).total_seconds() // 60) for a, b in zip(stamps, stamps[1:])}
    if len(gaps) == 1:
        return True, f"{gaps.pop()} min"
    return False, f"mixed {sorted(gaps)} min"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True, type=Path,
                    help="figure output root (holds the <YYYYMMDD_HHMM> directories)")
    ap.add_argument("--config", type=Path,
                    help="case TOML, so --domain can be resolved to its view tags")
    ap.add_argument("--domain", type=int,
                    help="restrict to the views of this nest (needs --config)")
    ap.add_argument("--view", action="append", metavar="TAG",
                    help="restrict to this view tag; repeatable, overrides --domain")
    ap.add_argument("--kind", action="append", metavar="SUBSTR",
                    help="only kinds containing this substring; repeatable")
    ap.add_argument("--width", type=int, default=TARGET_W, help="scaled frame width (px)")
    ap.add_argument("--duration", type=int, default=DURATION_MS, help="ms per frame")
    ap.add_argument("--min-frames", type=int, default=2,
                    help="skip a kind with fewer frames than this")
    ap.add_argument("--require-even", action="store_true",
                    help="refuse a kind whose frames are unevenly spaced in time")
    ap.add_argument("--dry-run", action="store_true",
                    help="list the GIFs that would be written, then exit")
    a = ap.parse_args()

    root: Path = a.root
    if not root.is_dir():
        raise SystemExit(f"no such figure root: {root}")
    repo = Path(__file__).resolve().parents[1]
    if root.resolve() == repo or repo in root.resolve().parents:
        raise SystemExit(f"refusing to write animations into the checkout ({repo})")

    if a.view:
        tags = set(a.view)
    elif a.domain is not None:
        if not a.config:
            raise SystemExit("--domain needs --config to resolve its view tags")
        tags = _tags_for_domain(a.config, a.domain)
    else:
        tags = set()

    times = _time_dirs(root)
    if not times:
        raise SystemExit(f"no <YYYYMMDD_HHMM> directories under {root}")

    # kind -> {valid time: frame path}.  A dict, not a list: re-rendering a time
    # must replace that frame rather than duplicate it in the series.
    series: dict[str, dict[datetime, Path]] = defaultdict(dict)
    by_length = sorted(tags, key=len, reverse=True)
    for tdir in times:
        for vdir in sorted(p for p in tdir.iterdir() if p.is_dir()):
            if tags and vdir.name not in tags:
                continue
            for png in vdir.glob("*.png"):
                m = STAMP_RE.match(png.stem)
                if not m:
                    continue
                series[m.group("kind")][
                    datetime.strptime(m.group("stamp"), STAMP_FMT)] = png
        # The aux family writes at the time-directory level, not under a view dir,
        # so these would otherwise be missed entirely -- and they are the densest
        # series there is, at the auxiliary stream's own cadence.
        for png in tdir.glob("*.png"):
            m = STAMP_RE.match(png.stem)
            if not m:
                continue
            if tags and _view_of(m.group("kind"), by_length) is None:
                continue
            series[m.group("kind")][
                datetime.strptime(m.group("stamp"), STAMP_FMT)] = png

    if a.kind:
        series = {k: v for k, v in series.items()
                  if any(s in k for s in a.kind)}
    if not series:
        raise SystemExit(f"no frames matched under {root}"
                         + (f" for views {sorted(tags)}" if tags else ""))

    out_dir = root / "animations"
    print(f"[views] {', '.join(sorted(tags)) if tags else 'all'}")
    print(f"[kinds] {len(series)} -> {out_dir}")

    written = skipped = 0
    for kind in sorted(series):
        stamps = sorted(series[kind])
        frames = [series[kind][s] for s in stamps]
        even, cadence = _even_spacing(stamps)
        if len(frames) < a.min_frames:
            print(f"  [skip] {kind}: {len(frames)} frame(s)")
            skipped += 1
            continue
        if a.require_even and not even:
            print(f"  [skip] {kind}: {cadence} cadence")
            skipped += 1
            continue
        note = "" if even else f"  <- {cadence}, plays at an even pace anyway"
        if a.dry_run:
            print(f"  {kind}.gif: {len(frames)} frames, "
                  f"{stamps[0]:{STAMP_FMT}}..{stamps[-1]:{STAMP_FMT}}{note}")
            written += 1
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        imgs = [_scaled(f) for f in frames]
        out = out_dir / f"{kind}.gif"
        imgs[0].save(out, save_all=True, append_images=imgs[1:],
                     duration=a.duration, loop=0, optimize=True)
        for im in imgs:
            im.close()
        print(f"  {out.name}: {len(imgs)} frames, {out.stat().st_size / 1e6:.1f} MB{note}")
        written += 1

    verb = "would write" if a.dry_run else "wrote"
    print(f"[tally] {verb} {written} GIF(s), skipped {skipped} -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

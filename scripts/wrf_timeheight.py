#!/usr/bin/env python
"""Render time-height sections at ``tslist`` stations from a WRF run.

The third engine's missing axis.  ``wrf_winds.py`` and ``wrf_convective.py`` both
render one valid time at a time; a cold pool, a drainage surge and a morning
break-up are *events*, and the question about them is usually **when**.  This
engine answers that from a stream the run already wrote and nothing plotted: the
per-station ``tslist`` column profiles, at model-timestep cadence, in text files
a thousandth the size of the history stream.

Everything case-specific lives in a TOML, shared with ``wrf_winds.py`` -- same
``[case]`` block, plus ``[[timeheight]]`` entries.  Schema: ``docs/WRF-WINDS.md``.

    python scripts/wrf_timeheight.py --config <case.toml> [--start ...] [--end ...]
"""
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brc_tools.nwp import wrf_engine as we  # noqa: E402
from brc_tools.nwp import wrf_tslist as wts  # noqa: E402
from brc_tools.visualize import timeheight as th  # noqa: E402
from brc_tools.visualize.style import use_publication_style  # noqa: E402

DEFAULT_FIELDS = ("theta", "theta_change", "theta_grad", "speed")
_TIME_FMT = we.TIME_FMT


def _kinds_for(fields) -> tuple[str, ...]:
    """The profile kinds needed by ``fields``, plus what the figure itself needs.

    ``PH`` is always read (it is the height axis) and ``TH`` almost always, since
    theta contours ride on every panel; ``UU``/``VV`` come along whenever barbs
    are wanted.  Reading a kind that turns out to be unused costs one text file.
    """
    kinds = {"PH", "TH"}
    for f in fields:
        kinds.update(th.FIELD_REQUIRES.get(f, ()))
    return tuple(sorted(kinds))


def _subsample(times, stride_min: float) -> slice:
    """A stride over the time axis giving roughly ``stride_min`` between columns.

    The raw axis is one row per model time step -- 33 601 of them over 28 hours
    on the run this was written for.  Drawn in full that is 33 601 quads per
    model level, which renders slowly and resolves nothing a five-minute column
    does not: the figure is 12 inches wide and the display grid is finite.
    """
    if len(times) < 2:
        return slice(None)
    dt_s = (times[1] - times[0]).total_seconds()
    if dt_s <= 0:
        return slice(None)
    return slice(None, None, max(1, int(round(stride_min * 60.0 / dt_s))))


def render_station(cfg: dict, spec: dict, run_dir: Path, out_root: Path,
                   args, ledger) -> int:
    key = spec["key"]
    domain = int(spec.get("domain", 2))
    prefix = str(spec["station"])
    fields = tuple(spec.get("fields", DEFAULT_FIELDS))
    kinds = _kinds_for(fields)

    paths = [wts.ts_path(run_dir, prefix, domain, k) for k in kinds]
    missing = [p for p in paths if not p.exists()]
    if missing:
        print(f"[SKIP] {key}: {missing[0].name} not written by this run")
        ledger.note(we.ABSENT, f"{missing[0].name} absent",
                    family="timeheight", domain=domain, var=key)
        return 0

    profiles = wts.read_ts_profiles(run_dir, prefix, domain, kinds=kinds)
    header = profiles["header"]
    times = list(profiles["valid_times"])

    start = we._as_time(args.start)
    end = we._as_time(args.end)
    keep = [i for i, t in enumerate(times)
            if (start is None or t >= start) and (end is None or t <= end)]
    if not keep:
        print(f"[SKIP] {key}: no times in the requested window")
        ledger.note(we.ABSENT, "no times in window", family="timeheight",
                    domain=domain, var=key)
        return 0
    step = _subsample(times, float(spec.get("stride_min", args.stride_min)))
    idx = keep[step]

    times_sel = [times[i] for i in idx]
    # The station's own model terrain, from the profile header -- not the
    # requested elevation, which is the tslist input and can differ from the
    # column the model actually sampled by tens of metres over this terrain.
    height = profiles["PH"][idx] - float(header.elevation_m)
    theta = profiles["TH"][idx]
    wind = ((profiles["UU"][idx], profiles["VV"][idx])
            if spec.get("wind", True) and "UU" in profiles and "VV" in profiles
            else None)

    label = spec.get("label", key)
    span = f"{times_sel[0]:%d %HZ}-{times_sel[-1]:%d %HZ}"
    base = (f"d{domain:02d} | {label} ({prefix}) | "
            f"{header.elevation_m:.0f} m | {span}")
    an = " | ".join(x for x in (cfg["case"].get("annotation", ""),
                                f"tslist {len(idx)} columns",
                                f"init {times[0]:%Y-%m-%d %H:%MZ}") if x)
    out_dir = out_root / "timeheight" / f"d{domain:02d}_{prefix}"
    made = 0
    for field in fields:
        try:
            values = th.derive_field({k: profiles[k][idx] for k in kinds}, field)
        except KeyError as exc:
            print(f"[SKIP] {key} {field}: {exc}")
            ledger.note(we.ABSENT, str(exc), family="timeheight",
                        domain=domain, var=f"{key}_{field}")
            continue
        st = we.style_for(cfg, th.FIELD_STYLE[field])

        def _draw(path, field=field, values=values, st=st):
            th.plot_time_height(
                times_sel, height, values, path,
                style=st, cbar_label=th.FIELD_LABEL[field],
                title=we.compose_title(we.SOURCE_WRF, base, th.FIELD_LABEL[field]),
                annotation=an,
                theta=theta if spec.get("theta_contours", True) else None,
                theta_interval=float(spec.get("theta_interval", 1.0)),
                wind=wind,
                y_top_m=float(spec.get("y_top_m", 2000.0)),
                y_bottom_m=float(spec.get("y_bottom_m", 0.0)),
                local_offset_h=spec.get("local_offset_h",
                                        cfg["case"].get("local_offset_h")),
                local_label=str(cfg["case"].get("local_label", "local")),
                dpi=args.dpi)

        made += ledger.emit(
            out_dir / f"timeheight_{field}_{prefix}_d{domain:02d}.png",
            _draw, sources=paths, family="timeheight", domain=domain,
            var=f"{key}_{field}",
        )
    print(f"  {key}: {made} figures -> {out_dir}")
    return made


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", required=True, type=Path, help="case TOML")
    ap.add_argument("--run-dir", type=Path, help="override the TOML run directory")
    ap.add_argument("--station", action="append",
                    help="restrict to this [[timeheight]] key (repeatable)")
    ap.add_argument("--start", metavar="TIME",
                    help=f"clip the time axis at or after this ({_TIME_FMT.replace('%', '%%')})")
    ap.add_argument("--end", metavar="TIME", help="clip the time axis at or before this")
    ap.add_argument("--stride-min", type=float, default=5.0,
                    help="minutes between drawn columns (default 5); the raw "
                         "tslist cadence is one row per model time step")
    ap.add_argument("--output-dir", type=Path, help="override the output root")
    ap.add_argument("--dpi", type=int, default=200)
    we.add_output_arguments(ap)
    args = ap.parse_args()

    cfg = we.load_config(args.config, index=("timeheight",))
    if args.run_dir:
        cfg["case"]["run_dir"] = args.run_dir
    run_dir = cfg["case"]["run_dir"]
    if not run_dir.is_dir():
        raise SystemExit(f"run directory not found: {run_dir}")

    specs = [s for s in cfg.get("timeheight", [])
             if not args.station or s["key"] in args.station]
    if not specs:
        raise SystemExit("no [[timeheight]] entries selected; add some to the TOML")

    use_publication_style(dpi=args.dpi)
    out_root = we.output_root(cfg, args.output_dir, config_path=args.config)
    if args.report:
        return we.report_coverage(out_root)

    ledger = we.FigureLedger(skip_existing=args.skip_existing, dry_run=args.dry_run)
    print(f"[run ] {run_dir}")
    total = 0
    for spec in specs:
        try:
            total += render_station(cfg, spec, run_dir, out_root, args, ledger)
        except Exception as exc:
            print(f"[ERR] timeheight {spec.get('key')}: {exc}")
            traceback.print_exc()
            ledger.note(we.ERROR, f"{type(exc).__name__}: {exc}",
                        family="timeheight", var=spec.get("key"))

    if args.dry_run:
        print(f"\n[dry ] {ledger.count(we.PLANNED)} figure(s) would be rendered:")
        for line in ledger.planned_lines():
            print(line)
    else:
        manifest = ledger.write_manifest(
            out_root, config_path=args.config, run_dir=run_dir, argv=sys.argv[1:])
        print(f"[man ] {manifest}")
    print(f"\nDone. {total} figures -> {out_root}")
    print(ledger.summarise())
    return ledger.exit_code(allow_errors=args.allow_errors)


if __name__ == "__main__":
    raise SystemExit(main())

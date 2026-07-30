"""Shared plumbing for the TOML-driven WRF figure engines.

Both ``scripts/wrf_winds.py`` (basin winds) and ``scripts/wrf_convective.py``
(convective diagnostics) are thin engines over a case TOML, and they need the same
four things: load the config and index its list-of-tables, resolve a waypoint
group, resolve a colour scale with the case's overrides applied, and decide which
valid times to render.  Those live here so the two engines cannot drift apart --
in particular so a fix to the sweep-a-still-writing-run time logic lands in both.

Not merged with ``brc_tools.nwp.wrf_figures``: that engine belongs to the pelican
publication figure set, is pinned by an evidence packet, and uses frozen
dataclasses rather than plain dicts.  Two engines, one set of plumbing.
"""

from __future__ import annotations

import os
import tomllib
from datetime import datetime, timedelta
from pathlib import Path

from brc_tools.nwp import wrf_section as ws
from brc_tools.visualize.style import VarStyle, get_style

#: Group storage, overridable.  Figures must never land in the checkout.
DEFAULT_OUTPUT_ROOT = Path(
    os.environ.get(
        "BRC_TOOLS_OUTPUT_DIR",
        "/uufs/chpc.utah.edu/common/home/lawson-group6/jrlawson/brc-tools-output",
    )
)

#: Natural-Earth overlay layers a case TOML may switch on under ``[map]``.
MAP_LAYERS = ("states", "counties", "roads", "rivers", "lakes")

#: ``--valid`` / display format.
TIME_FMT = "%Y-%m-%d_%H:%M"


def load_config(path: str | Path, *, index: tuple[str, ...] = ()) -> dict:
    """Read a case TOML, expanding ``run_dir`` and indexing its list-of-tables.

    ``index`` names top-level arrays of tables to turn into ``key``-keyed lookup
    dicts, stored as ``cfg["_<name>"]`` -- so ``index=("sections", "beams")``
    makes ``cfg["_sections"]`` and ``cfg["_beams"]``.  A ``[[domains]]`` entry then
    refers to them by key instead of repeating their definitions.
    """
    with open(path, "rb") as handle:
        cfg = tomllib.load(handle)
    case = cfg.get("case")
    if not case:
        raise SystemExit(f"{path}: missing a [case] table")
    if "run_dir" in case:
        case["run_dir"] = Path(os.path.expandvars(str(case["run_dir"]))).expanduser()
    for name in index:
        entries = cfg.get(name, [])
        missing = [e for e in entries if "key" not in e]
        if missing:
            raise SystemExit(f"{path}: every [[{name}]] entry needs a 'key'")
        cfg[f"_{name}"] = {e["key"]: e for e in entries}
    return cfg


def waypoints(group: str | None) -> dict:
    """Title-cased ``{name: {lat, lon}}`` for a ``lookups.toml`` waypoint group."""
    if not group:
        return {}
    from brc_tools.nwp.source import load_lookups

    lookups = load_lookups()
    try:
        names = lookups["waypoint_groups"][group]
    except KeyError:
        raise SystemExit(
            f"unknown waypoint_group {group!r}; known: "
            f"{sorted(lookups['waypoint_groups'])}"
        ) from None
    return {n.replace("_", " ").title(): lookups["waypoints"][n] for n in names}


def waypoint(name: str) -> dict:
    """One waypoint by ``lookups.toml`` name, so a case never carries coordinates."""
    from brc_tools.nwp.source import load_lookups

    lookups = load_lookups()
    try:
        return lookups["waypoints"][name]
    except KeyError:
        raise SystemExit(f"unknown waypoint {name!r} -- add it to lookups.toml") from None


def style_for(cfg: dict, var: str) -> VarStyle:
    """Resolve a variable's :class:`VarStyle`, applying ``[style.overrides.<var>]``.

    A case whose regime does not match the package default retunes it in its own
    TOML rather than in the shared table.
    """
    base = get_style(var)
    over = cfg.get("style", {}).get("overrides", {}).get(var)
    if not over:
        return base
    return VarStyle(
        cmap=over.get("cmap", base.cmap),
        label=over.get("label", base.label),
        vmin=float(over["vmin"]) if "vmin" in over else base.vmin,
        vmax=float(over["vmax"]) if "vmax" in over else base.vmax,
        extend=over.get("extend", base.extend),
        diverging=bool(over.get("diverging", base.diverging)),
    )


def add_time_arguments(parser) -> None:
    """Add the shared time-selection flags to an engine's argument parser."""
    parser.add_argument("--valid", help=f"exact valid time, {TIME_FMT.replace('%', '%%')}")
    parser.add_argument("--lead", type=int, help="minutes after init")
    parser.add_argument(
        "--hourly", action="store_true",
        help="sweep every whole-hour valid time written so far (= --every 60)",
    )
    parser.add_argument(
        "--every", type=int, metavar="MIN",
        help="sweep every valid time on a MIN-minute cadence; a domain lacking a "
             "given time is skipped for it",
    )
    parser.add_argument(
        "--all", dest="all_times", action="store_true",
        help="sweep every valid time at the run's native interval",
    )
    parser.add_argument(
        "--start", metavar="TIME",
        help=f"restrict a sweep to times at or after this ({TIME_FMT.replace('%', '%%')})",
    )
    parser.add_argument(
        "--end", metavar="TIME",
        help="restrict a sweep to times at or before this. Without --start/--end a "
             "1-minute sweep of a 5 h run is 301 times per domain, which is almost "
             "never what you want",
    )


def select_times(
    run_dir: str | Path,
    domains: list[int],
    *,
    valid: str | None = None,
    lead: int | None = None,
    hourly: bool = False,
    every: int | None = None,
    all_times: bool = False,
    start: str | datetime | None = None,
    end: str | datetime | None = None,
    times_for=None,
    label: str = "wrfout",
) -> list[datetime]:
    """Resolve which valid time(s) to render.

    The sweep forms (``hourly``/``every``/``all_times``) are the normal way to use
    an engine against a job still integrating; the single-time forms render one.

    A sweep takes the **union** across domains, not the intersection: a 3 km parent
    on hourly output and a 600 m nest on 1-minute output share only whole hours, so
    intersecting would throw away every sub-hourly frame the fine nest has.  Each
    domain then renders only the times it actually holds.

    ``times_for`` overrides how a domain's available times are discovered -- pass
    a high-cadence stream's lister to sweep that stream instead of the history.
    """
    lister = times_for or (lambda dom: ws.list_valid_times(run_dir, dom))
    per_domain = {d: set(lister(d)) for d in domains}

    # A domain that does not carry the requested stream is SKIPPED, not fatal.
    # Streams are per-domain in WRF: a run with `auxhist2_interval = 0, 1` writes
    # the high-cadence stream on the inner nest only, and letting that abort the
    # whole job means a parent domain listed for context kills the sweep.
    empty = [d for d, stamps in per_domain.items() if not stamps]
    for dom in empty:
        print(f"[SKIP] d{dom:02d} has no {label} times under {run_dir} -- domain dropped")
        per_domain.pop(dom)
    if not per_domain:
        raise SystemExit(
            f"no {label} times for any requested domain "
            f"({', '.join(f'd{d:02d}' for d in domains)}) under {run_dir}"
        )

    lo = _as_time(start)
    hi = _as_time(end)

    cadence = 60 if hourly else every
    if cadence or all_times:
        union = set().union(*per_domain.values())
        want = sorted(
            t for t in union
            if all_times or (t.second == 0 and cadence and t.minute % cadence == 0)
        )
        if lo or hi:
            before = len(want)
            want = [t for t in want if (lo is None or t >= lo) and (hi is None or t <= hi)]
            print(f"[time] window {lo or 'run start'} .. {hi or 'run end'} "
                  f"keeps {len(want)} of {before} {label} time(s)")
        if not want:
            raise SystemExit(
                f"no {label} time matches a {cadence}-minute cadence"
                + (" inside the requested window" if (lo or hi) else "")
            )
        how = "native" if all_times else f"{cadence}-min"
        print(f"[time] {len(want)} {label} time(s) at {how} cadence: "
              f"{want[0]:{TIME_FMT}} .. {want[-1]:{TIME_FMT}}")
        return want

    common = set.intersection(*per_domain.values())
    if valid:
        one = datetime.strptime(valid, TIME_FMT)
    elif lead is not None:
        one = ws.init_time(run_dir, min(domains)) + timedelta(minutes=lead)
    else:
        if not common:
            raise SystemExit(
                "no valid time is present on every requested domain: "
                + ", ".join(f"d{d:02d}={len(t)} times" for d, t in per_domain.items())
            )
        one = max(common)
        print(f"[time] latest common {label} time -> {one:{TIME_FMT}}")

    for dom, stamps in per_domain.items():
        if one not in stamps:
            print(f"[SKIP] d{dom:02d} has no {one:{TIME_FMT}} "
                  f"(latest {max(stamps):{TIME_FMT}}) -- domain dropped")
    return [one]


def output_root(cfg: dict, override: str | Path | None = None, *, config_path=None) -> Path:
    """Where figures go: CLI override, then the TOML, then group storage.

    Refuses a path inside **this package's checkout, or the case config's** -- the
    two repos a figure could plausibly pollute.  Deliberately not "any directory
    with a .git in it": a stray ``/tmp/.git`` would then veto every legitimate
    scratch path, which is exactly what happened the first time.
    """
    if override:
        root = Path(override)
    elif cfg["case"].get("output_dir"):
        root = Path(os.path.expandvars(str(cfg["case"]["output_dir"]))).expanduser()
    else:
        root = DEFAULT_OUTPUT_ROOT / cfg["case"]["slug"]

    resolved = root.resolve() if root.is_absolute() else (Path.cwd() / root).resolve()
    forbidden = [Path(__file__).resolve().parents[2]]  # the brc-tools checkout
    if config_path is not None:
        case_repo = _git_root(Path(config_path).resolve().parent)
        if case_repo is not None:
            forbidden.append(case_repo)
    for repo in forbidden:
        if resolved == repo or repo in resolved.parents:
            raise SystemExit(
                f"refusing to write figures into a repo checkout ({repo}); "
                "point output_dir or BRC_TOOLS_OUTPUT_DIR at scratch or group storage"
            )
    return root


def _as_time(value) -> datetime | None:
    """Accept a ``YYYY-MM-DD_HH:MM`` string, a datetime, or None."""
    if value is None or isinstance(value, datetime):
        return value
    return datetime.strptime(str(value), TIME_FMT)


def _git_root(start: Path) -> Path | None:
    """Nearest ancestor of ``start`` that holds a ``.git``, or None."""
    for candidate in [start, *start.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def overlays_from(cfg: dict) -> dict[str, bool]:
    """The ``[map]`` overlay switches, defaulted off."""
    section = cfg.get("map", {})
    return {layer: bool(section.get(layer, False)) for layer in MAP_LAYERS}

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

import hashlib
import json
import os
import tomllib
import traceback
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
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


# --------------------------------------------------------------------------- #
# the render ledger
# --------------------------------------------------------------------------- #
#: Statuses a :class:`FigureRecord` can carry.
RENDERED, SKIPPED, PLANNED, ERROR, ABSENT = (
    "rendered", "skipped", "planned", "error", "absent")


@dataclass
class FigureRecord:
    """One attempted figure: what it was, and what happened to it."""

    family: str
    status: str
    path: str | None = None
    domain: int | None = None
    valid: str | None = None
    var: str | None = None
    detail: str = ""


class FigureLedger:
    """The single chokepoint every figure passes through.

    Each family used to render on its own -- ``try: plot(...); made += 1`` /
    ``except: print("[ERR]")``, repeated at a dozen sites -- and report only an
    ``int``.  With no chokepoint there was nowhere to put idempotence, a record
    of what was produced, an error tally, or a dry run, so those read as four
    separate gaps when they are one missing seam.

    Robustness is unchanged: a failing figure is still caught and printed, and
    the sweep still continues.  What changes is that the job can now say what it
    did.
    """

    def __init__(self, *, skip_existing: bool = False, dry_run: bool = False):
        self.skip_existing = bool(skip_existing)
        self.dry_run = bool(dry_run)
        self.records: list[FigureRecord] = []

    # -- recording ---------------------------------------------------------- #
    def emit(
        self,
        out_path,
        render_fn,
        *,
        sources=(),
        family: str,
        domain: int | None = None,
        valid: datetime | None = None,
        var: str | None = None,
    ) -> int:
        """Render one figure, or decide not to.  Returns 1 if a file was written.

        ``render_fn`` takes the output path, so the decision to render happens
        before any work does.  ``sources`` are the files the figure derives from;
        with ``skip_existing`` a figure at least as new as all of them is kept.
        """
        out_path = Path(out_path)
        common = dict(family=family, domain=domain, var=var,
                      valid=None if valid is None else valid.strftime(TIME_FMT),
                      path=str(out_path))

        if self.dry_run:
            self.records.append(FigureRecord(status=PLANNED, **common))
            return 0
        if self.skip_existing and self.is_current(out_path, sources):
            self.records.append(FigureRecord(status=SKIPPED, **common))
            return 0
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            render_fn(out_path)
        except Exception as exc:  # one bad panel is not a lost run
            label = " ".join(str(x) for x in (family, var, out_path.name) if x)
            print(f"[ERR] {label}: {exc}")
            traceback.print_exc()
            self.records.append(
                FigureRecord(status=ERROR, detail=f"{type(exc).__name__}: {exc}", **common)
            )
            return 0
        self.records.append(FigureRecord(status=RENDERED, **common))
        return 1

    def note(self, status: str, detail: str, *, family: str,
             domain: int | None = None, valid: datetime | None = None,
             var: str | None = None) -> None:
        """Record something that produced no file -- an absent field, a bad key.

        Keeps the manifest honest about coverage: "not in this run" and "failed"
        are different answers to "where is my figure?", and ``find`` cannot tell
        them apart.
        """
        self.records.append(FigureRecord(
            family=family, status=status, detail=detail, domain=domain, var=var,
            valid=None if valid is None else valid.strftime(TIME_FMT),
        ))

    def is_current(self, out_path, sources) -> bool:
        """Whether ``out_path`` is at least as new as every source it derives from.

        A source rewritten by a later WRF run is newer than the figure, so the
        figure regenerates -- which is what makes this safe to use against a run
        that is still writing.
        """
        out_path = Path(out_path)
        if not out_path.exists():
            return False
        out_mtime = out_path.stat().st_mtime
        for src in sources:
            src = Path(src)
            if not src.exists() or src.stat().st_mtime > out_mtime:
                return False
        return True

    # -- reporting ---------------------------------------------------------- #
    def count(self, status: str) -> int:
        return sum(1 for r in self.records if r.status == status)

    @property
    def rendered(self) -> int:
        return self.count(RENDERED)

    @property
    def errors(self) -> int:
        return self.count(ERROR)

    def summarise(self) -> str:
        """The tally, printed last so it is the final line in a ``.err``."""
        parts = [f"{self.count(s)} {s}"
                 for s in (RENDERED, SKIPPED, PLANNED, ERROR, ABSENT)
                 if self.count(s)]
        return "[tally] " + (", ".join(parts) if parts else "nothing attempted")

    def planned_lines(self) -> list[str]:
        """One line per figure a dry run would have rendered."""
        return [f"  {r.family:9s} {r.valid or '-':16s} {r.path}"
                for r in self.records if r.status == PLANNED]

    def exit_code(self, *, allow_errors: bool = False) -> int:
        """0 only if the job actually did what it was asked.

        ``return 0 if total else 1`` could not tell 400-of-400 from 100-of-400:
        a job that failed three quarters of its figures looked like a success
        because *something* rendered.  Any error is now non-zero unless the
        caller opts out.
        """
        if self.errors and not allow_errors:
            return 1
        if self.dry_run:
            return 0
        return 0 if (self.rendered or self.count(SKIPPED)) else 1

    def write_manifest(self, out_root, *, config_path=None, run_dir=None,
                       argv=None, extra: dict | None = None) -> Path:
        """Write a machine-readable record of this job under ``out_root``.

        Named by ``SLURM_JOB_ID`` when there is one, because the normal way to
        sweep a case is several jobs into one output root and a single
        ``manifest.json`` would have them clobber each other.
        """
        out_root = Path(out_root)
        now = datetime.now(UTC)
        job = os.environ.get("SLURM_JOB_ID") or now.strftime("%Y%m%dT%H%M%SZ")
        payload = {
            "job": job,
            "written_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "config": None if config_path is None else str(config_path),
            "config_sha256": _sha256(config_path),
            "run_dir": None if run_dir is None else str(run_dir),
            "argv": list(argv) if argv is not None else None,
            "dry_run": self.dry_run,
            "skip_existing": self.skip_existing,
            "counts": {s: self.count(s)
                       for s in (RENDERED, SKIPPED, PLANNED, ERROR, ABSENT)},
            "figures": [asdict(r) for r in self.records],
            **(extra or {}),
        }
        out_root.mkdir(parents=True, exist_ok=True)
        path = out_root / f"manifest_{job}.json"
        path.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8")
        return path


def _sha256(path) -> str | None:
    """Hash a config so a manifest pins the exact settings a sweep ran under."""
    if path is None:
        return None
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def read_manifests(out_root) -> list[dict]:
    """Every ``manifest_*.json`` under ``out_root``, oldest first."""
    out_root = Path(out_root)
    found = []
    for path in sorted(out_root.glob("manifest_*.json")):
        try:
            found.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            print(f"[SKIP] unreadable manifest {path.name}: {exc}")
    return found


def report_coverage(out_root) -> int:
    """Print what a sweep actually produced, across every job in ``out_root``.

    This is the answer to "do we have all the plots?", which was previously
    answerable only by ``find`` -- and ``find`` cannot distinguish a figure that
    was never asked for from one that failed.
    """
    manifests = read_manifests(out_root)
    if not manifests:
        print(f"[report] no manifests under {out_root}")
        return 1

    print(f"[report] {len(manifests)} job(s) under {out_root}")
    totals: dict[str, int] = {}
    per_family: dict[str, dict[str, int]] = {}
    for man in manifests:
        argv = man.get("argv") or []
        counts = man.get("counts", {})
        summary = ", ".join(f"{v} {k}" for k, v in counts.items() if v)
        print(f"  job {man.get('job', '?')} [{man.get('written_utc', '?')}] "
              f"{summary or 'nothing'}")
        if argv:
            print(f"      argv: {' '.join(str(a) for a in argv)}")
        for rec in man.get("figures", []):
            status = rec.get("status", "?")
            totals[status] = totals.get(status, 0) + 1
            fam = per_family.setdefault(rec.get("family", "?"), {})
            fam[status] = fam.get(status, 0) + 1

    print("  per family:")
    for fam in sorted(per_family):
        detail = ", ".join(f"{v} {k}" for k, v in sorted(per_family[fam].items()))
        print(f"    {fam:9s} {detail}")
    print("  overall: " + (", ".join(f"{v} {k}" for k, v in sorted(totals.items()))
                           or "nothing"))
    failed = totals.get(ERROR, 0)
    if failed:
        print(f"  {failed} figure(s) errored -- see the job .err files")
    return 1 if failed else 0


def add_output_arguments(parser) -> None:
    """Flags shared by both engines for idempotence, dry runs and reporting."""
    parser.add_argument(
        "--skip-existing", action="store_true",
        help="keep figures already newer than every file they derive from; "
             "makes a re-run after adding one family cheap",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="print the figures that would be rendered, then exit",
    )
    parser.add_argument(
        "--allow-errors", action="store_true",
        help="exit 0 even if some figures failed (default: any failure exits 1)",
    )
    parser.add_argument(
        "--report", action="store_true",
        help="summarise coverage from the manifests already in the output root, "
             "then exit; renders nothing",
    )


def check_section_on_grid(plane, key: str, spec: dict, *, tag: str) -> bool:
    """Preflight an ``[[sections]]`` A->B transect against the nest it will cut.

    Returns ``False`` when the line misses the grid entirely, so the caller can
    skip it: a transect with no on-grid samples is a blank figure that costs an
    expensive read and tells a reader nothing.  A *partial* overlap warns and
    proceeds -- the on-grid part is real data, and
    :func:`~brc_tools.nwp.wrf_section.section_from_plane` blanks the rest rather
    than extruding the boundary column across it.

    Shared by both engines so the warning reads the same wherever it appears.
    ``WRF-WINDS.md`` used to warn about off-grid transects in prose only; this is
    that warning, made to actually fire.
    """
    cov = ws.section_coverage(
        plane, tuple(spec["a"]), tuple(spec["b"]),
        n_points=int(spec.get("n_points", 240)),
    )
    if cov.fully_inside:
        return True
    if cov.n_inside == 0:
        print(f"[SKIP] {tag} section {key!r}: {cov.describe()}")
        return False
    print(f"[WARN] {tag} section {key!r}: {cov.describe()} -- the off-grid part "
          "is blanked, not filled from the edge column")
    return True


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

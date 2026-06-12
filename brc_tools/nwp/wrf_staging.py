"""Stage WPS/WRF-ready GRIB inputs to scratch, with a provenance manifest.

This is the brc-tools side of the brc-wrf handoff: download raw GRIB (NOT
xarray) into a separate scratch directory laid out the way WPS expects, plus a
JSON manifest recording exactly what was staged and where it came from.

Primary source is the **GEFSv12 Reforecast** (Herbie model ``gefs_reforecast``),
the only Herbie-retrievable GEFS-family source covering historical dates such as
the Jan-2013 Uinta Basin test case (operational ``gefs`` only reaches back to
2017). The reforecast stores **one variable per file across many lead times**, so
a single download per ``variable_level`` token retrieves the whole forecast range
for that field.

Key design constraints (see ``docs`` / the WRF handoff doc):

* **Never** use ``NWPSource.fetch()`` — it calls ``H.xarray(..., remove_grib=True)``
  and deletes the raw GRIB. WPS needs the GRIB on disk, so this module uses
  ``Herbie.download()`` (which retains it).
* **Do not crop** the staged GRIB — WPS needs the full global grid plus margin.
* One ``download()`` per ``variable_level`` gets all lead times in the bucket
  (``fxx <= 240`` ⇒ directory ``Days:1-10``); ``fxx`` only selects the directory.
* Herbie writes into its own cache layout; we **move** files into the canonical
  ``<case>/<source>/<member>/`` layout.

The GFS/FNL "filler" source the user fuses in WPS (to supply the land-sea mask and
other fields the reforecast lacks) is a documented stub — see
:func:`stage_fnl_filler`.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import logging
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

import fasteners
from herbie import Herbie

from brc_tools.nwp._cache import purge_cached_files, validate_cached_grib
from brc_tools.nwp.source import _parse_init_time, load_lookups

LOG = logging.getLogger(__name__)

DEFAULT_SOURCE = "gefs_reforecast"
DEFAULT_CASE = "jan2013_basin_gefs"
DEFAULT_INIT = "2013-01-31 00Z"
DEFAULT_REGION = "uinta_basin_wide"
DEFAULT_FXX_WINDOW = (12, 48)
DEFAULT_INTERVAL_HOURS = 3
DEFAULT_SCRATCH_ROOT = Path(
    f"/scratch/general/vast/{os.environ.get('USER', 'user')}/wrf_inputs"
)
TOOL_NAME = "brc-tools"
MANIFEST_SCHEMA_VERSION = 1


@dataclass
class StagedFile:
    """Provenance record for one staged GRIB file."""

    source: str
    herbie_model: str
    member: str
    member_int: int
    init_time: str
    variable_level: str
    fxx_bucket: str
    lead_times: list[int]
    product: str
    local_path: str
    remote_url: str | None
    size_bytes: int
    sha256: str
    created_at: str


# ── token / path helpers ────────────────────────────────────────────────────


def _member_token(member_int: int) -> str:
    """Map a reforecast member integer to its file token.

    ``0`` -> ``"c00"`` (control); ``1..4`` -> ``"p01".."p04"``.
    """
    if member_int == 0:
        return "c00"
    if 1 <= member_int <= 4:
        return f"p{member_int:02d}"
    raise ValueError(
        f"GEFS reforecast member must be one of 0..4 (got {member_int!r})."
    )


def _fxx_bucket(fxx: int, breakpoint: int = 240) -> str:
    """Reforecast forecast-range directory for a lead time.

    ``fxx <= breakpoint`` -> ``"Days:1-10"``, else ``"Days:10-16"``.
    """
    return "Days:1-10" if fxx <= breakpoint else "Days:10-16"


def _canonical_staging_path(
    root: Path, case: str, source: str, member_token: str, filename: str
) -> Path:
    """``<root>/<case>/<source>/<member_token>/<filename>``."""
    return Path(root) / case / source / member_token / filename


def _reforecast_filename(variable_level: str, init_dt: dt.datetime, member_token: str) -> str:
    """The reforecast's own file name, e.g. ``tmp_2m_2013013100_c00.grib2``."""
    return f"{variable_level}_{init_dt:%Y%m%d%H}_{member_token}.grib2"


def _reforecast_remote_url(
    variable_level: str, init_dt: dt.datetime, member_token: str, bucket: str
) -> str:
    """Deterministic public S3 URL for a reforecast per-variable file."""
    return (
        "https://noaa-gefs-retrospective.s3.amazonaws.com/GEFSv12/reforecast/"
        f"{init_dt:%Y}/{init_dt:%Y%m%d%H}/{member_token}/{bucket}/"
        f"{variable_level}_{init_dt:%Y%m%d%H}_{member_token}.grib2"
    )


# ── provenance helpers ──────────────────────────────────────────────────────


def _sha256(path: Path, chunk: int = 1 << 20) -> str:
    """Streamed SHA-256 (never loads the whole GRIB into memory)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _git_sha() -> str | None:
    """Short-circuiting ``git rev-parse HEAD`` for the brc_tools package dir.

    Targets the package directory, not the cwd, because the staging output dir is
    on scratch (not a git repo). Returns ``None`` on any failure.
    """
    pkg_dir = Path(__file__).resolve().parent
    try:
        out = subprocess.run(
            ["git", "-C", str(pkg_dir), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def _tool_version() -> str | None:
    """``brc-tools`` package version, or ``None`` if not installed."""
    try:
        from importlib.metadata import PackageNotFoundError, version

        return version(TOOL_NAME)
    except Exception:  # PackageNotFoundError and anything odd
        return None


def _herbie_version() -> str | None:
    try:
        import herbie

        return getattr(herbie, "__version__", None)
    except Exception:
        return None


def _ensure_utc(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def _isoformat_utc(value: dt.datetime) -> str:
    """``%Y-%m-%dT%H:%M:%SZ`` (matches ``basinwx._isoformat_utc``)."""
    return _ensure_utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")


_LEAD_RE = re.compile(r"(\d+)\s*hour")


def _parse_lead(text) -> int | None:
    """Integer lead hour from a forecast-time string ('12 hour fcst' -> 12)."""
    m = _LEAD_RE.search(str(text))
    if m:
        return int(m.group(1))
    s = str(text).strip()
    return int(s) if s.isdigit() else None


def _inv_lead_values(inv) -> list:
    """The inventory column carrying lead time, as a list (empty if none)."""
    columns = list(getattr(inv, "columns", []))
    col = next((c for c in ("forecast_time", "step", "fxx", "lead_time") if c in columns), None)
    if col is None:
        return []
    try:
        return inv[col].tolist()
    except Exception:  # pragma: no cover - defensive
        return []


def _lead_times_from_inventory(inv) -> list[int]:
    """Best-effort sorted integer lead-time list from a Herbie inventory."""
    if inv is None:
        return []
    hours = {h for h in (_parse_lead(v) for v in _inv_lead_values(inv)) if h is not None}
    return sorted(hours)


def _lead_search_regex(inv, lo: int, hi: int) -> tuple[str | None, list[int]]:
    """Herbie ``search`` regex selecting only lead times in ``[lo, hi]``.

    Matches the inventory's ``:<var>:<level>:<N> hour fcst:`` lines on the lead
    token (the leading ``:`` disambiguates 12 from 112), so ``Herbie.download``
    fetches only those GRIB messages by byte-range. Returns
    ``(regex_or_None, in_window_leads)``; the regex is ``None`` when no integer
    ``N hour fcst`` lead falls in the window (e.g. accumulation fields), in which
    case the caller stages the whole file.
    """
    leads = sorted(
        {
            h
            for h in (_parse_lead(v) for v in _inv_lead_values(inv))
            if h is not None and lo <= h <= hi
        }
    )
    if not leads:
        return None, []
    alt = "|".join(str(h) for h in leads)
    return rf":(?:{alt}) hour fcst:", leads


# ── core stager ─────────────────────────────────────────────────────────────


def stage_reforecast(
    *,
    init_time: str | dt.datetime,
    variable_levels: list[str] | None = None,
    member: int = 0,
    output_root: str | Path = DEFAULT_SCRATCH_ROOT,
    case: str = DEFAULT_CASE,
    source: str = DEFAULT_SOURCE,
    fxx_window: tuple[int, int] = DEFAULT_FXX_WINDOW,
    herbie_save_dir: str | Path | None = None,
    overwrite: bool = False,
    keep_herbie_cache: bool = False,
    validate_tokens: bool = True,
    lead_subset: bool = False,
) -> list[StagedFile]:
    """Stage all WPS ``variable_level`` files for one reforecast init + member.

    Parameters
    ----------
    init_time : str or datetime
        Reforecast init (daily 00Z only), e.g. ``"2013-01-31 00Z"``.
    variable_levels : list[str], optional
        Per-variable tokens to fetch. Defaults to the curated
        ``wps_variable_levels`` list in ``lookups.toml``.
    member : int
        Herbie reforecast member integer (0=control c00, 1-4=p01-p04).
    output_root : path
        Root of the ``wrf_inputs`` tree; files land under
        ``<root>/<case>/<source>/<member_token>/``.
    fxx_window : (int, int)
        Intended lead-time window (hours). Selects the forecast-range bucket and
        is recorded as metadata; the download fetches the whole bucket file.
    herbie_save_dir : path, optional
        Herbie's working cache before the move. Defaults to a temp dir; pass a
        path on the same filesystem as ``output_root`` to make the move a rename.
    overwrite : bool
        Re-download even if a valid file already exists at the canonical path.
    keep_herbie_cache : bool
        Copy out of Herbie's cache instead of moving (leaves the cache populated).
    validate_tokens : bool
        Guard each token with ``H.inventory()`` and raise on an empty result
        (catches typo/absent tokens that would otherwise 404 silently).
    lead_subset : bool
        Download only the GRIB messages whose lead time falls in ``fxx_window``
        (Herbie byte-range ``search=``), instead of the whole bucket file (f3–f240).
        For the Jan-2013 window this is ~6× smaller. Falls back to the whole file
        for fields whose lead is not an integer ``N hour fcst`` (e.g. accumulations).

    Returns
    -------
    list[StagedFile]
        One record per staged file. Does not write the manifest.
    """
    init_dt = _parse_init_time(init_time)
    lu = load_lookups()
    cfg = lu["models"].get(source, {})
    breakpoint_fxx = int(cfg.get("fxx_bucket_breakpoint", 240))
    herbie_model = cfg.get("herbie_model", source)

    if variable_levels is None:
        variable_levels = list(cfg.get("wps_variable_levels", []))
    if not variable_levels:
        raise ValueError(
            f"No variable_levels provided and none configured for source {source!r}."
        )

    member_token = _member_token(member)
    bucket = _fxx_bucket(int(fxx_window[0]), breakpoint_fxx)
    if _fxx_bucket(int(fxx_window[1]), breakpoint_fxx) != bucket:
        LOG.warning(
            "fxx window %s spans the %dh bucket breakpoint; only %s is staged. "
            "Re-run for the other bucket if you need longer leads.",
            fxx_window, breakpoint_fxx, bucket,
        )
    # A representative fxx inside the bucket (selects the directory only).
    rep_fxx = int(fxx_window[0])

    save_dir = (
        Path(herbie_save_dir)
        if herbie_save_dir is not None
        else Path(tempfile.gettempdir()) / "brc_wrf_staging_cache"
    )
    save_dir.mkdir(parents=True, exist_ok=True)
    lock_dir = os.environ.get("BRC_TOOLS_LOCK_DIR") or tempfile.gettempdir()

    staged: list[StagedFile] = []
    for token in variable_levels:
        filename = _reforecast_filename(token, init_dt, member_token)
        dest = _canonical_staging_path(output_root, case, source, member_token, filename)

        lock_name = (
            f"stage_{herbie_model}_{init_dt:%Y%m%d_%H}_"
            f"{member_token}_{token}_{bucket.replace(':', '')}.lock"
        )
        lock = fasteners.InterProcessLock(os.path.join(lock_dir, lock_name))

        with lock:
            if not overwrite and dest.exists() and validate_cached_grib(dest):
                LOG.info("skip (already staged): %s", dest)
                staged.append(
                    _record_existing(
                        dest, token, init_dt, member, member_token, bucket, source,
                        herbie_model, cfg,
                    )
                )
                continue

            H = Herbie(
                init_dt,
                model=herbie_model,
                member=member,
                fxx=rep_fxx,
                variable_level=token,
                save_dir=str(save_dir),
            )

            inv = _safe_inventory(H) if (validate_tokens or lead_subset) else None
            if validate_tokens and (inv is None or len(inv) == 0):
                raise ValueError(
                    f"variable_level {token!r} returned an empty inventory for "
                    f"{herbie_model} {init_dt:%Y-%m-%d %HZ} {member_token}. "
                    "Check the token against the S3 listing."
                )
            lead_times = _lead_times_from_inventory(inv)

            search = None
            if lead_subset and inv is not None:
                search, sub_leads = _lead_search_regex(
                    inv, int(fxx_window[0]), int(fxx_window[1])
                )
                if search is not None:
                    lead_times = sub_leads
                else:
                    LOG.warning(
                        "lead-subset: no integer lead in %s..%s for %s; staging whole file",
                        fxx_window[0], fxx_window[1], token,
                    )

            local = _download(H, search=search)
            if not validate_cached_grib(local):
                purge_cached_files(H)
                raise RuntimeError(f"Downloaded GRIB failed validation: {local}")

            dest.parent.mkdir(parents=True, exist_ok=True)
            if keep_herbie_cache:
                shutil.copy2(local, dest)
            else:
                shutil.move(str(local), str(dest))

            remote_url = _remote_url(H)
            staged.append(
                StagedFile(
                    source=source,
                    herbie_model=herbie_model,
                    member=member_token,
                    member_int=member,
                    init_time=_isoformat_utc(init_dt),
                    variable_level=token,
                    fxx_bucket=bucket,
                    lead_times=lead_times,
                    product=str(cfg.get("default_product", "")),
                    local_path=str(dest),
                    remote_url=remote_url,
                    size_bytes=dest.stat().st_size,
                    sha256=_sha256(dest),
                    created_at=_isoformat_utc(dt.datetime.now(dt.timezone.utc)),
                )
            )
            LOG.info("staged %s -> %s (%d bytes)", token, dest, dest.stat().st_size)

    return staged


def _record_existing(
    dest, token, init_dt, member, member_token, bucket, source, herbie_model, cfg
) -> StagedFile:
    """Build a StagedFile for an already-present file without re-downloading.

    ``lead_times`` is left empty because deriving it would require an
    ``H.inventory()`` network call, which the skip-existing path deliberately
    avoids; ``remote_url`` is reconstructed deterministically. Use
    ``overwrite=True`` for a full-fidelity manifest.
    """
    return StagedFile(
        source=source,
        herbie_model=herbie_model,
        member=member_token,
        member_int=member,
        init_time=_isoformat_utc(init_dt),
        variable_level=token,
        fxx_bucket=bucket,
        lead_times=[],
        product=str(cfg.get("default_product", "")),
        local_path=str(dest),
        remote_url=_reforecast_remote_url(token, init_dt, member_token, bucket),
        size_bytes=dest.stat().st_size,
        sha256=_sha256(dest),
        created_at=_isoformat_utc(dt.datetime.now(dt.timezone.utc)),
    )


def _safe_inventory(H):
    """Return ``H.inventory()`` or ``None`` if it raises (e.g. missing idx)."""
    try:
        return H.inventory()
    except Exception as exc:  # noqa: BLE001 - token-validation guard
        LOG.warning("inventory() failed: %s", exc)
        return None


def _download(H, search=None) -> Path:
    """Download the GRIB (retains it) and return the local path.

    ``search=None`` downloads the whole file; a regex downloads only the matching
    GRIB messages by byte-range (used by ``lead_subset``).
    """
    out = H.download(search=search)
    if out is not None:
        return Path(out)
    getter = getattr(H, "get_localFilePath", None)
    if callable(getter):
        return Path(getter())
    grib = getattr(H, "grib", None)
    if grib is not None:
        return Path(grib)
    raise RuntimeError("Herbie.download() returned no local path.")


def _remote_url(H) -> str | None:
    sources = getattr(H, "SOURCES", None)
    if not isinstance(sources, dict) or not sources:
        return None
    key = getattr(H, "grib_source", None)
    return sources.get(key) or sources.get("aws") or next(iter(sources.values()))


def stage_fnl_filler(**_kwargs) -> list[StagedFile]:
    """STUB — GFS/FNL filler source (documented extension point).

    For the 2013 case the WPS "filler" (land-sea mask, SST, skin temp, and any
    fields the reforecast lacks) must come from **NCAR RDA ds083.2** (RDA auth +
    globus/wget), which Herbie does not serve. It should stage into
    ``<case>/gfs_fnl/`` and append ``StagedFile`` records with ``source="gfs_fnl"``.
    The metgrid-side fusion (two ungrib streams + multiple ``fg_name``) lives in
    the brc-wrf repo, not here.
    """
    raise NotImplementedError(
        "GFS/FNL filler for 2013 must come from NCAR RDA ds083.2 (not Herbie); "
        "stage into <case>/gfs_fnl/. See the WRF-input staging handoff gaps."
    )


# ── manifest ────────────────────────────────────────────────────────────────


def build_manifest(
    *,
    case: str,
    region: str,
    requested_window: tuple[str, str],
    interval_hours: int,
    sources: list[str],
    staged: list[StagedFile],
) -> dict:
    """Compose the staging manifest (case block + provenance + per-file list)."""
    lu = load_lookups()
    region_cfg = lu.get("regions", {}).get(region, {})
    bbox = (
        {"sw": list(region_cfg["sw"]), "ne": list(region_cfg["ne"])}
        if region_cfg
        else None
    )
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "manifest_kind": "wrf_input_staging",
        "case": {
            "name": case,
            "region": region,
            "bbox": bbox,
            "requested_window": {
                "start": requested_window[0],
                "end": requested_window[1],
            },
            "interval_hours": int(interval_hours),
            "note": (
                "interval_hours is the intended metgrid/WRF LBC interval "
                "(downstream metadata); reforecast files are whole-file-per-variable "
                "across all lead times."
            ),
            "sources": list(sources),
        },
        "provenance": {
            "tool": TOOL_NAME,
            "tool_version": _tool_version(),
            "git_sha": _git_sha(),
            "herbie_version": _herbie_version(),
            "generated_at": _isoformat_utc(dt.datetime.now(dt.timezone.utc)),
        },
        "staged_files": [asdict(s) for s in staged],
    }


def write_manifest(manifest: dict, output_dir: str | Path) -> Path:
    """Write the manifest JSON into ``output_dir`` and return its path."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"manifest_{manifest['case']['name']}.json"
    with path.open("w", encoding="utf-8") as handle:
        import json

        json.dump(manifest, handle, indent=2, allow_nan=False)
    return path


# ── orchestrator ────────────────────────────────────────────────────────────


def stage_case(
    *,
    case: str = DEFAULT_CASE,
    init_time: str = DEFAULT_INIT,
    region: str = DEFAULT_REGION,
    members: tuple[int, ...] = (0,),
    output_root: str | Path = DEFAULT_SCRATCH_ROOT,
    fxx_window: tuple[int, int] = DEFAULT_FXX_WINDOW,
    interval_hours: int = DEFAULT_INTERVAL_HOURS,
    variable_levels: list[str] | None = None,
    source: str = DEFAULT_SOURCE,
    quicklook: bool = True,
    obs_check: bool = False,
    **stage_kwargs,
) -> Path:
    """Stage every requested member, write the manifest, optional quicklook/obs.

    Returns the manifest path.
    """
    init_dt = _parse_init_time(init_time)
    window = (
        _isoformat_utc(init_dt + dt.timedelta(hours=int(fxx_window[0]))),
        _isoformat_utc(init_dt + dt.timedelta(hours=int(fxx_window[1]))),
    )

    staged: list[StagedFile] = []
    for member in members:
        staged.extend(
            stage_reforecast(
                init_time=init_dt,
                variable_levels=variable_levels,
                member=member,
                output_root=output_root,
                case=case,
                source=source,
                fxx_window=fxx_window,
                **stage_kwargs,
            )
        )

    manifest = build_manifest(
        case=case,
        region=region,
        requested_window=window,
        interval_hours=interval_hours,
        sources=[source],
        staged=staged,
    )
    case_dir = Path(output_root) / case
    manifest_path = write_manifest(manifest, case_dir)
    LOG.info("wrote manifest %s (%d files)", manifest_path, len(staged))

    if quicklook and staged:
        _run_quicklook(staged, region=region, case=case)
    if obs_check:
        _run_obs_check(case=case, init_dt=init_dt)

    return manifest_path


def _run_quicklook(staged: list[StagedFile], *, region: str, case: str) -> None:
    """Best-effort sanity figures; never fatal to staging."""
    try:
        from brc_tools.nwp.wrf_quicklook import quicklook_staged_grib

        wanted = {"tmp_2m", "weasd_sfc"}
        for s in staged:
            if s.variable_level in wanted:
                try:
                    png = quicklook_staged_grib(
                        s.local_path,
                        variable_level=s.variable_level,
                        region=region,
                        case=case,
                    )
                    LOG.info("quicklook -> %s", png)
                except Exception as exc:  # noqa: BLE001
                    LOG.warning("quicklook failed for %s: %s", s.variable_level, exc)
    except Exception as exc:  # noqa: BLE001
        LOG.warning("quicklook unavailable: %s", exc)


def _run_obs_check(*, case: str, init_dt: dt.datetime) -> None:
    """Opt-in obs overlay; 2013 basin obs are sparse, so failures are non-fatal."""
    try:
        from brc_tools.nwp.wrf_quicklook import obs_sanity_overlay

        png = obs_sanity_overlay(case=case, event_date=f"{init_dt:%Y-%m-%d}")
        LOG.info("obs overlay -> %s", png)
    except Exception as exc:  # noqa: BLE001
        LOG.warning("obs overlay unavailable/empty: %s", exc)


# ── CLI ─────────────────────────────────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for the WRF-input staging script."""
    parser = argparse.ArgumentParser(
        description="Stage WPS/WRF-ready GRIB inputs (GEFSv12 Reforecast) to scratch.",
    )
    parser.add_argument("--case", default=DEFAULT_CASE, help="Case name (output subdir).")
    parser.add_argument(
        "--init-time", default=DEFAULT_INIT, help="Reforecast init (daily 00Z), 'YYYY-MM-DD 00Z'."
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_SCRATCH_ROOT),
        help=f"wrf_inputs root (default: {DEFAULT_SCRATCH_ROOT}).",
    )
    parser.add_argument("--region", default=DEFAULT_REGION, help="Named region for manifest bbox + quicklook.")
    parser.add_argument(
        "--members", default="0", help="Comma list of member integers 0-4 (default: 0 = control)."
    )
    parser.add_argument(
        "--variable-levels",
        default="",
        help="Comma list of variable_level tokens (default: lookups wps_variable_levels).",
    )
    parser.add_argument(
        "--fxx-window", default="12,48", help="Lead-time window 'start,end' (manifest/bucket only)."
    )
    parser.add_argument("--interval-hours", type=int, default=DEFAULT_INTERVAL_HOURS, help="LBC interval (metadata).")
    parser.add_argument("--herbie-save-dir", default=None, help="Herbie working cache before the move.")
    parser.add_argument("--keep-herbie-cache", action="store_true", help="Copy instead of move out of cache.")
    parser.add_argument("--overwrite", action="store_true", help="Re-download even if already staged.")
    parser.add_argument(
        "--lead-subset", action="store_true",
        help="Download only lead times in --fxx-window (byte-range), not the whole f3-f240 bucket.",
    )
    parser.add_argument("--no-quicklook", action="store_true", help="Skip quicklook figures.")
    parser.add_argument("--obs-check", action="store_true", help="Attempt SynopticPy obs overlay (opt-in).")
    parser.add_argument("--no-validate-tokens", action="store_true", help="Skip the H.inventory() token guard.")
    return parser.parse_args(argv)


def _parse_int_csv(text: str) -> list[int]:
    return [int(x) for x in text.split(",") if x.strip() != ""]


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for WRF-input GRIB staging."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    args = parse_args(argv)
    members = tuple(_parse_int_csv(args.members))
    variable_levels = (
        [v.strip() for v in args.variable_levels.split(",") if v.strip()]
        if args.variable_levels
        else None
    )
    fxx_parts = _parse_int_csv(args.fxx_window)
    fxx_window = (fxx_parts[0], fxx_parts[-1]) if fxx_parts else DEFAULT_FXX_WINDOW

    try:
        manifest_path = stage_case(
            case=args.case,
            init_time=args.init_time,
            region=args.region,
            members=members,
            output_root=args.output_dir,
            fxx_window=fxx_window,
            interval_hours=args.interval_hours,
            variable_levels=variable_levels,
            quicklook=not args.no_quicklook,
            obs_check=args.obs_check,
            herbie_save_dir=args.herbie_save_dir,
            keep_herbie_cache=args.keep_herbie_cache,
            overwrite=args.overwrite,
            validate_tokens=not args.no_validate_tokens,
            lead_subset=args.lead_subset,
        )
    except Exception as exc:  # noqa: BLE001
        LOG.error("WRF-input staging failed: %s", exc)
        return 1

    LOG.info("Manifest: %s", manifest_path)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())

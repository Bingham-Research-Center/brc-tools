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

The land-sea mask, SST, skin temp, and soil that the reforecast lacks come from an
**auth-free NAM 12 km analysis** (NCEI ``namanl_218``) staged by
:func:`stage_nam_analysis` — no NCAR RDA account, no Herbie, just a direct HTTP GET.
NAM analysis works either as a standalone single-stream WRF forcing (the validated
Feb-2013 Basin recipe, ``Vtable.NAM``) or as the reforecast's second metgrid stream;
the WPS-side fusion (``Vtable.NAM`` + ``fg_name``) lives in the brc-wrf repo.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import fasteners
import requests
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
# v2: added staged_files[].lead_times_source + provenance.total_bytes/elapsed_seconds.
# Additive only; brc-wrf reads the contract sidecar, and verify_manifest still reads v1.
MANIFEST_SCHEMA_VERSION = 2
CONTRACT_SCHEMA_VERSION = 1

# Split HTTP timeouts for direct GETs: a short connect bound (so a wedged socket
# fails fast instead of blocking on the default scalar) + a longer read bound for
# the multi-hundred-MB GRIB body. See ``_http_download_grib``.
DEFAULT_HTTP_CONNECT_TIMEOUT = 10.0
DEFAULT_HTTP_READ_TIMEOUT = 300.0

# Offline byte estimate for a single NAM 12 km analysis cycle (~115 MB observed),
# used by ``plan_case`` to gauge load before committing a DTN job.
NAM_EST_BYTES_PER_CYCLE = 120_000_000

_IPV4_ENV = "BRC_TOOLS_HTTP_IPV4_ONLY"


def _ipv4_only_requested() -> bool:
    """True if ``BRC_TOOLS_HTTP_IPV4_ONLY`` is set to a truthy value."""
    return os.environ.get(_IPV4_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def _install_ipv4_only():
    """Force every socket lookup in this process to resolve IPv4 (AF_INET) only.

    Works around a CHPC DTN hang where outbound IPv6 to NCEI/S3 sits in SYN-SENT
    indefinitely (observed on ``dtn05`` killing job ``13471949``; the IPv4-only
    one-off ``13472014`` completed). Patching ``socket.getaddrinfo`` at the socket
    layer is mechanism-agnostic — it covers Herbie's S3 download *and* the direct
    ``requests`` NAM GET regardless of which HTTP stack each uses.

    Idempotent (tagged so a second call is a no-op). Returns the original
    ``getaddrinfo`` so callers/tests can restore it, or ``None`` if already
    installed. Falls back to the full result set for hosts with no IPv4 address,
    so it never breaks an IPv6-only endpoint.
    """
    if getattr(socket.getaddrinfo, "_brc_ipv4_only", False):
        return None
    original = socket.getaddrinfo

    def _ipv4_getaddrinfo(host, port, family=0, *args, **kwargs):
        results = original(host, port, family, *args, **kwargs)
        ipv4 = [r for r in results if r[0] == socket.AF_INET]
        return ipv4 or results

    _ipv4_getaddrinfo._brc_ipv4_only = True
    socket.getaddrinfo = _ipv4_getaddrinfo
    LOG.info("HTTP IPv4-only mode active (socket.getaddrinfo filtered to AF_INET).")
    return original


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
    # Provenance of ``lead_times``: "inventory" (parsed from a live Herbie inventory at
    # download), "analysis" (NAM single-cycle, always [0]), "idx" (recovered from a
    # co-located ``<file>.idx`` on the skip-existing path), or "skip-no-idx" (skip path
    # with no sidecar idx — ``lead_times`` is empty; re-run with overwrite for full fidelity).
    lead_times_source: str = "inventory"


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
    """``<root>/<case>/<source>/<member_token>/<filename>``.

    ``member_token`` may be empty (analysis sources with no ensemble member),
    in which case the member level is dropped: ``<root>/<case>/<source>/<filename>``.
    """
    base = Path(root) / case / source
    if member_token:
        base = base / member_token
    return base / filename


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


def _lead_times_from_idx(idx_path: Path) -> list[int]:
    """Best-effort sorted integer lead-time list from a co-located GRIB ``.idx`` sidecar.

    The idx is the wgrib-style inventory text written next to a GRIB; each line carries a
    forecast-time token (e.g. ``...:3 hour fcst:...``) that :func:`_parse_lead` already
    understands. Returns ``[]`` on any read/parse failure, so the caller falls back to a
    degraded (but labelled) skip entry rather than raising.
    """
    try:
        text = Path(idx_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    hours = {h for h in (_parse_lead(line) for line in text.splitlines()) if h is not None}
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
                    lead_times_source="inventory",
                )
            )
            LOG.info("staged %s -> %s (%d bytes)", token, dest, dest.stat().st_size)

    return staged


def _record_existing(
    dest, token, init_dt, member, member_token, bucket, source, herbie_model, cfg
) -> StagedFile:
    """Build a StagedFile for an already-present file without re-downloading.

    The skip-existing path deliberately avoids an ``H.inventory()`` network call, so
    ``lead_times`` is recovered offline only from a co-located ``<dest>.idx`` sidecar
    *if one is present* (``lead_times_source="idx"``). In normal operation no idx is
    co-located — staging moves only the GRIB, not its idx — so the entry is recorded
    empty and labelled ``"skip-no-idx"``; re-run with ``overwrite=True`` for
    full-fidelity lead times. ``remote_url`` is reconstructed deterministically.
    """
    idx_path = Path(str(dest) + ".idx")
    if idx_path.exists():
        lead_times = _lead_times_from_idx(idx_path)
        lead_times_source = "idx" if lead_times else "skip-no-idx"
    else:
        lead_times = []
        lead_times_source = "skip-no-idx"
    return StagedFile(
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
        remote_url=_reforecast_remote_url(token, init_dt, member_token, bucket),
        size_bytes=dest.stat().st_size,
        sha256=_sha256(dest),
        created_at=_isoformat_utc(dt.datetime.now(dt.timezone.utc)),
        lead_times_source=lead_times_source,
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


# ── NAM analysis filler/forcing (auth-free NCEI, no NCAR RDA) ────────────────


DEFAULT_NAM_SOURCE = "nam_analysis"
DEFAULT_NAM_CADENCE_HOURS = 6


def _snap_down_to_cadence(t: dt.datetime, cadence_hours: int) -> dt.datetime:
    """Floor ``t`` to the nearest analysis cycle (multiples of cadence from 00Z)."""
    floored_hour = (t.hour // cadence_hours) * cadence_hours
    return t.replace(hour=floored_hour, minute=0, second=0, microsecond=0)


def _nam_cycle_times(
    init_dt: dt.datetime,
    fxx_window: tuple[int, int],
    cadence_hours: int,
    pad_cycles: int = 0,
) -> list[dt.datetime]:
    """Analysis cycle times spanning ``[init+lo, init+hi]`` on the cadence grid.

    ``pad_cycles`` extends the window by that many cadence steps each end so
    metgrid has bracketing analyses. NAM analysis cycles are 00/06/12/18Z.
    """
    lo, hi = int(fxx_window[0]), int(fxx_window[1])
    pad = dt.timedelta(hours=pad_cycles * cadence_hours)
    start = _snap_down_to_cadence(
        init_dt + dt.timedelta(hours=lo) - pad, cadence_hours
    )
    end = init_dt + dt.timedelta(hours=hi) + pad
    times, step, t = [], dt.timedelta(hours=cadence_hours), start
    while t <= end:
        times.append(t)
        t += step
    return times


def _http_download_grib(
    url: str,
    dest: Path,
    *,
    connect_timeout: float,
    read_timeout: float,
    retries: int,
    backoff: float,
) -> bool:
    """Stream a GRIB from ``url`` to ``dest`` (auth-free GET).

    ``connect_timeout``/``read_timeout`` map to the ``requests`` ``(connect, read)``
    timeout tuple: a short connect bound so a wedged socket (e.g. the CHPC DTN
    IPv6 hang) fails fast and retries, plus a longer read bound for the GRIB body.

    Returns ``True`` on success, ``False`` if the remote file is missing (404 —
    NCEI has isolated gaps, so the caller skips that cycle). Raises after
    ``retries`` attempts on a persistent non-404 error (a real outage, not a gap).
    """
    timeout = (connect_timeout, read_timeout)
    LOG.info(
        "NAM GET %s (connect=%.0fs read=%.0fs, ipv4_only=%s)",
        url, connect_timeout, read_timeout,
        bool(getattr(socket.getaddrinfo, "_brc_ipv4_only", False)),
    )
    tmp = dest.with_suffix(dest.suffix + ".part")
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            with requests.get(url, stream=True, timeout=timeout) as resp:
                if resp.status_code == 404:
                    LOG.warning("NAM cycle missing (404), skipping: %s", url)
                    return False
                resp.raise_for_status()
                with open(tmp, "wb") as handle:
                    for chunk in resp.iter_content(chunk_size=1 << 20):
                        if chunk:
                            handle.write(chunk)
            tmp.replace(dest)
            return True
        except requests.RequestException as exc:
            last_exc = exc
            LOG.warning(
                "NAM download attempt %d/%d failed (%s): %s", attempt, retries, exc, url
            )
            tmp.unlink(missing_ok=True)
            if attempt < retries:
                time.sleep(backoff * attempt)
    raise RuntimeError(
        f"NAM download failed after {retries} attempts: {url}"
    ) from last_exc


def _nam_staged_file(
    dest: Path, cycle: dt.datetime, url: str, source: str, cfg: dict
) -> StagedFile:
    """Provenance record for one staged NAM analysis file (whole file, all fields)."""
    return StagedFile(
        source=source,
        herbie_model="",  # direct NCEI HTTP, not a Herbie fetch
        member="",  # analysis: no ensemble member
        member_int=0,
        init_time=_isoformat_utc(cycle),  # analysis time == valid time
        variable_level="all",  # full file; Vtable/metgrid selects fields
        fxx_bucket="analysis",
        lead_times=[0],
        product=str(cfg.get("default_product", "namanl_218")),
        local_path=str(dest),
        remote_url=url,
        size_bytes=dest.stat().st_size,
        sha256=_sha256(dest),
        created_at=_isoformat_utc(dt.datetime.now(dt.timezone.utc)),
        lead_times_source="analysis",
    )


def stage_nam_analysis(
    *,
    init_time: str | dt.datetime,
    fxx_window: tuple[int, int] = DEFAULT_FXX_WINDOW,
    output_root: str | Path = DEFAULT_SCRATCH_ROOT,
    case: str = DEFAULT_CASE,
    source: str = DEFAULT_NAM_SOURCE,
    cadence_hours: int | None = None,
    pad_cycles: int = 0,
    overwrite: bool = False,
    validate: bool = True,
    connect_timeout: float = DEFAULT_HTTP_CONNECT_TIMEOUT,
    read_timeout: float = DEFAULT_HTTP_READ_TIMEOUT,
    retries: int = 3,
    backoff: float = 5.0,
) -> list[StagedFile]:
    """Stage NAM 12 km analysis (NCEI ``namanl_218``) across the case window.

    The **auth-free filler/forcing** that replaces the old NCAR-RDA
    ``stage_fnl_filler`` stub. NAM analysis carries the full WRF field set the
    GEFS reforecast lacks (land-sea mask, SST, skin temp, 4-layer soil, snow), so
    it serves either as a standalone single-stream forcing (the validated Feb-2013
    Basin recipe, ``Vtable.NAM``) or as the reforecast's second metgrid stream.

    One **whole** GRIB per analysis cycle (00/06/12/18Z) is downloaded by direct
    HTTP from the NCEI historical archive — no NCAR RDA account, no Herbie. Fields
    are **not** cherry-picked; the WPS ``Vtable``/metgrid selects what it needs.

    ``fxx_window`` is the valid-time window relative to ``init_time``; cycles are
    enumerated on the analysis cadence grid (default 6 h, from ``lookups.toml``)
    spanning it. Isolated missing cycles (NCEI gaps) are logged and skipped.
    Returns one :class:`StagedFile` per file; does not write the manifest.
    """
    init_dt = _parse_init_time(init_time)
    lu = load_lookups()
    cfg = lu["models"].get(source, {})
    cadence = int(cadence_hours or cfg.get("cadence_hours", DEFAULT_NAM_CADENCE_HOURS))
    url_template = cfg.get("url_template")
    filename_template = cfg.get("filename_template")
    if not url_template or not filename_template:
        raise ValueError(
            f"source {source!r} needs url_template + filename_template in lookups.toml."
        )

    cycles = _nam_cycle_times(init_dt, fxx_window, cadence, pad_cycles)
    lock_dir = os.environ.get("BRC_TOOLS_LOCK_DIR") or tempfile.gettempdir()

    staged: list[StagedFile] = []
    for cycle in cycles:
        fmt = {
            "yyyymm": f"{cycle:%Y%m}",
            "yyyymmdd": f"{cycle:%Y%m%d}",
            "hhmm": f"{cycle:%H%M}",
        }
        filename = filename_template.format(**fmt)
        url = url_template.format(filename=filename, **fmt)
        dest = _canonical_staging_path(output_root, case, source, "", filename)

        lock = fasteners.InterProcessLock(
            os.path.join(lock_dir, f"stage_nam_{cycle:%Y%m%d_%H}.lock")
        )
        with lock:
            if not overwrite and dest.exists() and validate_cached_grib(dest):
                LOG.info("skip (already staged): %s", dest)
                staged.append(_nam_staged_file(dest, cycle, url, source, cfg))
                continue

            dest.parent.mkdir(parents=True, exist_ok=True)
            if not _http_download_grib(
                url, dest,
                connect_timeout=connect_timeout, read_timeout=read_timeout,
                retries=retries, backoff=backoff,
            ):
                continue  # 404 — isolated missing cycle, already logged

            if validate and not validate_cached_grib(dest):
                dest.unlink(missing_ok=True)
                raise RuntimeError(f"Downloaded NAM GRIB failed validation: {dest}")

            staged.append(_nam_staged_file(dest, cycle, url, source, cfg))
            LOG.info("staged NAM %s -> %s (%d bytes)", filename, dest, dest.stat().st_size)

    if not staged:
        raise RuntimeError(
            f"NAM staging produced no files for init {init_dt:%Y-%m-%d %HZ} window "
            f"{fxx_window}: all {len(cycles)} cycle(s) were missing/unreachable. Check the "
            "NCEI URL template ([models.nam_analysis] in lookups.toml)."
        )
    if len(staged) < len(cycles):
        LOG.warning(
            "NAM: staged %d of %d cycles (%d missing gap(s)).",
            len(staged), len(cycles), len(cycles) - len(staged),
        )
    return staged


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
        json.dump(manifest, handle, indent=2, allow_nan=False)
    return path


# ── WPS/WRF case contract ────────────────────────────────────────────────────


def _interval_hours_for_sources(sources, lu: dict) -> int:
    """Metgrid/WRF LBC interval (hours) implied by the forcing source(s).

    NAM-only forcing runs at the NAM analysis cadence (6 h — the validated
    Feb-2013 recipe). If a reforecast-family source is present it forces the LBCs
    at the finer reforecast lead cadence (3 h), with NAM as filler. This replaces
    the blind ``DEFAULT_INTERVAL_HOURS`` that wrongly stamped a NAM-only run as 3 h.
    """
    non_nam = [s for s in sources if s != DEFAULT_NAM_SOURCE]
    if non_nam:
        return DEFAULT_INTERVAL_HOURS  # reforecast 3-hourly LBC cadence
    cfg = lu["models"].get(DEFAULT_NAM_SOURCE, {})
    return int(cfg.get("cadence_hours", DEFAULT_NAM_CADENCE_HOURS))


def build_contract(manifest: dict, lu: dict | None = None) -> dict:
    """Derive a WPS/WRF case contract from a staging manifest.

    Emits only facts brc-tools can authoritatively know from what it staged:
    per-source file counts, cadence, the valid window, an ``fg_name`` suggestion,
    and ``interval_seconds`` derived from the forcing source's cadence. WPS/metgrid
    *outputs* such as ``num_metgrid_levels`` are NOT computed here — they are
    metgrid's product and live in the docs as proof constants.
    """
    if lu is None:
        lu = load_lookups()
    case = manifest.get("case", {})
    sources = list(case.get("sources", []))
    staged = manifest.get("staged_files", [])

    counts: dict[str, int] = {}
    for s in staged:
        counts[s["source"]] = counts.get(s["source"], 0) + 1

    cadence_hours = {}
    for src in sources:
        cfg = lu["models"].get(src, {})
        cadence_hours[src] = (
            int(cfg.get("cadence_hours", DEFAULT_NAM_CADENCE_HOURS))
            if src == DEFAULT_NAM_SOURCE
            else DEFAULT_INTERVAL_HOURS
        )

    nam = DEFAULT_NAM_SOURCE in sources
    other = [s for s in sources if s != DEFAULT_NAM_SOURCE]
    if other and nam:
        fg_name = ["GEFS", "NAM"]  # two-stream: reforecast forcing + NAM filler
    elif other:
        fg_name = ["GEFS"]
    else:
        fg_name = ["NAM"]  # validated single-stream forcing

    interval_hours = _interval_hours_for_sources(sources, lu)
    name = case.get("name")
    return {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "contract_kind": "wps_wrf_case_contract",
        "case": name,
        "region": case.get("region"),
        "valid_window": case.get("requested_window"),
        "sources": sources,
        "source_file_counts": counts,
        "cadence_hours": cadence_hours,
        "interval_hours": int(interval_hours),
        "interval_seconds": int(interval_hours) * 3600,
        "wps_fg_name": fg_name,
        "scratch_layout": "<output_root>/<case>/<source>/[<member>/]<file>",
        "manifest": f"manifest_{name}.json" if name else None,
        "generated_at": manifest.get("provenance", {}).get("generated_at"),
    }


def write_contract(contract: dict, output_dir: str | Path, case: str) -> Path:
    """Write the contract JSON into ``output_dir`` and return its path."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"contract_{case}.json"
    with path.open("w", encoding="utf-8") as handle:
        json.dump(contract, handle, indent=2, allow_nan=False)
    return path


# ── plan / dry-run + manifest integrity ──────────────────────────────────────


def plan_case(
    *,
    case: str = DEFAULT_CASE,
    init_time: str | dt.datetime = DEFAULT_INIT,
    members: tuple[int, ...] = (0,),
    output_root: str | Path = DEFAULT_SCRATCH_ROOT,
    fxx_window: tuple[int, int] = DEFAULT_FXX_WINDOW,
    variable_levels: list[str] | None = None,
    sources: tuple[str, ...] = (DEFAULT_SOURCE,),
) -> list[dict]:
    """Enumerate the files a stage would produce — **offline, no network**.

    Returns one dict per expected file (``source``, ``member``, ``filename``,
    ``url``, ``local_path``, ``est_bytes``) so a user can gauge load and eyeball
    URLs/paths before committing a DTN job. Reforecast byte sizes are unknown
    offline (would need an inventory call) and are reported as ``None``.
    """
    init_dt = _parse_init_time(init_time)
    lu = load_lookups()
    plan: list[dict] = []
    for src in sources:
        cfg = lu["models"].get(src, {})
        if src == DEFAULT_NAM_SOURCE:
            cadence = int(cfg.get("cadence_hours", DEFAULT_NAM_CADENCE_HOURS))
            url_template = cfg.get("url_template")
            filename_template = cfg.get("filename_template")
            if not url_template or not filename_template:
                raise ValueError(
                    f"source {src!r} needs url_template + filename_template in lookups.toml."
                )
            for cycle in _nam_cycle_times(init_dt, fxx_window, cadence):
                fmt = {
                    "yyyymm": f"{cycle:%Y%m}",
                    "yyyymmdd": f"{cycle:%Y%m%d}",
                    "hhmm": f"{cycle:%H%M}",
                }
                filename = filename_template.format(**fmt)
                url = url_template.format(filename=filename, **fmt)
                dest = _canonical_staging_path(output_root, case, src, "", filename)
                plan.append({
                    "source": src, "member": "", "filename": filename,
                    "url": url, "local_path": str(dest),
                    "est_bytes": NAM_EST_BYTES_PER_CYCLE,
                })
        else:
            breakpoint_fxx = int(cfg.get("fxx_bucket_breakpoint", 240))
            tokens = variable_levels or list(cfg.get("wps_variable_levels", []))
            bucket = _fxx_bucket(int(fxx_window[0]), breakpoint_fxx)
            for member in members:
                member_token = _member_token(member)
                for token in tokens:
                    filename = _reforecast_filename(token, init_dt, member_token)
                    url = _reforecast_remote_url(token, init_dt, member_token, bucket)
                    dest = _canonical_staging_path(
                        output_root, case, src, member_token, filename
                    )
                    plan.append({
                        "source": src, "member": member_token, "filename": filename,
                        "url": url, "local_path": str(dest), "est_bytes": None,
                    })
    return plan


def _print_plan(plan: list[dict]) -> None:
    """Pretty-print a :func:`plan_case` result with per-source totals."""
    if not plan:
        print("plan: nothing to stage.")
        return
    known = sum(e["est_bytes"] for e in plan if e["est_bytes"])
    n_est = sum(1 for e in plan if e["est_bytes"] is None)
    for e in plan:
        size = f"~{e['est_bytes'] / 1e6:.0f} MB" if e["est_bytes"] else "size unknown offline"
        print(f"  [{e['source']:<15}] {e['local_path']}\n      <- {e['url']}  ({size})")
    print(
        f"plan: {len(plan)} file(s); est. >= {known / 1e6:.0f} MB"
        + (f" (+{n_est} reforecast file(s) of unknown offline size)" if n_est else "")
    )


def verify_manifest(manifest_path: str | Path) -> dict:
    """Re-check every staged file against the manifest before WPS consumes it.

    For each ``staged_files`` entry: confirm the local file exists, its size
    matches ``size_bytes``, and its recomputed SHA-256 matches ``sha256``.
    Returns ``{ok, n_files, n_ok, results:[{local_path, ok, problem}]}``.
    """
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    results = []
    for entry in manifest.get("staged_files", []):
        lp = Path(entry["local_path"])
        problem = None
        if not lp.exists():
            problem = "missing"
        elif lp.stat().st_size != entry.get("size_bytes"):
            problem = f"size {lp.stat().st_size} != manifest {entry.get('size_bytes')}"
        elif _sha256(lp) != entry.get("sha256"):
            problem = "sha256 mismatch"
        results.append({"local_path": str(lp), "ok": problem is None, "problem": problem})
    n_ok = sum(1 for r in results if r["ok"])
    return {"ok": n_ok == len(results), "n_files": len(results), "n_ok": n_ok, "results": results}


# ── orchestrator ────────────────────────────────────────────────────────────


def stage_case(
    *,
    case: str = DEFAULT_CASE,
    init_time: str = DEFAULT_INIT,
    region: str = DEFAULT_REGION,
    members: tuple[int, ...] = (0,),
    output_root: str | Path = DEFAULT_SCRATCH_ROOT,
    fxx_window: tuple[int, int] = DEFAULT_FXX_WINDOW,
    interval_hours: int | None = None,
    variable_levels: list[str] | None = None,
    source: str = DEFAULT_SOURCE,
    sources: tuple[str, ...] | None = None,
    connect_timeout: float = DEFAULT_HTTP_CONNECT_TIMEOUT,
    read_timeout: float = DEFAULT_HTTP_READ_TIMEOUT,
    quicklook: bool = True,
    obs_check: bool = False,
    **stage_kwargs,
) -> Path:
    """Stage every requested source/member, write the manifest, optional quicklook/obs.

    ``sources`` (e.g. ``("gefs_reforecast", "nam_analysis")``) overrides the
    singular ``source``; ``nam_analysis`` is staged via :func:`stage_nam_analysis`
    (one whole file per analysis cycle), any other source via
    :func:`stage_reforecast` (per member). ``interval_hours`` defaults to the
    forcing source's cadence (NAM-only → 6 h, reforecast → 3 h) when not given.
    Also writes a ``contract_<case>.json`` sidecar. Returns the manifest path.
    """
    init_dt = _parse_init_time(init_time)
    lu = load_lookups()
    window = (
        _isoformat_utc(init_dt + dt.timedelta(hours=int(fxx_window[0]))),
        _isoformat_utc(init_dt + dt.timedelta(hours=int(fxx_window[1]))),
    )

    src_list = tuple(sources) if sources else (source,)
    if interval_hours is None:
        interval_hours = _interval_hours_for_sources(src_list, lu)

    staged: list[StagedFile] = []
    for src in src_list:
        if src == DEFAULT_NAM_SOURCE:
            staged.extend(
                stage_nam_analysis(
                    init_time=init_dt,
                    fxx_window=fxx_window,
                    output_root=output_root,
                    case=case,
                    source=src,
                    overwrite=stage_kwargs.get("overwrite", False),
                    connect_timeout=connect_timeout,
                    read_timeout=read_timeout,
                )
            )
        else:
            for member in members:
                staged.extend(
                    stage_reforecast(
                        init_time=init_dt,
                        variable_levels=variable_levels,
                        member=member,
                        output_root=output_root,
                        case=case,
                        source=src,
                        fxx_window=fxx_window,
                        **stage_kwargs,
                    )
                )

    manifest = build_manifest(
        case=case,
        region=region,
        requested_window=window,
        interval_hours=interval_hours,
        sources=list(src_list),
        staged=staged,
    )
    case_dir = Path(output_root) / case
    manifest_path = write_manifest(manifest, case_dir)
    LOG.info("wrote manifest %s (%d files)", manifest_path, len(staged))

    contract_path = write_contract(build_contract(manifest, lu), case_dir, case)
    LOG.info("wrote contract %s", contract_path)

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
        "--source",
        default=DEFAULT_SOURCE,
        help="Comma list of sources: gefs_reforecast, nam_analysis (default: gefs_reforecast).",
    )
    parser.add_argument(
        "--variable-levels",
        default="",
        help="Comma list of variable_level tokens (default: lookups wps_variable_levels).",
    )
    parser.add_argument(
        "--fxx-window", default="12,48", help="Lead-time window 'start,end' (manifest/bucket only)."
    )
    parser.add_argument(
        "--interval-hours", type=int, default=None,
        help="LBC interval metadata (default: derived from the forcing cadence — NAM 6 h, reforecast 3 h).",
    )
    parser.add_argument("--herbie-save-dir", default=None, help="Herbie working cache before the move.")
    parser.add_argument("--keep-herbie-cache", action="store_true", help="Copy instead of move out of cache.")
    parser.add_argument("--overwrite", action="store_true", help="Re-download even if already staged.")
    parser.add_argument(
        "--lead-subset", action="store_true",
        help="Download only lead times in --fxx-window (byte-range), not the whole f3-f240 bucket.",
    )
    parser.add_argument(
        "--http-ipv4-only", action="store_true",
        help=f"Force IPv4 for all downloads (CHPC DTN IPv6-hang workaround; also via {_IPV4_ENV}=1).",
    )
    parser.add_argument(
        "--connect-timeout", type=float, default=DEFAULT_HTTP_CONNECT_TIMEOUT,
        help=f"HTTP connect timeout (s) for direct NAM GETs (default {DEFAULT_HTTP_CONNECT_TIMEOUT}).",
    )
    parser.add_argument(
        "--read-timeout", type=float, default=DEFAULT_HTTP_READ_TIMEOUT,
        help=f"HTTP read timeout (s) for direct NAM GETs (default {DEFAULT_HTTP_READ_TIMEOUT}).",
    )
    parser.add_argument(
        "--plan", "--dry-run", dest="plan", action="store_true",
        help="List expected files/URLs/paths and total bytes, then exit (no download).",
    )
    parser.add_argument(
        "--verify-manifest", default=None, metavar="PATH",
        help="Re-hash staged files against a manifest JSON and exit (integrity check).",
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

    if args.verify_manifest:
        report = verify_manifest(args.verify_manifest)
        for r in report["results"]:
            mark = "OK  " if r["ok"] else "FAIL"
            print(f"  [{mark}] {r['local_path']}" + (f"  ({r['problem']})" if r["problem"] else ""))
        print(f"verify: {report['n_ok']}/{report['n_files']} OK")
        return 0 if report["ok"] else 1

    if args.http_ipv4_only or _ipv4_only_requested():
        _install_ipv4_only()

    members = tuple(_parse_int_csv(args.members))
    sources = tuple(s.strip() for s in args.source.split(",") if s.strip())
    variable_levels = (
        [v.strip() for v in args.variable_levels.split(",") if v.strip()]
        if args.variable_levels
        else None
    )
    fxx_parts = _parse_int_csv(args.fxx_window)
    fxx_window = (fxx_parts[0], fxx_parts[-1]) if fxx_parts else DEFAULT_FXX_WINDOW

    if args.plan:
        plan = plan_case(
            case=args.case,
            init_time=args.init_time,
            members=members,
            output_root=args.output_dir,
            fxx_window=fxx_window,
            variable_levels=variable_levels,
            sources=sources,
        )
        _print_plan(plan)
        return 0

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
            sources=sources,
            connect_timeout=args.connect_timeout,
            read_timeout=args.read_timeout,
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

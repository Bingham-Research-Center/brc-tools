"""Readers for WRF ``tslist`` output -- the ``.TS`` traces and level profiles.

WRF's time-series output is written **every model time step** at named points, so
for a 3 s inner-domain step it is the only continuous record a run produces.  The
history stream, at 10 minutes, aliases anything shorter: a gust swath ~3 km wide
crossing a point at ~12 m/s transits it in ~4 minutes, which the history stream
cannot resolve and this stream can.

Two file families share one header format:

``<PFX>.d<NN>.TS``
    19 columns of surface variables, one row per time step.

``<PFX>.d<NN>.{PH,PR,QV,TH,UU,VV,WW}``
    A time-height profile, one row per time step: the forecast hour followed by
    one value per model level (up to ``max_ts_level``).

There is also the ``tslist`` *input* file, which is what defines the points; it
is a different format and :func:`read_tslist` handles it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import polars as pl

from brc_tools.nwp.derived import wind_direction, wind_speed

#: Columns of a ``.TS`` file, in order, as written by WRF's module_tslist.
#:
#: ``t_2m_k`` is the actual 2 m temperature, not a potential temperature: for the
#: Ashley control run it reads 293.7 K where the matching ``.TH`` profile's lowest
#: level is 309.4 K, and 309.4 K reduced to the 828 hPa surface pressure is 293.0 K.
#: Worth stating because mistaking one for the other is a 15 K error.
TS_COLUMNS: tuple[str, ...] = (
    "domain",
    "ts_hour",
    "ts_id",
    "grid_i",
    "grid_j",
    "t_2m_k",
    "q_2m",
    "u_10m",
    "v_10m",
    "psfc_pa",
    "glw",
    "gsw",
    "hfx",
    "lh",
    "tsk_k",
    "tslb_1_k",
    "rainc_mm",
    "rainnc_mm",
    "clw",
)

#: Profile suffixes and what they hold.
PROFILE_KINDS: dict[str, str] = {
    "PH": "geopotential height (m)",
    "PR": "pressure (Pa)",
    "QV": "water-vapour mixing ratio (kg/kg)",
    "TH": "potential temperature (K)",
    "UU": "earth-relative U wind (m/s)",
    "VV": "earth-relative V wind (m/s)",
    "WW": "vertical velocity (m/s)",
}

_HEADER_RE = re.compile(
    r"^(?P<head>.*?)\s+"
    r"\(\s*(?P<req_lat>-?[\d.]+)\s*,\s*(?P<req_lon>-?[\d.]+)\s*\)\s+"
    r"\(\s*(?P<grid_i>\d+)\s*,\s*(?P<grid_j>\d+)\s*\)\s+"
    r"\(\s*(?P<grid_lat>-?[\d.]+)\s*,\s*(?P<grid_lon>-?[\d.]+)\s*\)\s+"
    r"(?P<elevation_m>-?[\d.]+)\s+meters\s+"
    r"(?P<init>[\d]{4}-[\d]{2}-[\d]{2}_[\d]{2}:[\d]{2}:[\d]{2})\s*$"
)

_TSLIST_LINE_RE = re.compile(
    r"^(?P<name>.{1,25}?)\s+(?P<prefix>\S+)\s+"
    r"(?P<lat>-?[\d.]+)\s+(?P<lon>-?[\d.]+)\s*$"
)


@dataclass(frozen=True)
class TSHeader:
    """The first line of any ``.TS`` or profile file."""

    name: str
    domain: int
    ts_id: int
    prefix: str
    request_lat: float
    request_lon: float
    grid_i: int
    grid_j: int
    grid_lat: float
    grid_lon: float
    elevation_m: float
    init_time: datetime


@dataclass(frozen=True)
class TSLocation:
    """One entry of a ``tslist`` input file."""

    name: str
    prefix: str
    lat: float
    lon: float


def parse_ts_header(line: str) -> TSHeader:
    """Parse a ``.TS``/profile header line.

    The name field is nominally 25 characters but station names contain both
    spaces and digits (``Dinosaur NM A3822``), so the tail is matched structurally
    and the head split from the right -- never by column position.
    """
    m = _HEADER_RE.match(line.rstrip("\n"))
    if m is None:
        raise ValueError(f"not a WRF time-series header line: {line!r}")

    head = m.group("head").strip()
    parts = head.rsplit(maxsplit=3)
    if len(parts) != 4:
        raise ValueError(f"cannot split name/domain/id/prefix out of {head!r}")
    name, domain, ts_id, prefix = parts

    return TSHeader(
        name=name.strip(),
        domain=int(domain),
        ts_id=int(ts_id),
        prefix=prefix,
        request_lat=float(m.group("req_lat")),
        request_lon=float(m.group("req_lon")),
        grid_i=int(m.group("grid_i")),
        grid_j=int(m.group("grid_j")),
        grid_lat=float(m.group("grid_lat")),
        grid_lon=float(m.group("grid_lon")),
        elevation_m=float(m.group("elevation_m")),
        init_time=datetime.strptime(m.group("init"), "%Y-%m-%d_%H:%M:%S").replace(
            tzinfo=timezone.utc
        ),
    )


def read_tslist(path: str | Path) -> list[TSLocation]:
    """Read a ``tslist`` *input* file (the three-comment-line format).

    Note the coordinates here are written ``F7.3``/``F8.3``, i.e. truncated to
    three decimals -- about 27 m of latitude.  Use them to identify a point, not
    as the authoritative station location.
    """
    out: list[TSLocation] = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = _TSLIST_LINE_RE.match(line)
        if m is None:
            raise ValueError(f"unparseable tslist line: {raw!r}")
        out.append(
            TSLocation(
                name=m.group("name").strip(),
                prefix=m.group("prefix"),
                lat=float(m.group("lat")),
                lon=float(m.group("lon")),
            )
        )
    return out


#: Time quantum used when converting ``ts_hour`` to a wall-clock time (ms).
#:
#: ``ts_hour`` is printed to six decimals, i.e. 3.6 ms resolution, so a 3 s step
#: is written as 0.000833 h = 2.9988 s.  Snapping to the nearest 10 ms recovers
#: the exact step -- WRF time steps are multiples of 0.1 s at worst -- and keeps
#: the axis uniform.  Without it the jitter accumulates into 3.002 s spacing and
#: window filtering on a 1-minute boundary starts missing rows.
_TIME_QUANTUM_MS = 10


def _valid_times(header: TSHeader, ts_hour: np.ndarray) -> list[datetime]:
    """Forecast hours to absolute UTC times, snapped to ``_TIME_QUANTUM_MS``."""
    base = header.init_time
    return [
        base
        + timedelta(
            milliseconds=int(round(h * 3_600_000.0 / _TIME_QUANTUM_MS)) * _TIME_QUANTUM_MS
        )
        for h in ts_hour
    ]


def read_ts(path: str | Path, *, derive_wind: bool = True) -> pl.DataFrame:
    """Read one ``.TS`` file into a Polars frame.

    Adds ``valid_time`` (UTC), and by default ``wind_speed_10m`` /
    ``wind_dir_10m`` via :mod:`brc_tools.nwp.derived` -- the ``u``/``v`` in this
    file are already earth-relative, so no rotation is needed.

    The header is exposed on the frame's metadata-carrying columns ``station``
    (the prefix), ``name`` and ``terrain_m``, so several stations can be
    concatenated and grouped without carrying a second object around.
    """
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError(f"empty time-series file: {path}")

    header = parse_ts_header(lines[0])
    rows = [line.split() for line in lines[1:] if line.strip()]
    if not rows:
        raise ValueError(f"time-series file has a header but no records: {path}")

    width = len(TS_COLUMNS)
    bad = {len(r) for r in rows} - {width}
    if bad:
        raise ValueError(
            f"{path.name}: expected {width} columns per record, found widths {sorted(bad)}"
        )

    data = np.asarray(rows, dtype=float)
    df = pl.DataFrame({name: data[:, k] for k, name in enumerate(TS_COLUMNS)})
    df = df.with_columns(
        pl.Series("valid_time", _valid_times(header, data[:, 1])),
        pl.lit(header.prefix).alias("station"),
        pl.lit(header.name).alias("name"),
        pl.lit(header.elevation_m).alias("terrain_m"),
    )
    if derive_wind:
        u, v = df["u_10m"].to_numpy(), df["v_10m"].to_numpy()
        df = df.with_columns(
            pl.Series("wind_speed_10m", wind_speed(u, v)),
            pl.Series("wind_dir_10m", wind_direction(u, v)),
        )
    return df


def read_ts_profile(path: str | Path) -> tuple[TSHeader, list[datetime], np.ndarray]:
    """Read one profile file, returning ``(header, valid_times, values)``.

    ``values`` is ``(n_times, n_levels)`` with level 0 the lowest model level.
    """
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError(f"empty profile file: {path}")

    header = parse_ts_header(lines[0])
    rows = [line.split() for line in lines[1:] if line.strip()]
    if not rows:
        raise ValueError(f"profile file has a header but no records: {path}")

    widths = {len(r) for r in rows}
    if len(widths) != 1:
        raise ValueError(f"{path.name}: ragged profile rows, widths {sorted(widths)}")

    data = np.asarray(rows, dtype=float)
    return header, _valid_times(header, data[:, 0]), data[:, 1:]


def ts_path(run_dir: str | Path, prefix: str, domain: int, kind: str = "TS") -> Path:
    """Path to a time-series file: ``<run_dir>/<PFX>.d<NN>.<KIND>``."""
    kind = kind.upper()
    if kind != "TS" and kind not in PROFILE_KINDS:
        raise ValueError(
            f"unknown time-series kind {kind!r}; expected 'TS' or one of {sorted(PROFILE_KINDS)}"
        )
    return Path(run_dir) / f"{prefix}.d{domain:02d}.{kind}"


def list_ts_stations(run_dir: str | Path, domain: int) -> list[str]:
    """Station prefixes that have a ``.TS`` file for ``domain``, sorted."""
    pattern = f"*.d{domain:02d}.TS"
    return sorted(p.name.split(".")[0] for p in Path(run_dir).glob(pattern))


def read_ts_profiles(
    run_dir: str | Path,
    prefix: str,
    domain: int,
    kinds: tuple[str, ...] = ("PH", "TH", "UU", "VV"),
) -> dict[str, object]:
    """Read several profile kinds for one station onto a common time axis.

    Returns ``{"header": TSHeader, "valid_times": [...], "<KIND>": (nt, nlev), ...}``.
    Raises if the requested kinds disagree on their time axis, because silently
    truncating would misalign a time-height section.
    """
    result: dict[str, object] = {}
    times: list[datetime] | None = None
    for kind in kinds:
        header, valid_times, values = read_ts_profile(ts_path(run_dir, prefix, domain, kind))
        if times is None:
            times, result["header"], result["valid_times"] = valid_times, header, valid_times
        elif valid_times != times:
            raise ValueError(
                f"{prefix}.d{domain:02d}.{kind} has {len(valid_times)} times but a sibling "
                f"kind has {len(times)}; the run may still be writing"
            )
        result[kind.upper()] = values
    return result

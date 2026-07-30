"""Convective diagnostics from WRF output, and access to the ``auxhist`` streams.

Two jobs:

**The high-cadence 2-D stream.**  A convective run typically writes a second
history stream at a much shorter interval than the main one -- on the Ashley
600 m run, ``auxhist2`` every 60 s against a 10-minute history.  That stream is
what resolves a feature the history stream aliases, and it comes with two traps
this module exists to handle (see :func:`open_auxhist` and :data:`RESET_ON_HISTORY`).

**Fields the model does not write.**  Vertical vorticity and a reflectivity-based
echo top have to be computed; ``UP_HELI_MAX`` and friends are written but only
under conditions worth being explicit about.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np

from brc_tools.nwp import wrf_output as wo
from brc_tools.nwp.wrf_section import _parse_stamp, _lon180

#: Fields whose accumulation window is reset by the **history** write, not by the
#: write of the stream they appear in.
#:
#: WRF's ``nwp_diagnostics`` maxima reset each time the history stream is written.
#: If a high-cadence auxiliary stream also carries them, its values are therefore
#: *partial running maxima* within the current history interval -- the 60 s frame
#: at 02:05Z holds the maximum since 02:00Z, not the maximum during that minute,
#: and not the maximum over the storm's life.  Reading a swath from them gives a
#: figure that looks right and is wrong, so :func:`aux_field` refuses.
RESET_ON_HISTORY: frozenset[str] = frozenset({
    "WSPD10MAX", "W_UP_MAX", "W_DN_MAX", "REFD_MAX", "UP_HELI_MAX",
    "UP_HELI_MIN", "GRPL_MAX", "GRPL_FLX_MAX", "HAIL_MAXK1", "HAIL_MAX2D",
    "HAILCAST_DIAM_MAX", "TCOLI_MAX", "AFWA_TORNADO", "REFD_COM_MAX",
})

_EARTH_R = 6_371_000.0


# --------------------------------------------------------------------------- #
# The auxiliary history stream
# --------------------------------------------------------------------------- #
def aux_prefix(domain: int, stream: int = 2) -> str:
    """Filename prefix of an auxiliary history stream, e.g. ``auxhist2_d02_``."""
    return f"auxhist{stream}_d{domain:02d}_"


def list_aux_files(run_dir: str | Path, domain: int, stream: int = 2) -> list[Path]:
    """Auxiliary-stream files for a domain, sorted by their time stamp."""
    prefix = aux_prefix(domain, stream)
    found = [
        (t, p)
        for p in Path(run_dir).glob(f"{prefix}*")
        if (t := _parse_stamp(p.name[len(prefix):])) is not None
    ]
    return [p for _, p in sorted(found)]


def list_aux_times(run_dir: str | Path, domain: int, stream: int = 2) -> list[datetime]:
    """Every valid time in an auxiliary stream, across all its files.

    Unlike ``wrfout``, an auxiliary stream usually packs many frames per file
    (``frames_per_auxhist2``), so the file stamps alone under-report the times
    available by that factor -- 6 files can hold 301 frames.  This opens each
    file to read its actual ``Times``.
    """
    times: list[datetime] = []
    for path in list_aux_files(run_dir, domain, stream):
        ds = wo.open_wrfout(path)
        try:
            times.extend(_times_in(ds))
        finally:
            ds.close()
    return sorted(times)


def _stamp_text(row) -> str:
    """One ``Times`` entry as text.

    xarray's ``concat_characters`` default means a WRF ``char Times(Time,
    DateStrLen)`` usually arrives as ``S19`` byte scalars, but an un-concatenated
    read gives a per-character array instead.  Both appear in the wild, and
    ``str()`` on the former yields ``"b'2025-...'"`` which parses as nothing, so
    handle them explicitly.
    """
    if isinstance(row, np.ndarray):
        row = row.tobytes()
    if isinstance(row, (bytes, np.bytes_)):
        return row.decode("ascii", errors="replace").strip().strip("\x00")
    return str(row).strip()


def _times_in(ds) -> list[datetime]:
    """Decode a WRF ``Times`` character array into datetimes."""
    if "Times" not in ds:
        raise KeyError("dataset has no Times variable")
    out = []
    for row in np.atleast_1d(ds["Times"].values):
        parsed = _parse_stamp(_stamp_text(row))
        if parsed is not None:
            out.append(parsed)
    return out


def open_auxhist(run_dir: str | Path, domain: int, valid_time: datetime, stream: int = 2):
    """Open the auxiliary-stream frame valid at ``valid_time``.

    Returns ``(dataset, index)`` where ``index`` selects the frame within the
    file; the dataset is left with its full ``Time`` dimension so the caller can
    read several nearby frames cheaply from one open file.

    Raises ``FileNotFoundError`` if no file covers the time.
    """
    for path in list_aux_files(run_dir, domain, stream):
        ds = wo.open_wrfout(path)
        try:
            times = _times_in(ds)
        except KeyError:
            ds.close()
            continue
        if valid_time in times:
            return ds, times.index(valid_time)
        ds.close()
    raise FileNotFoundError(
        f"no auxhist{stream}_d{domain:02d} frame valid at {valid_time:%Y-%m-%d_%H:%M:%S} "
        f"under {run_dir}"
    )


def aux_field(ds, name: str, index: int = 0) -> np.ndarray:
    """Read a 2-D field from an auxiliary-stream dataset at frame ``index``.

    Refuses the fields in :data:`RESET_ON_HISTORY`, because in this stream they
    are partial maxima over the current history interval rather than over the
    stream's own interval.  Read those from ``wrfout`` instead, where the window
    is the history interval they are actually reset against.
    """
    if name in RESET_ON_HISTORY:
        raise ValueError(
            f"{name} resets on the HISTORY write, not this stream's write, so its "
            f"value here is a partial maximum over the current history interval, "
            f"not over this frame. Read {name} from wrfout instead -- see "
            f"brc_tools.nwp.wrf_convective.RESET_ON_HISTORY."
        )
    da = ds[name]
    return np.asarray(da.isel(Time=index).values if "Time" in da.dims else da.values)


def attach_grid_coords(aux_ds, coords_from) -> dict[str, np.ndarray]:
    """Latitude/longitude/terrain for an auxiliary stream that lacks them.

    An ``iofields``-defined stream carries only the fields it was asked for, so it
    usually has **no ``XLAT``/``XLONG``/``HGT``** at all -- on the Ashley run
    ``auxhist2`` has none of the three.  Pass an open ``wrfout`` (or its path) for
    the same domain to borrow them.

    Returns ``{"latitude", "longitude", "terrain_height"}`` as 2-D arrays, with
    longitudes wrapped to -180..180, ready to merge into
    :func:`brc_tools.nwp.wrf_section.plan_dataset` via its ``extra`` argument.
    """
    close_after = False
    if isinstance(coords_from, (str, Path)):
        coords_from = wo.open_wrfout(coords_from)
        close_after = True
    try:
        lat = wo.surface_field(coords_from, "XLAT")
        lon = _lon180(wo.surface_field(coords_from, "XLONG"))
        terrain = wo.surface_field(coords_from, "HGT")
    finally:
        if close_after:
            coords_from.close()

    shape = _aux_shape(aux_ds)
    if shape is not None and lat.shape != shape:
        raise ValueError(
            f"coordinate source grid {lat.shape} does not match the auxiliary "
            f"stream grid {shape}; wrong domain?"
        )
    return {"latitude": lat, "longitude": lon, "terrain_height": terrain}


def _aux_shape(ds) -> tuple[int, int] | None:
    """``(ny, nx)`` of an auxiliary dataset, from its dimensions."""
    dims = ds.sizes
    if "south_north" in dims and "west_east" in dims:
        return int(dims["south_north"]), int(dims["west_east"])
    return None


# --------------------------------------------------------------------------- #
# Diagnostics WRF does not write
# --------------------------------------------------------------------------- #
def vertical_vorticity(ds, *, earth_relative: bool = True) -> np.ndarray:
    """Relative vertical vorticity ``dv/dx - du/dy`` (s^-1) on mass levels.

    WRF writes no vorticity field, so it is differenced from the destaggered
    winds on the model grid.  ``dx``/``dy`` come from the file's own attributes,
    and the map factor is deliberately *not* applied: at 600 m over a 213 km
    domain the Lambert map factor departs from unity by well under a percent,
    far less than the truncation error of a centred difference at the grid scale.
    """
    ue, ve = wo.earth_relative_winds(ds) if earth_relative else wo.grid_relative_winds(ds)
    dx, dy = wo.dx_dy(ds)
    dv_dx = np.gradient(ve, dx, axis=2)
    du_dy = np.gradient(ue, dy, axis=1)
    return dv_dx - du_dy


def echo_top_height(ds, *, threshold_dbz: float = 40.0, refl3d=None) -> np.ndarray:
    """Height (m ASL) of the **highest** crossing of ``threshold_dbz``.

    NaN where the column never reaches the threshold.

    Distinct from :func:`brc_tools.visualize.coldpool3d.isentrope_lid`, which
    takes the *lowest* crossing of a field that increases upward.  Reflectivity
    does the opposite -- it decreases upward above the core -- so an echo top is
    the highest crossing, and reusing the isentrope routine would silently return
    the cloud base of the echo instead of its top.
    """
    refl = wo.reflectivity(ds) if refl3d is None else np.asarray(refl3d, dtype=float)
    z = wo.geopotential_height_mass(ds)
    return highest_crossing(refl, z, threshold_dbz)


def highest_crossing(field3d, z3d, threshold: float) -> np.ndarray:
    """Height of the highest level where ``field3d`` crosses ``threshold``.

    Linearly interpolates between the bracketing levels.  Returns NaN for columns
    that never reach the threshold.  ``field3d`` and ``z3d`` are ``(nz, ny, nx)``
    with ``z3d`` increasing along axis 0.
    """
    field = np.asarray(field3d, dtype=float)
    z = np.asarray(z3d, dtype=float)
    nz = field.shape[0]

    above = field >= threshold
    ever = above.any(axis=0)
    # Highest level at or above threshold: flip, find first, map back.
    k_top = nz - 1 - np.argmax(above[::-1], axis=0)

    ny, nx = field.shape[1], field.shape[2]
    jj, ii = np.meshgrid(np.arange(ny), np.arange(nx), indexing="ij")

    z_hi = z[k_top, jj, ii]
    f_hi = field[k_top, jj, ii]
    # Interpolate toward the level above, where the field has dropped below.
    k_up = np.minimum(k_top + 1, nz - 1)
    z_up = z[k_up, jj, ii]
    f_up = field[k_up, jj, ii]

    with np.errstate(invalid="ignore", divide="ignore"):
        frac = (threshold - f_hi) / (f_up - f_hi)
    frac = np.where(np.isfinite(frac), np.clip(frac, 0.0, 1.0), 0.0)
    out = z_hi + frac * (z_up - z_hi)

    # A column whose top level is still above threshold has an unresolved top.
    out = np.where(k_top >= nz - 1, z[nz - 1, jj, ii], out)
    return np.where(ever, out, np.nan)


def storm_relative_winds(ds, storm_u: float, storm_v: float) -> tuple[np.ndarray, np.ndarray]:
    """Earth-relative winds minus a storm motion (m/s), for storm-relative vectors."""
    ue, ve = wo.earth_relative_winds(ds)
    return ue - float(storm_u), ve - float(storm_v)


def _near_mask(lat2d, lon2d, near, radius_km: float) -> np.ndarray:
    """Cells within ``radius_km`` of ``near=(lat, lon)``."""
    from brc_tools.radar.beam import great_circle_distance_m

    dist = great_circle_distance_m(float(near[0]), float(near[1]), lat2d, lon2d)
    return dist <= radius_km * 1000.0


def reflectivity_centroid(
    lat2d,
    lon2d,
    refl2d,
    *,
    threshold_dbz: float = 35.0,
    near: tuple[float, float] | None = None,
    radius_km: float = 40.0,
    largest_cluster: bool = False,
) -> tuple[float, float, float] | None:
    """Reflectivity-weighted centroid of the echo, as ``(lat, lon, n_cells)``.

    Weights by ``refl - threshold`` so the answer tracks the core rather than the
    anvil edge.  Returns ``None`` when nothing is above the threshold, which a
    caller should treat as "no storm this frame" rather than as a zero.

    A whole 213 x 171 km footprint usually holds several storms, and averaging
    across them produces a centroid that is in none of them.  Restrict with
    either or both of:

    ``near``/``radius_km``
        keep only cells within ``radius_km`` of a point.
    ``largest_cluster``
        keep only the largest connected above-threshold region.

    This is what sizes a nested domain honestly: a nest placed on the *observed*
    track is a nest with no storm in it if the model puts the cell elsewhere.
    """
    refl = np.asarray(refl2d, dtype=float)
    lat = np.asarray(lat2d, dtype=float)
    lon = np.asarray(lon2d, dtype=float)

    mask = np.isfinite(refl) & (refl >= threshold_dbz)
    if near is not None:
        mask &= _near_mask(lat, lon, near, radius_km)
    if largest_cluster and mask.any():
        from scipy import ndimage

        labels, n = ndimage.label(mask)
        if n > 1:
            sizes = ndimage.sum(mask, labels, index=np.arange(1, n + 1))
            mask = labels == (int(np.argmax(sizes)) + 1)
    if not mask.any():
        return None

    weight = refl[mask] - threshold_dbz
    total = weight.sum()
    if total <= 0.0:  # every cell sits exactly at the threshold
        weight = np.ones_like(weight)
        total = weight.sum()
    return (
        float((lat[mask] * weight).sum() / total),
        float((lon[mask] * weight).sum() / total),
        float(mask.sum()),
    )


def swath_width_km(
    lat2d,
    lon2d,
    field2d,
    threshold,
    *,
    axis: str = "ns",
    near: tuple[float, float] | None = None,
    radius_km: float = 15.0,
) -> float:
    """Extent of the ``field2d >= threshold`` region across one axis, in km.

    ``axis="ns"`` measures north-south extent, ``"ew"`` east-west.  Returns 0.0
    when nothing exceeds the threshold.

    **Pass ``near`` for any statement about a swath.**  Without it this is the
    bounding box of every exceedance in the domain, which for a multi-storm
    footprint is not a swath width at all -- on the Ashley run the domain-wide
    45 dBZ box spans 159 km while the feature of interest is ~3 km across.

    Width, not peak, is the test in CHK-SWATH: a gust field strong at one point
    and quiet 3.3 km away is <= 3 km wide, and a 20 km-wide field is a negative
    result even if its peak speed matches the report.
    """
    field = np.asarray(field2d, dtype=float)
    lat = np.asarray(lat2d, dtype=float)
    lon = np.asarray(lon2d, dtype=float)

    mask = np.isfinite(field) & (field >= threshold)
    if near is not None:
        mask &= _near_mask(lat, lon, near, radius_km)
    if not mask.any():
        return 0.0

    if axis == "ns":
        return float((lat[mask].max() - lat[mask].min()) * np.pi / 180.0 * _EARTH_R / 1000.0)
    if axis == "ew":
        coslat = float(np.cos(np.deg2rad(lat[mask].mean())))
        return float(
            (lon[mask].max() - lon[mask].min()) * np.pi / 180.0 * _EARTH_R * coslat / 1000.0
        )
    raise ValueError(f"axis must be 'ns' or 'ew', got {axis!r}")

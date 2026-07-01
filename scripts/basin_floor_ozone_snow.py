"""Seasonal Uinta Basin-floor ozone time series (minimalist PNG).

Plots a single-panel ozone figure for a winter season: ozone concentration
(ppb), one line per basin-floor AQ station, with a horizontal station legend.
Snow depth + precipitation are still fetched and cached alongside ozone (so a
snow panel can be re-added without a refetch), but the figure shows ozone only.

Stations are *discovered dynamically*: every active Synoptic station inside the
Uinta Basin below ``--max-elev-m`` (default 1900 m) that reports each variable.
No hardcoded station list -- coverage reflects whatever is actually reporting.

Data are fetched via ``brc_tools.obs.ObsSource`` (SynopticPy) month-by-month and
cached to parquet so styling can be re-iterated off-internet with ``--no-fetch``.

Run it as a CHPC **DTN** batch job (Synoptic is outbound HTTPS; compute nodes may
lack internet -- see docs/WRF-INPUT-STAGING.md §5a):

    sbatch scripts/basin_floor_ozone_snow.dtn.slurm

or directly with the env's python (login node is fine for a light pull):

    ~/software/pkg/miniforge3/envs/clyfar-nov2025/bin/python \
        scripts/basin_floor_ozone_snow.py --start 2025-12-01 --end 2026-03-31

UTC throughout (CLAUDE.md convention). Output NEVER lands in the repo checkout:
images default to CHPC group storage
(/uufs/.../lawson-group6/jrlawson/brc-tools-output, override BRC_TOOLS_OUTPUT_DIR).
"""

import argparse
import datetime as dt
import logging
import os
import re
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless (DTN / batch)

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import polars as pl

from brc_tools.obs import ObsSource

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("basin_ozone_snow")

# ── Configuration ────────────────────────────────────────────────────────────

# Uinta Basin-floor search box: lon/lat of regions.uinta_basin (lookups.toml),
# but latitude tightened to ~39.85-40.70 to exclude Carbon-County low spots
# (e.g. Price) that the elevation filter alone would keep.
# Order: (lon_min, lat_min, lon_max, lat_max)  -- Synoptic bbox order.
DEFAULT_BBOX = (-110.95, 39.85, -108.55, 40.70)

# Canonical aliases (lookups.toml) -> Synoptic variable names handled by ObsSource.
VARIABLES = ["o3_concentration", "snow_depth", "precip_1hr"]
DISCOVERY_VARS = {
    "o3_concentration": "ozone_concentration",
    "snow_depth": "snow_depth",
    "precip_1hr": "precip_accum_one_hour",
}

FT_PER_M = 1.0 / 0.3048
NAAQS_O3_PPB = 70.0  # US ozone NAAQS reference (8-hr design value)
SNOW_MIN_CM = 0.5    # drop flat/zero snow sensors (e.g. UDOT road sites at 0 cm)
SNOW_GAP_DAYS = 3    # break the snow line across reporting gaps wider than this

# "Vibrant modern" palette (user-selected). Core 6 + harmonious extras so up to
# ten stations stay distinct on a clean white background.
VIBRANT = [
    "#06b6d4", "#fb7185", "#f59e0b", "#6366f1", "#10b981",
    "#a855f7", "#ef4444", "#14b8a6", "#ec4899", "#84cc16",
]
PRECIP_COLOR = "#334155"  # slate -- the dotted basin-mean cumulative line

DEFAULT_CACHE_DIR = Path(os.path.expanduser("~/.cache/brc-tools/obs"))

# Images NEVER go inside the repo checkout. On CHPC they default to durable
# group storage; override with BRC_TOOLS_OUTPUT_DIR for other contexts.
DEFAULT_OUTPUT_ROOT = Path(os.environ.get(
    "BRC_TOOLS_OUTPUT_DIR",
    "/uufs/chpc.utah.edu/common/home/lawson-group6/jrlawson/brc-tools-output",
))
DEFAULT_OUTDIR = DEFAULT_OUTPUT_ROOT / "basin_winter"


# ── Discovery ────────────────────────────────────────────────────────────────

def discover_stations(bbox, max_elev_m):
    """Find active sub-*max_elev_m* basin stations reporting each variable.

    Returns ``(var_stids, meta)`` where *var_stids* maps each canonical alias to
    a list of station IDs, and *meta* maps stid -> {name, elev_m, lat, lon}.
    """
    from synoptic.services import Metadata

    bbox_str = ",".join(str(x) for x in bbox)
    max_ft = max_elev_m * FT_PER_M
    var_stids = {}
    meta = {}
    for alias, syn_name in DISCOVERY_VARS.items():
        try:
            md = Metadata(bbox=bbox_str, vars=syn_name, verbose=False).df()
        except Exception as exc:  # network / no stations
            LOG.warning("Metadata discovery failed for %s: %s", syn_name, exc)
            var_stids[alias] = []
            continue
        keep = md.filter(
            (pl.col("elevation") < max_ft) & (pl.col("is_active"))
        ).sort("elevation")
        stids = keep["stid"].to_list()
        var_stids[alias] = stids
        for row in keep.iter_rows(named=True):
            meta.setdefault(row["stid"], {
                "name": row["name"],
                "elev_m": round(row["elevation"] * 0.3048),
                "lat": row["latitude"],
                "lon": row["longitude"],
            })
        LOG.info("%s: %d active sub-%dm stations: %s",
                 alias, len(stids), max_elev_m, ", ".join(stids) or "(none)")
    return var_stids, meta


# ── Fetch ────────────────────────────────────────────────────────────────────

def _month_chunks(start_dt, end_dt):
    """Yield (start_str, end_str) monthly boundaries clamped to [start, end)."""
    cur = start_dt
    while cur < end_dt:
        if cur.month == 12:
            nxt = cur.replace(year=cur.year + 1, month=1, day=1)
        else:
            nxt = cur.replace(month=cur.month + 1, day=1)
        chunk_end = min(nxt, end_dt)
        yield cur.strftime("%Y-%m-%d %HZ"), chunk_end.strftime("%Y-%m-%d %HZ")
        cur = nxt


def _standardize(df):
    """Ensure the expected columns exist (null-filled) and ordered for concat."""
    cols = ["valid_time", "stid"] + VARIABLES
    for c in VARIABLES:
        if c not in df.columns:
            df = df.with_columns(pl.lit(None, dtype=pl.Float64).alias(c))
    return df.select([c for c in cols if c in df.columns])


def fetch_obs(stids, start_dt, end_dt):
    """Month-chunked ObsSource pull for *stids* over [start, end); concat to one DF."""
    obs = ObsSource()
    frames = []
    for s, e in _month_chunks(start_dt, end_dt):
        LOG.info("Fetching %d stations %s -> %s ...", len(stids), s, e)
        try:
            df = obs.timeseries(stids=stids, variables=VARIABLES, start=s, end=e)
        except Exception as exc:
            LOG.warning("  chunk %s..%s failed: %s", s, e, exc)
            continue
        if df.height:
            frames.append(_standardize(df))
        time.sleep(0.5)  # courtesy pause (mirrors obs/scanner.py)
    if not frames:
        raise RuntimeError("No observation data returned for any chunk.")
    return pl.concat(frames, how="vertical_relaxed").sort(["stid", "valid_time"])


# ── Processing ───────────────────────────────────────────────────────────────

def _label(stid, meta):
    """Friendly station label from metadata name (falls back to the stid)."""
    name = (meta.get(stid, {}).get("name") or stid).strip()
    # UDOT road sensors: "US-40 at MP 105 Myton" / "US-40 @ Starvation" -> place.
    name = re.sub(r"(?i)^us-40\s*(?:at\s*mp\s*\d+|@)\s*", "", name)
    name = re.sub(r"(?i)[-\s]*quarry area\b", "", name)        # COOP quarry tag
    name = re.sub(r"(?i)\bcoop[ab]?\b", "", name).strip(" -,")  # COOP boilerplate
    if name.isupper() or name.islower():
        name = name.title()
    name = re.sub(r"(?i)\bnational monument\b", "NM", name)
    name = re.sub(r"\bNm\b", "NM", name)
    name = name.strip(" -,")
    return (name[:18] if len(name) > 18 else name) or stid


def build_series(df, var_stids, meta, start_dt, end_dt, ozone_stat):
    """Turn the raw wide DF into plot-ready per-station series + precip curve.

    Returns dict with keys ``ozone`` / ``snow`` (each {label: (x, y)}) and
    ``precip`` ((x, cumulative_mm) or None).
    """
    daily = ozone_stat == "dailymax"
    out = {"ozone": {}, "snow": {}, "precip": None}

    if daily:
        df = df.with_columns(pl.col("valid_time").dt.date().alias("date"))

    # Ozone -------------------------------------------------------------------
    for stid in var_stids.get("o3_concentration", []):
        sub = df.filter((pl.col("stid") == stid) & pl.col("o3_concentration").is_not_null())
        if sub.height == 0:
            continue
        if daily:
            g = sub.group_by("date").agg(pl.col("o3_concentration").max().alias("y")).sort("date")
            x = [dt.datetime(d.year, d.month, d.day) for d in g["date"].to_list()]
        else:
            g = sub.sort("valid_time")
            x = g["valid_time"].to_list()
            g = g.rename({"o3_concentration": "y"})
        out["ozone"][_label(stid, meta)] = (x, g["y"].to_list())

    # Snow depth (mm -> cm) ---------------------------------------------------
    # Basin-floor snow is shallow + sparsely reported (daily COOP, whole-inch
    # steps). Drop flat/zero sensors, and in daily mode reindex to a dense grid
    # with nulls so multi-day gaps BREAK the line instead of interpolating.
    ndays = (end_dt.date() - start_dt.date()).days
    dense_dates = [start_dt.date() + dt.timedelta(days=i) for i in range(ndays)]
    for stid in var_stids.get("snow_depth", []):
        sub = df.filter((pl.col("stid") == stid) & pl.col("snow_depth").is_not_null())
        if sub.height == 0:
            continue
        if daily:
            g = sub.group_by("date").agg(pl.col("snow_depth").mean().alias("mm")).sort("date")
            day_cm = {d: mm / 10.0 for d, mm in zip(g["date"].to_list(), g["mm"].to_list())}
            if not day_cm or max(day_cm.values()) < SNOW_MIN_CM:
                continue  # flat/zero road sensor or trace-only -- skip clutter
            x = [dt.datetime(d.year, d.month, d.day) for d in dense_dates]
            y = [day_cm.get(d, float("nan")) for d in dense_dates]  # nan -> line break
        else:
            g = sub.sort("valid_time")
            cm = [v / 10.0 for v in g["snow_depth"].to_list()]
            if not cm or max(cm) < SNOW_MIN_CM:
                continue
            x, y = g["valid_time"].to_list(), cm
        out["snow"][_label(stid, meta)] = (x, y)

    # Basin-mean cumulative precipitation -------------------------------------
    pr = df.filter(pl.col("precip_1hr").is_not_null())
    if pr.height:
        if daily:
            per = pr.group_by(["stid", "date"]).agg(pl.col("precip_1hr").sum().alias("tot"))
            basin = per.group_by("date").agg(pl.col("tot").mean().alias("mean")).sort("date")
            # Dense daily index so the cumulative curve does not skip empty days.
            ndays = (end_dt.date() - start_dt.date()).days
            idx = pl.DataFrame({"date": [start_dt.date() + dt.timedelta(days=i) for i in range(ndays)]})
            basin = idx.join(basin, on="date", how="left").with_columns(
                pl.col("mean").fill_null(0.0)
            ).sort("date")
            x = [dt.datetime(d.year, d.month, d.day) for d in basin["date"].to_list()]
            cum = basin["mean"].cum_sum().to_list()
        else:
            per = pr.group_by(["stid", "valid_time"]).agg(pl.col("precip_1hr").sum().alias("tot"))
            basin = per.group_by("valid_time").agg(pl.col("tot").mean().alias("mean")).sort("valid_time")
            x = basin["valid_time"].to_list()
            cum = basin["mean"].cum_sum().to_list()
        out["precip"] = (x, cum)

    return out


# ── Plot ─────────────────────────────────────────────────────────────────────

def _apply_style():
    plt.rcParams.update({
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "axes.edgecolor": "#94a3b8",
        "axes.linewidth": 0.8,
        # Helvetica is the brc-tools house viz font (CLAUDE.md). It is proprietary
        # and absent on CHPC, so fall back to Nimbus Sans -- the URW metric-clone
        # of Helvetica -- then Arial/Liberation Sans, then DejaVu Sans.
        "font.family": "sans-serif",
        "font.sans-serif": ["Helvetica", "Nimbus Sans", "Arial",
                            "Liberation Sans", "DejaVu Sans"],
        "axes.titlesize": 12,
        "axes.titleweight": "semibold",
        "axes.labelsize": 11,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "xtick.color": "#475569",
        "ytick.color": "#475569",
        "legend.fontsize": 9,
        "legend.frameon": False,
        "axes.spines.top": False,
    })


def _despine(ax):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(length=3, color="#94a3b8")


def plot_ozone(series, *, title, subtitle, ozone_stat, outpath):
    """Render the single-panel minimalist ozone figure (11:8) and save a PNG."""
    _apply_style()
    # 11:8 canvas *including* the legend; no bbox_inches='tight' so the saved
    # aspect ratio is exactly 11:8. A reserved bottom band holds the legend.
    fig, ax = plt.subplots(figsize=(11, 8))

    for i, (label, (x, y)) in enumerate(series["ozone"].items()):
        ax.plot(x, y, color=VIBRANT[i % len(VIBRANT)], lw=1.6, label=label)

    ax.axhline(NAAQS_O3_PPB, color="#94a3b8", lw=1.0, ls=(0, (6, 4)), zorder=1)
    ax.text(0.004, NAAQS_O3_PPB, " NAAQS 70 ppb", transform=ax.get_yaxis_transform(),
            va="bottom", ha="left", fontsize=9, color="#64748b")

    stat_lbl = "daily max" if ozone_stat == "dailymax" else "hourly"
    ax.set_ylabel(f"Ozone ({stat_lbl}, ppb)")
    ax.set_ylim(bottom=0)
    ax.grid(True, axis="y", color="#e2e8f0", lw=0.7)
    ax.set_axisbelow(True)
    _despine(ax)

    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.xaxis.set_minor_locator(mdates.WeekdayLocator(byweekday=mdates.MO))
    for lbl in ax.get_xticklabels():
        lbl.set_ha("center")

    # Tessellating legend: a horizontal band centred under the axes, wrapped into
    # ~two balanced rows so it packs the wide canvas without hanging off the edge.
    n = len(series["ozone"])
    if n:
        handles, labels = ax.get_legend_handles_labels()
        ncol = n if n <= 5 else -(-n // 2)  # ceil(n/2) -> two balanced rows
        fig.legend(handles, labels, loc="lower center", bbox_to_anchor=(0.5, 0.015),
                   ncol=ncol, frameon=False, handlelength=1.6, columnspacing=1.8,
                   title="Basin-floor ozone sites", title_fontsize=9)

    fig.suptitle(title, x=0.5, y=0.975, fontsize=16, fontweight="semibold", ha="center")
    ax.set_title(subtitle, fontsize=10, color="#64748b", loc="left", pad=8,
                 fontweight="normal")

    try:
        from brc_tools.nwp.case_study import annotate
        annotate(fig, "Source: Synoptic Data PBC · Bingham Research Center")
    except Exception:
        fig.text(0.99, 0.008, "Source: Synoptic Data PBC · Bingham Research Center",
                 fontsize=6, ha="right", va="bottom", fontstyle="italic", color="gray")

    fig.subplots_adjust(left=0.07, right=0.97, top=0.90, bottom=0.17)
    outpath.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(outpath, dpi=300)  # exact 11:8 (legend inside the canvas)
    plt.close(fig)
    LOG.info("Saved figure: %s", outpath)


# ── Cache ────────────────────────────────────────────────────────────────────

def _cache_paths(cache_dir, start_dt, end_dt):
    tag = f"{start_dt:%Y%m%d}_{end_dt:%Y%m%d}"
    return (cache_dir / f"basin_obs_{tag}.parquet",
            cache_dir / f"basin_meta_{tag}.parquet")


# ── Main ─────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--start", default="2025-12-01", help="UTC start date YYYY-MM-DD")
    p.add_argument("--end", default="2026-03-31", help="UTC end date YYYY-MM-DD (inclusive)")
    p.add_argument("--max-elev-m", type=float, default=1900.0,
                   help="Keep stations below this elevation (m). Default 1900.")
    p.add_argument("--ozone-stat", choices=["dailymax", "hourly"], default="dailymax",
                   help="Aggregate to daily values (default) or plot raw hourly.")
    p.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    p.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    p.add_argument("--refresh", action="store_true", help="Ignore cache; refetch.")
    p.add_argument("--no-fetch", action="store_true",
                   help="Plot from cached parquet only (no network).")
    return p.parse_args()


def main():
    args = parse_args()

    # IPv4-only guard for DTN (Synoptic is outbound HTTPS); shares the staging fix.
    if os.environ.get("BRC_TOOLS_HTTP_IPV4_ONLY"):
        try:
            from brc_tools.nwp.wrf_staging import _install_ipv4_only
            _install_ipv4_only()
        except Exception as exc:
            LOG.warning("Could not enable IPv4-only mode: %s", exc)

    start_dt = dt.datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
    # end is inclusive -> fetch through end-of-day by extending one day.
    end_dt = (dt.datetime.strptime(args.end, "%Y-%m-%d")
              + dt.timedelta(days=1)).replace(tzinfo=dt.timezone.utc)

    obs_cache, meta_cache = _cache_paths(args.cache_dir, start_dt, end_dt)

    if args.no_fetch or (not args.refresh and obs_cache.exists()):
        if not obs_cache.exists():
            raise SystemExit(f"--no-fetch set but cache missing: {obs_cache}")
        LOG.info("Loading cached obs: %s", obs_cache)
        df = pl.read_parquet(obs_cache)
        meta_df = pl.read_parquet(meta_cache)
        meta = {r["stid"]: r for r in meta_df.iter_rows(named=True)}
        var_stids = {
            "o3_concentration": meta_df.filter(pl.col("has_o3"))["stid"].to_list(),
            "snow_depth": meta_df.filter(pl.col("has_snow"))["stid"].to_list(),
            "precip_1hr": meta_df.filter(pl.col("has_precip"))["stid"].to_list(),
        }
    else:
        var_stids, meta = discover_stations(DEFAULT_BBOX, args.max_elev_m)
        all_stids = sorted({s for v in var_stids.values() for s in v})
        if not all_stids:
            raise SystemExit("No basin-floor stations discovered.")
        df = fetch_obs(all_stids, start_dt, end_dt)
        args.cache_dir.mkdir(parents=True, exist_ok=True)
        df.write_parquet(obs_cache)
        meta_df = pl.DataFrame([
            {"stid": s, "name": m["name"], "elev_m": m["elev_m"],
             "lat": m["lat"], "lon": m["lon"],
             "has_o3": s in var_stids.get("o3_concentration", []),
             "has_snow": s in var_stids.get("snow_depth", []),
             "has_precip": s in var_stids.get("precip_1hr", [])}
            for s, m in meta.items()
        ])
        meta_df.write_parquet(meta_cache)
        LOG.info("Cached obs (%d rows) -> %s", df.height, obs_cache)

    series = build_series(df, var_stids, meta, start_dt, end_dt, args.ozone_stat)
    LOG.info("Plotting %d ozone station series (ozone-only figure)",
             len(series["ozone"]))

    end_label = dt.datetime.strptime(args.end, "%Y-%m-%d")
    season = f"{start_dt:%-d %b %Y} – {end_label:%-d %b %Y}"
    agg = "daily-max" if args.ozone_stat == "dailymax" else "hourly"
    title = "Uinta Basin-floor winter ozone"
    subtitle = (f"{agg.capitalize()} ozone at sub-{int(args.max_elev_m)} m basin "
                f"stations · {season} · Synoptic")
    outpath = args.outdir / f"basin_floor_ozone_{start_dt:%Y%m%d}_{end_dt:%Y%m%d}.png"
    plot_ozone(series, title=title, subtitle=subtitle,
               ozone_stat=args.ozone_stat, outpath=outpath)


if __name__ == "__main__":
    main()

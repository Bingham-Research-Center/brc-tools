# WRF trajectories — `brc_tools.nwp.wrf_trajectories`

Offline kinematic trajectories, forward or backward, from any WRF stream that carries
`U, V, W, PH, PHB` (and `T` if potential temperature along the path is wanted). Built for
drainage questions: *where did the air at this canyon mouth come from, and where does the air
leaving this bench go?*

```python
from datetime import datetime
import numpy as np
from brc_tools.nwp import wrf_trajectories as wt

run = "/path/to/wrf_run"                                   # auxhist2_d02_* and wrfout_d02_* inside
statics = wt.read_statics(wt.stream_times(run, 2, "wrfout")[0][1])
release = wt.release_points(statics, lats=[40.56], lons=[-109.66], levels=(0, 1, 2, 3, 4))
back = wt.back_trajectories(run, 2, release, datetime(2025, 1, 27, 9), 6.0,
                            stream="auxhist2", statics=statics, release_is_index=True, kmax=60)
back[["lat", "lon", "z_agl", "theta"]]                    # (time, parcel)
```

`release` comes in two forms. Without a flag it is `(lat, lon, level)`; what
`release_points` returns is `(i, j, k)` grid indices and needs `release_is_index=True`.
A release that falls off the grid raises in either form -- that is how the two are kept from
being confused, since `(i, j, k)` read as degrees lands far outside any domain -- and so does
a release above the `kmax` levels read. Times are naive UTC; an aware `t0` is converted.

| function | purpose |
|---|---|
| `stream_times(run_dir, domain, stream)` | every frame of a stream, both file-name conventions (`nocolons` or not); a file holding several frames (`frames_per_auxhist2`) is listed once per frame, timed from its `Times` |
| `read_statics(path)` | latitude, longitude, terrain, map factors (`MAPFAC_MX`/`MAPFAC_MY`, else `MAPFAC_M`), grid spacing from any wrfout |
| `release_points(statics, lats, lons, levels)` | `(i, j, k)` release array from places and mass-level indices (pass it with `release_is_index=True`) |
| `back_trajectories` / `forward_trajectories` / `trajectories` | file drivers; return an `xarray.Dataset` on `(time, parcel)` |
| `integrate(frames, release_ijk, t_start, hours, ...)` | the integrator on plain arrays (`Frame` objects); what the tests use |
| `frame_from_fields`, `load_frame` | one output time converted to index-space velocities |
| `sampling_separation(reference, other)` | end-point distance and height difference between two sets of trajectories |

## Method

A parcel is carried as fractional grid indices `(i, j, k)` on the mass grid:

```
di/dt = u m_x / dx        dj/dt = v m_y / dy
dk/dt = ( w - u dz/dx|k - v dz/dy|k - dz/dt|k ) / ( dz/dk )
```

with `u, v` grid-relative, `m_x, m_y` the map factors along each axis (equal on a conformal
projection, not on a lat-lon grid) and `z` the height of the model levels. The
vertical equation is the motion *relative to the levels*: air flowing parallel to terrain keeps
its level however steep the slope, where integrating `w` in height coordinates would walk it
into the hillside. Fields are trilinear in index space and linear in time between frames; the
step is RK4 (RK2 optional), 20 s by default. Parcels are held at or above the lowest mass level
and become NaN once they leave the domain.

It is not a dispersion model: there is no sub-grid mixing, so a trajectory is the path of the
resolved flow.

## How good is it — what the stream cadence costs

The integration step is not the error; the spacing of the frames is. A software test on an
archived run with a 10-minute 3-D stream (ub-wx `drainage-canyons-gigawatts`,
`analysis/iter5/wrf_traj_sampling.py`, 50 parcels, six hours back; not a science result):

| frames every | median end-point distance from the 10-min answer | 90th percentile | median as a share of the path |
|---|---|---|---|
| 20 min | 4.2 km | 14.7 km | 8 % |
| 30 min | 5.8 km | 18.6 km | 14 % |
| 60 min | 11.7 km | 35.8 km | 25 % |
| 10 min, step 10 s instead of 20 s | 0.004 km | 0.05 km | — |

Halving the interval from 20 to 10 minutes still moved the median end point 4 km, so the
10-minute answer is not itself converged: write the winds as often as the budget allows, and
check against WRF's own online trajectories where it matters.

## WRF's online trajectories, for comparison

`traj_opt = 1` (`&physics`) with `num_traj` (`&domains`) advances up to 1000 parcels per domain
at every model time step (`dyn_em/module_em.F`, subroutine `trajectory`; first-order in time, with
the time-averaged mass fluxes) from release points listed in `wrfinput_traj_d<NN>` (namelists
`traj_default` and `traj_spec`: longitude, latitude, height above ground, start and stop time, and
the names of dynamic, hydrometeor and tracer fields to sample along the path;
`share/module_trajectory.F`). Output goes to `wrfout_traj_d<NN>`. It is forward only and the
parcels must be chosen before the run. That makes it the reference for testing this module in
forward mode on a short run, and the complement to it in production: online forward from the
source regions, offline backward from the stations.

## Tests

`tests/test_wrf_trajectories.py` (15 tests, synthetic frames): a uniform wind displaces exactly;
solid-body rotation closes and RK4 beats RK2; flow parallel to sloping levels stays on its level;
horizontal flow over a slope crosses levels at constant height; levels that rise with the air do
not move the parcel; backward undoes forward in an unsteady flow; a parcel leaving the grid is
dropped; a parcel is held at the lowest level; release points invert the grid; the file driver
reads both file-name conventions, and every frame of a file that packs several; the two map
factors are kept apart; releases off the grid or above `kmax` raise; an aware `t0` is converted.

# The reference temperature for heat-deficit budgets (`brc_tools.nwp.wrf_deficit_reference`)

`wrf_output.heat_deficit_field` measures the valley heat deficit against a *crest*
reference: each column's own potential temperature at `crest_m`, at that output
time. That is right for a map ("how much colder than the air above it is this
column now") and wrong for a budget, because the datum drifts through the night
and differs between columns, so the deficit is not conserved under adiabatic
advection. The transport `Phi` through a canyon mouth then depends on the
reference height: Dry Fork's September night mean was 12.8 GW at 2600 m and
19.2 GW at 3340 m, and a 1.2 K change of a fixed datum moved it three-fold
(ub-wx `drainage-canyons-gigawatts`, CHK-REFERENCE). This module is the budget's
datum.

## The sunset profile

`sunset_profile(ds, floor_mask, time=...)` builds `theta_ref(z)` from one wrfout at
the pre-sunset hour:

- **below the mixed-layer top**: the mixed-layer potential temperature over the
  receiving floor -- per column the mean theta in the lowest `ml_depth_m`
  (500 m), reduced over the floor columns by `ml_stat` (`max` by default, so a
  floor cell that is already shaded cannot drag the datum down). This is the
  temperature the drainage air had before the slopes started cooling; on the
  September 2025 night it was the 23Z value (314.9 K), the last hour of the
  mixed-layer maximum, and it was the datum that closed the catchment budgets.
- **above it**: the floor-mean theta in 25 m bins of height ASL, floored at the
  mixed-layer value and made non-decreasing. A single value over 2 km of relief
  counts ambient stratification as deficit (the 100 GW pre-sunset spikes of the
  first budgets); a profile does not.

The deficit against it is *cooling since the profile was taken, at that height*:
materially conserved under adiabatic motion, and on a clear day the residual layer
that caps the pool *is* this profile, so it is also the datum the pool depth is
measured against.

## The error bar

The drainage layer is only 1-3 K colder than the air it displaces, so where the
zero of "deficit" sits is a first-order term. Every number measured against a
fixed datum is therefore reported at `ref - delta` and `ref + delta`
(`two_datum`, `at_two_datums`; 0.5 K by default) beside its central value, and the
`CatchmentTerms` record carries `storage_lo/hi` and `export_lo/hi`. The datum-free
counterpart is the tracer pair: seed `c = 1` and `c_theta = theta` over a
catchment, and `c_theta / c - theta` downstream is the cooling that air has
undergone since seeding, with no reference at all.

## The fields

`deficit_fixed_fields(ds, ref, cap_agl_m=1500)` returns H (J m-2) and F (W m-1) as
`sum_k rho c_p max(theta_ref(z_k) - theta_k, 0) dz_k` (and with `u_k`, `v_k`) below
`cap_agl_m` above ground; `ref` is a `SunsetProfile` or a float. Box integration in
height (not the frozen kernel's trapezoid in pressure) so catchment sums are
additive in cell mass. `longwave_production_field` adds the radiative term when the
run wrote `RTHRATLW` (the history name; `RTHRATENLW` is restart-only), which is what
the September/November 2025 budgets could not close without.
`catchment_budget_terms` does one output time for many catchments and boxes with
the transects reused.

## The sidecar (cross-repo contract)

`SunsetProfile.to_json()` writes `theta_ref_<case>_<night>.json`:

```json
{"schema": 1, "method_version": "sunset-profile-1",
 "z_asl_m": [...], "theta_k": [...],
 "valid_time": "2025-01-27T00:00:00Z", "mixed_layer_theta_k": 289.4,
 "ml_depth_m": 500.0, "top_m": 6000.0, "ml_stat": "max",
 "floor_label": "HGT < 1800 m in the Ashley box", "floor_cells": 3204,
 "run_id": "...", "domain": 2, "source_file": "wrfout_d02_2025-01-27_00:00:00",
 "case": "gigawatts", "night": "20250126", "notes": ""}
```

`theta_ref(z)` is linear interpolation in `z_asl_m`, clamped at both ends. Any
consumer (brc-voxel-viz's isosurfaces, a figure engine, an offline budget) that
draws "colder than the sunset profile" from this file draws the same surface this
module budgets against; `schema` bumps on any incompatible change. The
`sunset-profile-1` method is the one the ub-wx pre-flight report (September 2026)
adopted; the crest kernel stays what it was, for maps.

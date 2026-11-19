# Forecast verification

For station and waypoint errors (bias, MAE, RMSE and correlation), use the
[deterministic verification walkthrough](../../docs/walkthroughs/verify.md).
The experimental `infogain.py` module implements a separate information-gain method.

For Clyfar ozone possibilities, follow the [scorecard manuscript’s current
handoff](https://github.com/Bingham-Research-Center/forecast-verification-scorecard/blob/main/docs/clyfar-scoring.md).
The manuscript owns the equations, reference evaluator and synthetic checks.
The seasonal evaluation maintains the ozone adapter and records the method
commit and evaluator hash. Keep shared transport, data access and deterministic
verification here. Route changes to possibility scoring through the manuscript.

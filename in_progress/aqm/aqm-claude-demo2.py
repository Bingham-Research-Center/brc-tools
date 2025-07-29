from aqm_explorer import process_forecast_range, create_valid_time_comparison

# Process forecasts for hours 8 through 24
results = process_forecast_range(
    "2024-04-07 12:00",
    product="ave_8hr_o3"
)

# Compare forecasts from multiple initialization times valid at the same time
comparison = create_valid_time_comparison(
    "2024-04-08 18:00",  # Valid time
    lookback_days=2       # Compare with forecasts from the past 2 days
)
"""End-to-end test: Download GEFS → Process with Ensemble → Visualize → Export JSON

This script demonstrates the complete workflow:
1. Download GEFS data using standardized download function
2. Load into Ensemble class
3. Compute ensemble statistics and probabilities
4. Create visualizations
5. Export to BasinWx JSON format

Author: JRL, 2025-10-26
"""

import sys
import datetime
import logging
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
import xarray as xr

# Add paths
sys.path.insert(0, '/Users/johnlawson/PycharmProjects/brc-tools')
sys.path.insert(0, '/Users/johnlawson/PycharmProjects/brc-tools/in_progress')

from brc_tools.download.nwp import download_gefs_ensemble
from ensemble.ensemble import Ensemble
from brc_tools.delivery.forecast_api import create_meteogram_json, save_json_with_timestamp

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_download(test_mode: bool = True):
    """Test downloading GEFS data.

    Args:
        test_mode: If True, download minimal data for quick testing
    """
    logger.info("=" * 60)
    logger.info("STEP 1: Download GEFS Data")
    logger.info("=" * 60)

    # Configuration
    if test_mode:
        logger.info("Running in TEST MODE (quick download)")
        init_time = datetime.datetime(2025, 10, 26, 0)  # Adjust to recent date
        members = [0, 1, 2]  # Control + 2 perturbations
        forecast_hours = range(0, 48, 6)  # 2 days
    else:
        logger.info("Running in FULL MODE (operational download)")
        init_time = datetime.datetime(2025, 10, 26, 0)
        members = 'all'
        forecast_hours = range(0, 384, 6)  # 15 days for clyfar

    logger.info(f"Init time: {init_time}")
    logger.info(f"Members: {members}")
    logger.info(f"Forecast hours: {list(forecast_hours)[0]} to {list(forecast_hours)[-1]}")

    # Download
    try:
        save_path = download_gefs_ensemble(
            init_time=init_time,
            members=members,
            forecast_hours=forecast_hours,
            subset_bbox=(39.4, 41.1, -110.9, -108.5),  # Uinta Basin
            save_dir='./test_data',
            save_format='zarr',
            overwrite=False
        )
        logger.info(f"✓ Download successful: {save_path}")
        return save_path

    except Exception as e:
        logger.error(f"✗ Download failed: {e}")
        raise


def test_load_and_analyze(zarr_path: Path):
    """Test loading data into Ensemble and computing statistics."""
    logger.info("=" * 60)
    logger.info("STEP 2: Load into Ensemble Class")
    logger.info("=" * 60)

    # Load
    ens = Ensemble.from_zarr(zarr_path)
    logger.info(f"✓ Ensemble loaded:")
    logger.info(ens)

    # Compute statistics
    logger.info("\n" + "=" * 60)
    logger.info("STEP 3: Compute Ensemble Statistics")
    logger.info("=" * 60)

    # Find temperature variable (Herbie naming may vary)
    temp_var = None
    for var in ens.ds.data_vars:
        if 't2m' in var.lower() or 'tmp' in var.lower():
            temp_var = var
            break

    if temp_var is None:
        logger.warning("No temperature variable found, using first variable")
        temp_var = list(ens.ds.data_vars)[0]

    logger.info(f"Using variable: {temp_var}")

    # Ensemble mean
    mean = ens.mean(temp_var)
    logger.info(f"✓ Mean computed: shape {mean.shape}")

    # Ensemble spread
    spread = ens.std(temp_var)
    logger.info(f"✓ Spread computed: shape {spread.shape}")

    # Exceedance probability (freezing temps)
    prob_freeze = ens.get_exceedance_prob(
        var=temp_var,
        threshold=273.15,  # 0°C in Kelvin
        operator='<'
    )
    logger.info(f"✓ Freezing probability computed")

    # Find representative member
    first_time = ens.ds.time.values[0]
    repr_member = ens.closest_to_mean(temp_var, time=first_time)
    logger.info(f"✓ Representative member: {repr_member}")

    return ens, temp_var


def test_visualize(ens: Ensemble, temp_var: str, save_dir: str = './test_plots'):
    """Create visualization plots."""
    logger.info("=" * 60)
    logger.info("STEP 4: Create Visualizations")
    logger.info("=" * 60)

    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)

    # Time series at a point (Vernal, UT area)
    location = (40.5, -110.0)
    logger.info(f"Creating time series at {location}")

    # Extract point data
    data_point = ens.ds[temp_var].sel(
        latitude=location[0],
        longitude=location[1],
        method='nearest'
    )

    # Convert to Celsius for plotting
    data_point_c = data_point - 273.15

    # Compute statistics
    mean = data_point_c.mean(dim='member')
    std = data_point_c.std(dim='member')
    p10 = data_point_c.quantile(0.1, dim='member')
    p90 = data_point_c.quantile(0.9, dim='member')

    # Plot
    fig, axes = plt.subplots(2, 1, figsize=(12, 8))

    # Plot 1: Ensemble spread
    ax = axes[0]
    times = range(len(mean))

    # Individual members (light gray)
    for member in data_point_c.member.values:
        ax.plot(times, data_point_c.sel(member=member).values,
                color='gray', alpha=0.3, linewidth=0.5)

    # Mean
    ax.plot(times, mean.values, 'k-', linewidth=2, label='Mean')

    # Spread
    ax.fill_between(times, (mean - std).values, (mean + std).values,
                     alpha=0.3, label='Mean ± 1σ')
    ax.fill_between(times, p10.values, p90.values,
                     alpha=0.2, label='10th-90th percentile')

    ax.axhline(0, color='r', linestyle='--', alpha=0.5, label='Freezing')
    ax.set_ylabel('Temperature (°C)')
    ax.set_title(f'GEFS Ensemble Forecast - Location: {location}')
    ax.legend()
    ax.grid(True, alpha=0.3)

    # Plot 2: Exceedance probability
    ax = axes[1]
    prob_freeze = ens.get_exceedance_prob(temp_var, threshold=273.15, operator='<')
    prob_point = prob_freeze.sel(
        latitude=location[0],
        longitude=location[1],
        method='nearest'
    )

    ax.plot(times, prob_point.values, 'b-', linewidth=2)
    ax.fill_between(times, 0, prob_point.values, alpha=0.3)
    ax.set_ylabel('Probability (%)')
    ax.set_xlabel('Forecast Hour')
    ax.set_title('Probability of Freezing Temperatures (T < 0°C)')
    ax.set_ylim(0, 100)
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plot_path = save_dir / 'ensemble_timeseries.png'
    plt.savefig(plot_path, dpi=150, bbox_inches='tight')
    logger.info(f"✓ Time series plot saved: {plot_path}")
    plt.close()

    # Spatial plot (mean at first time)
    logger.info("Creating spatial map")
    fig, ax = plt.subplots(figsize=(10, 8))

    mean_map = ens.mean(temp_var).isel(time=0) - 273.15

    im = ax.pcolormesh(
        mean_map.longitude,
        mean_map.latitude,
        mean_map.values,
        cmap='RdYlBu_r',
        shading='auto'
    )
    plt.colorbar(im, ax=ax, label='Temperature (°C)')
    ax.set_xlabel('Longitude')
    ax.set_ylabel('Latitude')
    ax.set_title(f'GEFS Ensemble Mean - {ens.ds.time.values[0]}')

    plot_path = save_dir / 'ensemble_spatial.png'
    plt.savefig(plot_path, dpi=150, bbox_inches='tight')
    logger.info(f"✓ Spatial plot saved: {plot_path}")
    plt.close()


def test_json_export(ens: Ensemble, temp_var: str, save_dir: str = './test_json'):
    """Test JSON export for BasinWx."""
    logger.info("=" * 60)
    logger.info("STEP 5: Export to JSON")
    logger.info("=" * 60)

    # Create meteogram JSON
    location = (40.5, -110.0)
    json_data = create_meteogram_json(
        ensemble=ens,
        location=location,
        location_name="Vernal, UT (Test)"
    )

    # Save
    json_path = save_json_with_timestamp(
        json_data,
        output_dir=save_dir,
        prefix="test_meteogram"
    )

    logger.info(f"✓ JSON saved: {json_path}")
    logger.info(f"  Variables: {list(json_data['variables'].keys())}")
    logger.info(f"  Location: {json_data['metadata']['location']}")

    return json_path


def main(test_mode: bool = True):
    """Run complete end-to-end test.

    Args:
        test_mode: If True, use minimal data for quick testing
    """
    logger.info("\n" + "=" * 60)
    logger.info("GEFS ENSEMBLE - END-TO-END TEST")
    logger.info("=" * 60)
    logger.info(f"Mode: {'TEST (quick)' if test_mode else 'FULL (operational)'}")

    try:
        # 1. Download
        zarr_path = test_download(test_mode=test_mode)

        # 2. Load and analyze
        ens, temp_var = test_load_and_analyze(zarr_path)

        # 3. Visualize
        test_visualize(ens, temp_var)

        # 4. Export JSON
        test_json_export(ens, temp_var)

        logger.info("\n" + "=" * 60)
        logger.info("✓ ALL TESTS PASSED")
        logger.info("=" * 60)
        logger.info("\nCheck outputs:")
        logger.info("  - Data: ./test_data/")
        logger.info("  - Plots: ./test_plots/")
        logger.info("  - JSON: ./test_json/")

        return True

    except Exception as e:
        logger.error(f"\n✗ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Test ensemble forecast pipeline')
    parser.add_argument(
        '--full',
        action='store_true',
        help='Run full operational test (slow, downloads all GEFS data)'
    )

    args = parser.parse_args()

    success = main(test_mode=not args.full)
    sys.exit(0 if success else 1)

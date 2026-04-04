#!/usr/bin/env python3
"""Operational script for GEFS ensemble forecasts.

Designed to run via cron on CHPC. Downloads latest GEFS, processes with
Ensemble class, exports to JSON for BasinWx delivery.

Cron schedule examples:
    # Run 4x/day after GEFS cycles (with 4-hour delay for processing)
    30 4,10,16,22 * * * /path/to/run_operational_gefs.py

    # Run once daily at 5:30 UTC
    30 5 * * * /path/to/run_operational_gefs.py

Author: JRL, 2025-10-26
"""

import sys
import os
import datetime
import logging
from pathlib import Path
import json
import traceback

# Add paths (adjust for your CHPC setup)
sys.path.insert(0, '/uufs/chpc.utah.edu/common/home/u0123456/brc-tools')
sys.path.insert(0, '/uufs/chpc.utah.edu/common/home/u0123456/brc-tools/in_progress')

from brc_tools.download.nwp import download_latest_gefs_for_clyfar, get_latest_gefs_init
from ensemble.ensemble import Ensemble
from brc_tools.delivery.forecast_api import create_meteogram_json, save_json_with_timestamp

# Configuration
CONFIG = {
    # Paths (UPDATE these for your CHPC setup)
    'data_dir': '/scratch/general/lustre/u0123456/gefs',
    'json_output_dir': '/uufs/chpc.utah.edu/common/home/u0123456/basinwx_output/forecasts',
    'log_dir': '/uufs/chpc.utah.edu/common/home/u0123456/logs/gefs',

    # BasinWx locations
    'locations': {
        'vernal': (40.4555, -109.5287),
        'roosevelt': (40.2994, -110.0062),
        'rangely': (40.0875, -108.8048),
        'uinta_basin_rep': (40.5, -110.0)  # Representative point
    },

    # Forecast settings
    'forecast_hours': list(range(0, 384, 6)),  # 15 days for clyfar
    'subset_bbox': (39.0, 41.5, -111.5, -108.0),  # Uinta Basin + buffer

    # Operational settings
    'overwrite': False,  # Don't re-download existing data
    'save_format': 'zarr',
    'cleanup_old_data': True,
    'keep_last_n_cycles': 4  # Keep 1 day of data
}


def setup_logging(log_dir: str) -> logging.Logger:
    """Setup logging for operational run."""
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.datetime.utcnow().strftime('%Y%m%d_%H%M')
    log_file = log_dir / f"gefs_operational_{timestamp}.log"

    # Console and file logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )

    logger = logging.getLogger('gefs_operational')
    logger.info(f"Log file: {log_file}")

    return logger


def download_data(config: dict, logger: logging.Logger) -> Path:
    """Download latest GEFS data."""
    logger.info("=" * 60)
    logger.info("DOWNLOADING GEFS DATA")
    logger.info("=" * 60)

    init_time = get_latest_gefs_init()
    logger.info(f"Latest GEFS init: {init_time}")

    try:
        zarr_path = download_latest_gefs_for_clyfar(
            save_dir=config['data_dir'],
            save_format=config['save_format'],
            overwrite=config['overwrite'],
            subset_bbox=config['subset_bbox'],
            forecast_hours=config['forecast_hours']
        )
        logger.info(f"✓ Download complete: {zarr_path}")
        return zarr_path

    except Exception as e:
        logger.error(f"✗ Download failed: {e}")
        raise


def process_ensemble(zarr_path: Path, logger: logging.Logger) -> Ensemble:
    """Load data into Ensemble class."""
    logger.info("=" * 60)
    logger.info("LOADING ENSEMBLE")
    logger.info("=" * 60)

    try:
        ens = Ensemble.from_zarr(zarr_path)
        logger.info(f"✓ Ensemble loaded:")
        logger.info(ens)
        return ens

    except Exception as e:
        logger.error(f"✗ Ensemble load failed: {e}")
        raise


def export_forecasts(ens: Ensemble, config: dict, logger: logging.Logger) -> list:
    """Export JSON forecasts for all locations."""
    logger.info("=" * 60)
    logger.info("EXPORTING FORECASTS")
    logger.info("=" * 60)

    output_files = []

    for loc_name, (lat, lon) in config['locations'].items():
        logger.info(f"Processing {loc_name}: ({lat}, {lon})")

        try:
            # Create meteogram JSON
            json_data = create_meteogram_json(
                ensemble=ens,
                location=(lat, lon),
                location_name=loc_name.replace('_', ' ').title()
            )

            # Save
            json_path = save_json_with_timestamp(
                json_data,
                output_dir=config['json_output_dir'],
                prefix=f"gefs_{loc_name}"
            )

            logger.info(f"  ✓ Saved: {json_path}")
            output_files.append(json_path)

        except Exception as e:
            logger.error(f"  ✗ Failed to export {loc_name}: {e}")
            continue

    logger.info(f"✓ Exported {len(output_files)} JSON files")
    return output_files


def cleanup_old_data(config: dict, logger: logging.Logger):
    """Remove old GEFS data to save disk space."""
    if not config['cleanup_old_data']:
        return

    logger.info("=" * 60)
    logger.info("CLEANING UP OLD DATA")
    logger.info("=" * 60)

    data_dir = Path(config['data_dir'])

    # Find GEFS files
    if config['save_format'] == 'zarr':
        pattern = 'gefs_*.zarr'
    else:
        pattern = 'gefs_*.nc'

    gefs_files = sorted(data_dir.glob(pattern))

    if len(gefs_files) <= config['keep_last_n_cycles']:
        logger.info(f"Only {len(gefs_files)} files found, nothing to clean")
        return

    # Remove old files
    files_to_remove = gefs_files[:-config['keep_last_n_cycles']]
    for fpath in files_to_remove:
        try:
            if fpath.is_dir():
                import shutil
                shutil.rmtree(fpath)
            else:
                fpath.unlink()
            logger.info(f"  Removed: {fpath.name}")
        except Exception as e:
            logger.warning(f"  Failed to remove {fpath}: {e}")

    logger.info(f"✓ Cleaned up {len(files_to_remove)} old files")


def send_to_basinwx(json_files: list, config: dict, logger: logging.Logger):
    """Send JSON files to BasinWx server (placeholder).

    TODO: Implement actual upload to BasinWx API
    """
    logger.info("=" * 60)
    logger.info("SENDING TO BASINWX")
    logger.info("=" * 60)

    # Placeholder - implement based on your server setup
    # Options:
    #   1. scp/rsync to web server
    #   2. POST to API endpoint
    #   3. Write to shared filesystem

    logger.info("TODO: Implement BasinWx upload")
    logger.info(f"Files ready for upload: {len(json_files)}")
    for fpath in json_files:
        logger.info(f"  {fpath}")


def write_status_file(config: dict, success: bool, message: str):
    """Write status file for monitoring."""
    status_file = Path(config['log_dir']) / 'last_run_status.json'

    status = {
        'timestamp': datetime.datetime.utcnow().isoformat() + 'Z',
        'success': success,
        'message': message,
        'init_time': get_latest_gefs_init().isoformat() + 'Z'
    }

    with open(status_file, 'w') as f:
        json.dump(status, f, indent=2)


def main():
    """Main operational routine."""
    # Setup
    logger = setup_logging(CONFIG['log_dir'])
    logger.info("GEFS OPERATIONAL RUN STARTING")
    logger.info(f"Timestamp: {datetime.datetime.utcnow()} UTC")

    try:
        # 1. Download
        zarr_path = download_data(CONFIG, logger)

        # 2. Process
        ens = process_ensemble(zarr_path, logger)

        # 3. Export
        json_files = export_forecasts(ens, CONFIG, logger)

        # 4. Send to BasinWx
        send_to_basinwx(json_files, CONFIG, logger)

        # 5. Cleanup
        cleanup_old_data(CONFIG, logger)

        # Success
        logger.info("=" * 60)
        logger.info("✓ OPERATIONAL RUN COMPLETE")
        logger.info("=" * 60)

        write_status_file(CONFIG, success=True, message="Run completed successfully")

        return 0

    except Exception as e:
        logger.error("=" * 60)
        logger.error("✗ OPERATIONAL RUN FAILED")
        logger.error("=" * 60)
        logger.error(str(e))
        logger.error(traceback.format_exc())

        write_status_file(CONFIG, success=False, message=str(e))

        return 1


if __name__ == '__main__':
    sys.exit(main())

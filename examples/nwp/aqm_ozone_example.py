#!/usr/bin/env python
"""
AQM Ozone Data Example
======================

This example demonstrates how to access and analyze AQM ozone forecast data
using the BRC Tools package.

Example output:
- Downloads 8-hour average ozone forecast
- Creates Utah-focused subset
- Generates basic statistics and plots

Author: BRC Tools Team
Date: 2025-01-19
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

try:
    import matplotlib.pyplot as plt
    import numpy as np
    HAS_PLOTTING = True
except ImportError:
    print("Warning: matplotlib not available, skipping plots")
    HAS_PLOTTING = False

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from brc_tools.models import AQMData
from brc_tools.core.logging import setup_logging
from brc_tools.core.exceptions import DataError


def main():
    """Main example function."""
    
    # Setup logging
    setup_logging()
    
    print("=" * 60)
    print("BRC Tools - AQM Ozone Example")
    print("=" * 60)
    
    # Configure forecast parameters
    init_time = datetime.now() - timedelta(hours=6)  # Use recent forecast
    forecast_hour = 14  # 14-hour forecast
    product = "ave_8hr_o3"  # 8-hour average ozone
    
    print(f"Forecast configuration:")
    print(f"  Init time: {init_time}")
    print(f"  Forecast hour: {forecast_hour}")
    print(f"  Product: {product}")
    print()
    
    try:
        # Initialize AQM data interface
        print("Initializing AQM data interface...")
        aqm = AQMData(
            init_time=init_time,
            forecast_hour=forecast_hour,
            product=product,
            domain="CS"  # CONUS domain
        )
        
        # Check available data
        print("Checking available data...")
        available_vars = aqm.available_variables()
        available_forecasts = aqm.get_available_forecasts()
        
        print(f"Available variables: {available_vars[:5]}...")  # Show first 5
        print(f"Available forecasts: {available_forecasts[:3]}...")  # Show first 3
        print()
        
        # Get ozone data
        print("Downloading ozone data...")
        ozone_data = aqm.get_variable("ozone_concentration")
        
        print(f"Data shape: {dict(ozone_data.dims)}")
        print(f"Valid time: {aqm.valid_time()}")
        print()
        
        # Basic statistics
        ozone_values = ozone_data["ozone_concentration"]
        print("Ozone statistics (ppb):")
        print(f"  Min: {float(ozone_values.min()):.1f}")
        print(f"  Max: {float(ozone_values.max()):.1f}")
        print(f"  Mean: {float(ozone_values.mean()):.1f}")
        print(f"  Std: {float(ozone_values.std()):.1f}")
        print()
        
        # Get Utah subset
        print("Creating Utah subset...")
        utah_ozone = aqm.get_utah_subset("ozone_concentration")
        
        utah_values = utah_ozone["ozone_concentration"]
        print("Utah ozone statistics (ppb):")
        print(f"  Min: {float(utah_values.min()):.1f}")
        print(f"  Max: {float(utah_values.max()):.1f}")
        print(f"  Mean: {float(utah_values.mean()):.1f}")
        print()
        
        # Air quality assessment
        assess_air_quality(utah_values)
        
        # Create plots if matplotlib available
        if HAS_PLOTTING:
            create_plots(utah_ozone, aqm, init_time, forecast_hour)
        
        # Display metadata
        print("Model metadata:")
        metadata = aqm.get_metadata()
        for key, value in metadata.items():
            if key not in ["available_variables", "available_forecasts"]:
                print(f"  {key}: {value}")
        
        print("\nExample completed successfully!")
        
    except DataError as e:
        print(f"Data access error: {e}")
        print("This might be due to:")
        print("  - Forecast not yet available")
        print("  - Network connectivity issues")
        print("  - Try a different init_time or forecast_hour")
        
    except Exception as e:
        print(f"Unexpected error: {e}")
        print("Check that all dependencies are installed")


def assess_air_quality(ozone_values):
    """Assess air quality based on ozone concentrations."""
    
    # EPA ozone standards (8-hour average)
    thresholds = {
        "good": 54,           # 0-54 ppb
        "moderate": 70,       # 55-70 ppb  
        "unhealthy_sensitive": 85,  # 71-85 ppb
        "unhealthy": 105,     # 86-105 ppb
        "very_unhealthy": 200  # 106-200 ppb
    }
    
    print("Air Quality Assessment (EPA 8-hour ozone standards):")
    
    total_points = ozone_values.size
    
    good = (ozone_values <= thresholds["good"]).sum()
    moderate = ((ozone_values > thresholds["good"]) & 
                (ozone_values <= thresholds["moderate"])).sum()
    unhealthy_sensitive = ((ozone_values > thresholds["moderate"]) & 
                          (ozone_values <= thresholds["unhealthy_sensitive"])).sum()
    unhealthy = ((ozone_values > thresholds["unhealthy_sensitive"]) & 
                (ozone_values <= thresholds["unhealthy"])).sum()
    very_unhealthy = (ozone_values > thresholds["unhealthy"]).sum()
    
    print(f"  Good (≤{thresholds['good']} ppb): {int(good)} ({100*good/total_points:.1f}%)")
    print(f"  Moderate ({thresholds['good']+1}-{thresholds['moderate']} ppb): {int(moderate)} ({100*moderate/total_points:.1f}%)")
    print(f"  Unhealthy for Sensitive ({thresholds['moderate']+1}-{thresholds['unhealthy_sensitive']} ppb): {int(unhealthy_sensitive)} ({100*unhealthy_sensitive/total_points:.1f}%)")
    print(f"  Unhealthy ({thresholds['unhealthy_sensitive']+1}-{thresholds['unhealthy']} ppb): {int(unhealthy)} ({100*unhealthy/total_points:.1f}%)")
    print(f"  Very Unhealthy (>{thresholds['unhealthy']} ppb): {int(very_unhealthy)} ({100*very_unhealthy/total_points:.1f}%)")
    print()


def create_plots(utah_ozone, aqm, init_time, forecast_hour):
    """Create visualization plots."""
    
    print("Creating plots...")
    
    try:
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
        
        # Plot 1: Spatial map
        ozone_values = utah_ozone["ozone_concentration"]
        
        im1 = ax1.imshow(
            ozone_values,
            cmap='RdYlBu_r',
            vmin=0,
            vmax=100,
            aspect='auto'
        )
        ax1.set_title(f'Utah Ozone Forecast\n{aqm.valid_time().strftime("%Y-%m-%d %H:%M")} UTC')
        ax1.set_xlabel('Longitude Index')
        ax1.set_ylabel('Latitude Index')
        
        # Add colorbar
        cbar1 = plt.colorbar(im1, ax=ax1)
        cbar1.set_label('Ozone (ppb)')
        
        # Plot 2: Histogram
        ax2.hist(ozone_values.values.flatten(), bins=30, alpha=0.7, edgecolor='black')
        ax2.set_xlabel('Ozone Concentration (ppb)')
        ax2.set_ylabel('Frequency')
        ax2.set_title('Utah Ozone Distribution')
        ax2.grid(True, alpha=0.3)
        
        # Add EPA threshold lines
        thresholds = [54, 70, 85, 105]
        colors = ['green', 'yellow', 'orange', 'red']
        labels = ['Good', 'Moderate', 'Unhealthy Sensitive', 'Unhealthy']
        
        for threshold, color, label in zip(thresholds, colors, labels):
            ax2.axvline(threshold, color=color, linestyle='--', alpha=0.7, label=f'{label} ({threshold} ppb)')
        
        ax2.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
        
        plt.tight_layout()
        
        # Save plot
        output_file = f"utah_ozone_{init_time.strftime('%Y%m%d_%H')}Z_f{forecast_hour:02d}.png"
        plt.savefig(output_file, dpi=150, bbox_inches='tight')
        print(f"Plot saved as: {output_file}")
        
        # Show plot
        plt.show()
        
    except Exception as e:
        print(f"Error creating plots: {e}")


if __name__ == "__main__":
    main()
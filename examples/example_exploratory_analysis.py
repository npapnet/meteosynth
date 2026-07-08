"""
Example: Exploratory Analysis of Meteorological Data

This script demonstrates how to fetch weather data from PVGIS, process it using
the `MetDataProcessor` from `meteosynth`, and visualize it using the plotting
functions in `sup_plot_lib`.
"""

import os
import pathlib
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pvlib.iotools import get_pvgis_hourly

# Import from our package (assuming installed in editable/dev mode)
from meteosynth.met_data_processor import MetDataProcessor
import meteosynth.sup_plot_lib as spl

# Setup directories
DATA_DIR = pathlib.Path("./data")
DATA_DIR.mkdir(exist_ok=True)
XLSX_FNAME = DATA_DIR / "pvgis_hourly_data.xlsx"

def load_or_fetch_data() -> pd.DataFrame:
    """Load PVGIS hourly data from cache, or download it if missing."""
    if XLSX_FNAME.exists():
        print(f"Loading cached weather data from {XLSX_FNAME}...")
        return pd.read_excel(XLSX_FNAME)
        
    print("No cached data found. Fetching hourly data from PVGIS for Paris (48.8566, 2.3522)...")
    latitude = 48.8566
    longitude = 2.3522
    start_year = 2011
    end_year = 2012 # Fetching 2 years for demonstration speed

    data, inputs = get_pvgis_hourly(
        latitude=latitude, 
        longitude=longitude, 
        start=start_year, 
        end=end_year,
        usehorizon=True, 
        outputformat="json", 
        components=True
    )
    
    # Process index to create year, month, day, hour columns
    data['year'] = data.index.year
    data['month'] = data.index.month
    data['day'] = data.index.day
    data['hour'] = data.index.hour 
    
    # Cache data to Excel
    data.to_excel(XLSX_FNAME, index=False)
    print(f"Data saved to {XLSX_FNAME}")
    return data

def main():
    # 1. Load Data
    df = load_or_fetch_data()
    print("Preview of PVGIS weather data:")
    print(df.head())

    # 2. Initialize MetDataProcessor
    mdp = MetDataProcessor(df)
    print("\nData time range description:")
    print(mdp.describe_time_range())

    # 3. Get subset of data for May (Month = 5)
    month_ind = 5
    month_data = mdp.get_month_subset(month_ind)
    print(f"\nSubset for May contains {len(month_data)} hourly records.")

    # 4. Generate daily wide format (days as rows, hours 0-23 as columns)
    wide_df = mdp.get_monthly_attribute_wide_format(value_col='poa_direct', month_id=month_ind)
    print("\nMay 'poa_direct' daily wide format preview:")
    print(wide_df.head())

    # 5. Visualizations using sup_plot_lib
    print("\nGenerating exploratory plots...")
    
    # 2D KDE contour plot using Seaborn
    print("- Creating 2D KDE Plot...")
    spl.plot_2d_kde_sns(month_data, value_str='poa_direct', ylabel='Plane of Array Direct Irradiance (W/m^2)')
    
    # Hourly Boxplot with Scatter Points overlay
    print("- Creating Whisker-Point Plot...")
    spl.plot_whisker_point_sns(month_data, value_str='poa_direct', ylabel='Plane of Array Direct Irradiance (W/m^2)')
    
    # Hourly Mean with standard deviation error bars using Matplotlib
    print("- Creating Error Bar Plot...")
    spl.plot_hourly_mean_with_error_bars_plt(met_data=month_data, value_str='poa_direct', k=1.0, show_points=False)
    
    # Plotnine monthly line plot faceted by year
    print("- Creating plotnine faceted line plot...")
    p = spl.p9_month_by_year(mdp, month_ind=month_ind, value_col='poa_direct')
    print(p)

    print("\nAnalysis complete.")

if __name__ == "__main__":
    main()

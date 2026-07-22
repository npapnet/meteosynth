#%%
"""
Example: Synthetic Series Generation using Markov Chains

This script demonstrates how to construct a daily weather generator
(EnvSeriesGenerator) using the 2D KDE Markov Chain Simulator and generate
synthetic hourly sequences of solar radiation (poa_direct) based on historical TMY/hourly data.
"""

import os
import pathlib
import logging
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pvlib.iotools import get_pvgis_hourly

# Import from our package (assuming installed in editable/dev mode)
from meteosynth.met_data_processor import MetDataProcessor
from meteosynth.generators import EnvSeriesGenerator

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Setup directories
DATA_DIR = pathlib.Path("./data")
DATA_DIR.mkdir(exist_ok=True)
XLSX_FNAME = DATA_DIR / "pvgis_hourly_data.xlsx"

def load_or_fetch_data() -> pd.DataFrame:
    """Load cached PVGIS hourly data or download it."""
    if XLSX_FNAME.exists():
        logging.info(f"Loading cached weather data from {XLSX_FNAME}...")
        return pd.read_excel(XLSX_FNAME)
        
    logging.info("No cached data found. Fetching hourly data from PVGIS for Paris (48.8566, 2.3522)...")
    latitude = 48.8566
    longitude = 2.3522
    start_year = 2011
    end_year = 2012

    data, inputs = get_pvgis_hourly(
        latitude=latitude, 
        longitude=longitude, 
        start=start_year, 
        end=end_year,
        usehorizon=True, 
        outputformat="json", 
        components=True
    )
    
    # Process index
    data['year'] = data.index.year
    data['month'] = data.index.month
    data['day'] = data.index.day
    data['hour'] = data.index.hour 
    
    # Cache data
    data.to_excel(XLSX_FNAME, index=False)
    logging.info(f"Data saved to {XLSX_FNAME}")
    return data

def main():
    # 1. Load weather data
    df = load_or_fetch_data()
    mdp = MetDataProcessor(df)

    # 2. Get subset for May (Month = 5) to train our generators
    may_data = mdp.get_month_subset(5)
    
    # 3. Create the daily series generator for Plane of Array Direct Irradiance (poa_direct)
    generator = EnvSeriesGenerator(may_data, attr_str='poa_direct')

    # 4. Generate 10 synthetic daily profiles
    print("\nGenerating 10 synthetic daily profiles for Plane of Array Direct Irradiance...")
    # Hour 0 is drawn from the fitted initial distribution pi(x0). For poa_direct every
    # observed midnight is zero, so pi(x0) is a spike at zero and each day starts at 0.0
    # -- read off the data rather than hard-coded as a default argument.
    rng = np.random.default_rng(42)
    synthetic_profiles = [generator.gen_day(rng=rng) for _ in range(10)]

    # 5. Plot the generated profiles
    plt.figure(figsize=(10, 6))
    for i, profile in enumerate(synthetic_profiles):
        plt.plot(profile, alpha=0.6, label=f"Synthetic Day {i+1}" if i < 3 else "")
        
    plt.title("Synthetic 24-hour Irradiance Profiles (poa_direct)")
    plt.xlabel("Hour of Day")
    plt.ylabel("Irradiance (W/m^2)")
    plt.grid(True, linestyle="--", alpha=0.5)
    plt.legend()
    plt.tight_layout()
    plt.show()

    print("Synthetic generation complete.")

if __name__ == "__main__":
    main()

# %%

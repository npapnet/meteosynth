#%%
"""
Example: Synthetic Series Generation using Markov Chains

This script demonstrates how to construct a daily weather generator
(EnvSeriesGenerator) using the 2D KDE Markov Chain Simulator and generate
synthetic hourly sequences of solar radiation (poa_direct) based on historical TMY/hourly data.
"""

import logging
import pathlib
import sys

import numpy as np
import matplotlib.pyplot as plt

# Make `examples/` importable however this file is run (script, -m, or an editor cell).
_HERE = pathlib.Path(__file__).resolve().parent if "__file__" in globals() else pathlib.Path.cwd()
_EXAMPLES = next(p for c in (_HERE, *_HERE.parents) for p in (c, c / "examples")
                 if (p / "tools" / "site_data.py").is_file())
sys.path.insert(0, str(_EXAMPLES))

# Import from our package (assuming installed in editable/dev mode)
from meteosynth.met_data_processor import MetDataProcessor
from meteosynth.generators import EnvSeriesGenerator
from tools.site_data import load_paris_demo

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

def main():
    # 1. Load weather data (Paris 2011-2012, cached under examples/data/)
    df = load_paris_demo()
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

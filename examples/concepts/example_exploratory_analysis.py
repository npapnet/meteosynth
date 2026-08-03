#%%
"""
Example: Exploratory Analysis of Meteorological Data

This script demonstrates how to fetch weather data from PVGIS, process it using
the `MetDataset` from `meteosynth`, and visualize it using the plotting
functions in `sup_plot_lib`.
"""

import sys

import matplotlib.pyplot as plt

from meteosynth import workspace

#: This script's own folder. `data/` and `output/` sit beside it, wherever the script
#: is launched from -- so the example is self-contained and can be copied anywhere.
#: `globals().get` rather than `__file__` because this also runs as `#%%` cells, where
#: there is no file and the working directory is the honest answer.
WS = workspace(globals().get("__file__"))
# Make `examples/` importable however this file is run (script, -m, or an editor cell).
_EXAMPLES = next(p for c in (WS.root, *WS.root.parents) for p in (c, c / "examples")
                 if (p / "tools" / "site_data.py").is_file())
sys.path.insert(0, str(_EXAMPLES))

# Import from our package (assuming installed in editable/dev mode)
from meteosynth.dataset import MetDataset
import meteosynth.sup_plot_lib as spl
from tools.site_data import load_paris_demo
#%%

def main():
    # 1. Load Data (Paris 2011-2012, collected into data/ beside this file). It returns a
    #    validated MetDataset, so there is nothing left to construct.
    ds = load_paris_demo(WS)
    print("Preview of PVGIS weather data:")
    print(ds.met_data.head())
    print(f"Provenance: {ds.provenance.source}, site={ds.provenance.site}")

    print("\nData time range description:")
    print(ds.describe_time_range())

    # 3. Get subset of data for May (Month = 5)
    month_ind = 5
    month_data = ds.get_month_subset(month_ind)
    print(f"\nSubset for May contains {len(month_data)} hourly records.")

    # 4. Generate daily wide format (days as rows, hours 0-23 as columns)
    wide_df = ds.get_monthly_attribute_wide_format(value_col='poa_direct', month_id=month_ind)
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
    
    # Faceted monthly line plot by year using Seaborn
    print("- Creating Seaborn faceted line plot...")
    g = spl.plot_month_by_year_sns(ds, month_ind=month_ind, value_col='poa_direct')
    plt.show()

    print("\nAnalysis complete.")

if __name__ == "__main__":
    main()

# %%

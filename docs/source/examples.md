# Examples

Two runnable scripts live under `examples/`. Both fetch data from PVGIS on
first run and cache it to `data/pvgis_hourly_data.xlsx`, so subsequent runs are
offline and fast.

```bash
uv run python examples/example_exploratory_analysis.py
uv run python examples/example_markov_generation.py
```

## 1. Exploratory analysis

`examples/example_exploratory_analysis.py` shows the data-preparation and
visualisation side: fetch hourly data, wrap it in `MetDataProcessor`, subset a
month, reshape to daily-wide format, and produce diagnostic plots via
`sup_plot_lib` (2D KDE contours, hourly boxplots, mean ± error bars, and a
Seaborn faceted line plot).

```python
from meteosynth import MetDataProcessor
import meteosynth.sup_plot_lib as spl

mdp = MetDataProcessor(df)
month_data = mdp.get_month_subset(5)              # May
wide = mdp.get_monthly_attribute_wide_format(     # days x hours
    value_col="poa_direct", month_id=5)

spl.plot_2d_kde_sns(month_data, value_str="poa_direct")
```

## 2. Synthetic generation

`examples/example_markov_generation.py` builds an `EnvSeriesGenerator` for
plane-of-array direct irradiance and plots several synthetic daily profiles.

```{mermaid}
flowchart LR
    L["load_or_fetch_data()"] --> M["MetDataProcessor"]
    M --> May["get_month_subset(5)"]
    May --> G["EnvSeriesGenerator(attr_str='poa_direct')"]
    G --> P["gen_day_sequence() &times; 10"]
    P --> Plot["plot 24-hour profiles"]
```

```python
from meteosynth import MetDataProcessor, EnvSeriesGenerator

mdp = MetDataProcessor(df)
may = mdp.get_month_subset(5)

generator = EnvSeriesGenerator(may, attr_str="poa_direct")
profiles = [generator.gen_day_sequence(start_value=0.0) for _ in range(10)]
```

## 3. A Monte-Carlo sketch for energy output

Putting it together for the target use case — turning synthetic irradiance days
into a distribution of daily energy yield:

```python
import numpy as np
from meteosynth import MetDataProcessor, EnvSeriesGenerator

mdp = MetDataProcessor(df)
june = mdp.get_month_subset(6)

gen = EnvSeriesGenerator(june, attr_str="poa_direct", bandwidth=0.1)

# 1000 synthetic June days -> (1000, 24) array of hourly irradiance
ensemble = gen.generate_ensemble(n_days=1000, start_value=0.0, seed=42)

# Convert to a simple daily-energy proxy (W/m2 summed over hours -> Wh/m2)
module_area_m2 = 1.6
module_eff = 0.20
daily_wh = ensemble.sum(axis=1) * module_area_m2 * module_eff

print(f"P50 daily yield : {np.percentile(daily_wh, 50):8.1f} Wh")
print(f"P90 daily yield : {np.percentile(daily_wh, 90):8.1f} Wh")
print(f"P10 daily yield : {np.percentile(daily_wh, 10):8.1f} Wh")
```

The percentile spread across the ensemble is exactly the quantity an energy
Monte-Carlo consumes: a distribution of outcomes rather than a single number.

## Interactive use

Every snippet above runs cleanly in a Jupyter notebook or a VS Code interactive
window (the dev environment ships Jupyter, `notebook` and `ipykernel`). Because
each simulator exposes plotting helpers (`plot_joint_distribution`,
`plot_conditional_densities`, `plot_transition_slice`), it is convenient to
explore the fitted densities cell-by-cell.
```

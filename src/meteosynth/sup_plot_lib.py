import pandas as pd

import plotnine as p9
import seaborn as sns
import matplotlib.pyplot as plt
from mpl_toolkits.axes_grid1 import make_axes_locatable
from scipy.interpolate import make_interp_spline, BSpline

from .met_data_processor import MetDataProcessor

_f_month_name = lambda x: pd.to_datetime(f'2023-{x}-01').strftime('%B')

def p9_month_by_year(mdp:MetDataProcessor, month_ind:int=5, value_col:str='poa_direct'):
    """
    Create a plot of the monthly data for each year.
    
    Parameters:
    - month_data: DataFrame containing the data to plot.
    - month_ind: Month index (1-12) to filter the data.
    - value_col: Column name for the value to plot.
    
    Returns:
    - Plot object.
    """
    # Filter the data for the specified month
    month_data = mdp.get_month_subset(month_ind)
    # month_data["date_id"] = month_data["year"].astype(str) + "-" + month_data["month"].astype(str) + "-" + month_data["day"].astype(str)    
    
    # Create the plot
    p = (p9.ggplot(month_data) 
         + p9.aes(x='hour', y=value_col, group='date_id', color='factor(year)') 
         + p9.geom_line(alpha=0.2)
         + p9.facet_grid('year ~ month',  scales='free_y')
         + p9.theme(figure_size=(6, 20))
         + p9.labs(title=f"PVGIS Hourly Data for {_f_month_name(month_ind)}", x="Hour of Day", y=value_col)
        )
    
    return p


def plot_2d_kde_sns(month_data, value_str:str='poa_direct', 
                ylabel = 'Plane of Array Direct Irradiance (W/m^2)',
                figsize=(10, 6), contour_levels=5):
    """
    Create a 2D KDE plot with filled contours and contour lines using seaborn.
    
    Parameters:
    - month_data: DataFrame containing the data to plot.
    - figsize: Tuple specifying the figure size.
    - contour_levels: Number of contour levels to display.
    """
    plt.figure(figsize=figsize)  # Set the figure size

    # Plot the filled contours
    sns.kdeplot(data=month_data, x='hour', y=value_str, levels=contour_levels, fill=True, alpha=0.7, cmap='viridis')

    # Plot the contour lines on top
    sns.kdeplot(data=month_data, x='hour', y=value_str, levels=contour_levels, color='black', linewidth=0.8)  # Add color and linewidth for lines

    # Add titles and labels using matplotlib
    plt.title("PVGIS Hour Data for February")
    plt.xlabel("Hour of Day")
    plt.ylabel(ylabel)

    # Show the plot
    plt.show()



def plot_whisker_point_sns(month_data, value_str:str='poa_direct', ylabel = 'Plane of Array Direct Irradiance (W/m^2)'):
    """
    Create a boxplot with scatter points overlayed using seaborn. 
    """
    # whisker plot of the data for each hour of the day

    # Ensure 'hour' is treated as a category for seaborn
    month_data['hour_cat'] = month_data['hour'].astype('category')
    month_indx = month_data['month'].unique()[0] # get the month index from the data

    # Create the plot using seaborn
    plt.figure(figsize=(12, 6)) # Optional: set the figure size

    # Create the boxplot
    sns.boxplot(data=month_data, x='hour_cat', y=value_str, color='lightblue')

    # Overlay the scatter points (jittered to avoid overplotting)
    sns.stripplot(data=month_data, x='hour_cat', y=value_str, color='red', alpha=0.5, jitter=True)

    # Add titles and labels
    plt.title(f"PVGIS Hourly Data for {_f_month_name(month_indx)}")
    plt.xlabel("Hour of Day")
    plt.ylabel(ylabel)

    # Ensure all hour categories are shown on the x-axis if there are gaps
    plt.xticks(rotation=0) # Rotate labels if they overlap

    plt.tight_layout() # Adjust layout to prevent labels overlapping
    plt.show()


def plot_hourly_mean_with_error_bars_plt(met_data, value_str:str='poa_direct', 
                                         k = 1.0, show_points:bool=True):
    """
    Create a plot of the hourly mean and standard error for 'poa_direct' with error bars.
    """
    # --- Configuration ---
     # Factor to multiply the standard error by (e.g., 1.0 for 1 SE, 2.0 for 2 SE)
    # ---------------------

    # Calculate mean and standard error for 'poa_direct' for each hour
    hourly_stats = met_data.groupby('hour')[value_str].agg(['mean', 'std']).reset_index()

    # Calculate the error bar length (k * SE)
    hourly_stats['yerr'] = hourly_stats['std'] * k

    # Create the plot
    fig, ax = plt.subplots(figsize=(12, 6)) # Create a matplotlib figure and axes

    # Plot the individual scatter points
    if show_points:
        ax.scatter(met_data['hour'], met_data[value_str], color='red', alpha=0.5, label='Individual Data Points')

    # Plot the mean and standard error bars
    # The x values are the hours, y values are the means, and yerr is k * SE
    ax.errorbar(
        hourly_stats['hour'],
        hourly_stats['mean'],
        yerr=hourly_stats['yerr'],
        fmt='o',           # Format of the mean marker ('o' for circles)
        color='blue',
        capsize=5,         # Size of the caps on the error bars
        label=rf'Mean $\pm$ {k} SE' # Label for the legend
    )

    # Add titles and labels
    ax.set_title("PVGIS Hourly Data for February with Mean and Error Bars")
    ax.set_xlabel("Hour of Day")
    ax.set_ylabel("Plane of Array Direct Irradiance (W/m^2)")

    # Ensure x-axis ticks are at integer hours
    ax.set_xticks(hourly_stats['hour'])

    # Add a legend to distinguish the points and error bars
    ax.legend()

    plt.grid(axis='y', linestyle='--', alpha=0.7) # Optional: add a grid for easier reading
    plt.tight_layout() # Adjust layout
    plt.show()

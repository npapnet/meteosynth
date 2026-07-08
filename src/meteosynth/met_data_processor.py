import numpy as np
import pandas as pd

class MetDataProcessor():
    """
    Class to process meteorological data from PVGIS.
    """
    __met_data_columns =['poa_direct', 'poa_sky_diffuse', 'poa_ground_diffuse',
       'solar_elevation', 'temp_air', 'wind_speed', 'Int', 'year', 'month',
       'day', 'hour']
    def __init__(self, met_data:pd.DataFrame):
        """
        Initialize the MetDataProcessor with meteorological data.

        Parameters:
        met_data (pd.DataFrame): DataFrame containing meteorological data.
        """
        # assert metdata contains all the columns  in self.__met_data_columns
        assert all(col in met_data.columns for col in self.__met_data_columns), "Missing columns in met_data"

        self.met_data = met_data
        
    def get_month_subset(self, month_ind:int):
        """
        Get a subset of the meteorological data for a specific month.

        Parameters:
        month_ind (int): Month index (1-12) to filter the data.

        Returns:
        pd.DataFrame: Subset of the meteorological data for the specified month.
        """
        month_data = self.met_data[self.met_data['month'] == month_ind].copy()
        
        # creating an id column so that I can create a line for each unique date_id
        month_data["date_id"] = month_data["year"].astype(str) + "-" + month_data["month"].astype(str) + "-" + month_data["day"].astype(str)    
        return month_data
    
    def describe_time_range(self):
        """
        Describe the time range of the meteorological data.

        Returns:
        str: Description of the time range.
        """
        start_date = self.met_data['year'].min()
        end_date = self.met_data['year'].max()
        return f"Data ranges from {start_date} to {end_date}"
    
    def get_monthly_attribute_wide_format(self, value_col:str, month_id:int=None):
        """
        Convert the meteorological data to wide format using pivot_table.

        Parameters:
        value_col (str): The column to use as the values.

        Returns:
        pd.DataFrame: The converted met_data DataFrame in wide format.
        """
        
        if month_id is None:   
            temp_df = self.met_data.copy()
        else:
            temp_df = self.get_month_subset(month_ind=month_id)

        return convert_to_daily_wide(temp_df, value_col=value_col)


def convert_to_daily_wide(met_data:pd.DataFrame, value_col:str):
    """
    Convert a DataFrame to wide format using pivot_table.
    
    Parameters:
    met_data (pd.DataFrame): The DataFrame to convert.
    value_col (str): The column to use as the values.
    
    Returns:
    pd.DataFrame: The converted met_data DataFrame in wide format.
    """
    
    tmp_df = met_data.loc[:,[value_col, 'year', 'month',
                    'day', 'hour']]
    # convert datetime to string format YYYYMMDD
    tmp_df['date_str'] = pd.to_datetime(tmp_df[['year', 'month', 'day']]).dt.strftime('%Y%m%d')
    
    # Pivot the data to get hours as columns
    pivot_df = tmp_df.pivot(index=['date_str'], 
                            columns='hour', 
                            values=value_col)
    return pivot_df
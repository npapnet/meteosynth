import numpy as np
import pandas as pd

from .day_window import circular_delta, day_slot, day_slots

class MetDataProcessor():
    """
    Class to process meteorological data from PVGIS.
    
    TODO: consider exposing the _met_data_columns to the package for
    maximum transparency for the user (frozen/immutable) 
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
        self.__slots_cache = None

    def get_month_subset(self, month_ind:int):
        """
        Get a subset of the meteorological data for a specific month.

        Parameters:
        month_ind (int): Month index (1-12) to filter the data.

        Returns:
        pd.DataFrame: Subset of the meteorological data for the specified month.
        """
        month_data = self.met_data[self.met_data['month'] == month_ind].copy()

        return _add_date_id(month_data)

    def get_day_window_subset(self, month:int, day:int, n_days:int=15):
        """
        Get a rolling window of the meteorological data centred on a calendar day.

        Selects every record lying within ``n_days`` of ``(month, day)`` on the
        ``all_leap`` calendar, pooled across all years in the dataset. This is the
        seasonal counterpart to :meth:`get_month_subset`: where a month subset is
        centred on the middle of the month (so a May 1 model trains on data centred on
        May 16) and jumps discontinuously at month boundaries, a window is centred on
        the target day and slides smoothly from one day to the next.

        The window wraps across New Year, so a Jan 2 target reaches back into December
        and a Dec 30 target reaches forward into January. Feb 29 needs no special
        handling: it is an ordinary slot, so it is pooled into any nearby window and can
        also be requested as the target.

        Note this is a *climatological* window, not a chronological one -- a Jan 2 2011
        target pools December 2011 as a proxy for "late-December climate".

        Parameters
        ----------
        month : int
            Month of the target day (1-12).
        day : int
            Day of the target month.
        n_days : int, optional
            Half-width of the window in days. Defaults to 15, giving a 31-day window
            (~62 days pooled over 2 years, matching a month subset's sample size).
            ``n_days=0`` selects the target day alone; any ``n_days >= 183`` selects
            the whole year.

        Returns
        -------
        pd.DataFrame
            Subset of the meteorological data for the window, with the same ``date_id``
            column that :meth:`get_month_subset` adds, plus the ``day_slot`` of each
            record.

        Raises
        ------
        ValueError
            If ``(month, day)`` is not a valid date, or ``n_days`` is negative.
        """
        n_days = int(n_days)
        if n_days < 0:
            raise ValueError(f"n_days must be non-negative, got {n_days}")

        center = day_slot(month, day)
        slots = self._day_slots()

        mask = circular_delta(slots, center) <= n_days
        window_data = self.met_data[mask].copy()
        window_data["day_slot"] = slots[mask]

        return _add_date_id(window_data)

    def _day_slots(self):
        """The all_leap calendar slot of every record, computed once and reused.

        The source data does not change over a processor's lifetime, so caching this
        keeps a 366-day calendar walk from re-mapping all rows on every window.
        """
        if self.__slots_cache is None:
            self.__slots_cache = day_slots(self.met_data['month'].values,
                                           self.met_data['day'].values)
        return self.__slots_cache

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


def _add_date_id(subset:pd.DataFrame):
    """
    Add the ``date_id`` column identifying each unique date, in place.

    Shared by :meth:`MetDataProcessor.get_month_subset` and
    :meth:`MetDataProcessor.get_day_window_subset` so the two slicing strategies cannot
    drift apart on the format downstream consumers group by.

    Note the id is not zero-padded (``'2011-1-2'``), so it does not sort
    lexicographically -- do not rely on it for ordering. :func:`convert_to_daily_wide`
    builds its own zero-padded ``date_str`` for that reason.

    Parameters:
    subset (pd.DataFrame): Subset to annotate. Mutated and returned.

    Returns:
    pd.DataFrame: The same frame, with a ``date_id`` column.
    """
    subset["date_id"] = subset["year"].astype(str) + "-" + subset["month"].astype(str) + "-" + subset["day"].astype(str)
    return subset


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
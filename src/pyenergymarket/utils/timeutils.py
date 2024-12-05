"""Utilites related to time management should be placed here
"""

import pandas as pd
from typing import Union

def mk_daterange(start:Union[str, pd.Timestamp, None]=None, 
                 end:Union[str, pd.Timestamp,None]=None, min_freq:Union[None,int]=None,
                 periods:Union[None,int] = None) -> pd.DatetimeIndex:
    """Lightweight wrapper around the pandas date_range method that is a bit 
    more geared towards the specific use case.
    Of the 4 inputs, exactly 3 MUST be specified. 
    If all four are specified, periods will be set to None.

    Args:
        start (Union[str, pd.Timestamp, None], optional): start time (inclusive). Defaults to None.
        end (Union[str, pd.Timestamp,None], optional): end time (inclusive). Defaults to None.
        min_freq (int, optional): frequency in minutes (i.e. 60 = 1 hour). Defaults to 60.
        periods (int, optional): number of periods. Defaults to None.

    Returns:
        pd.DatetimeIndex: the datetime index range
    """
    if all([start, end, min_freq, periods]):
        ## if all are not None, convert periods to None
        periods = None
    return pd.date_range(start=start, end=end, freq=f"{min_freq}min", periods=periods)

def count_gen_onoff_periods(lst):
    """Tool to calculate the number of on/off periods
    We need to pull the last (not including lookahead) setpoint data from the mdl_sol timeseries and
    update the current self.mdl with generator values from the solution.
    1. lst contains all the generator set points, not including lookahead window. Lookahead window is currently 
        specified as the model configuration time window -- self.em.configuration['time']['window']
        But this might need to be changed to the model configuration time lookahead -- self.em.configuration['time']['lookahead']
    2. if the lst is empty (if not lst), the unit has been offline -- return 0, to mean that the unit is offline
    3. we want to know *how many periods* the generator has been online (positive) and 
        how many periods the generator has been offline (negative)
    example:
    lst = [0,0,1,1]
    count_gen_onoff_periods(lst) = 2
    lst = [0,1,1,0]
    count_gen_onoff_periods(lst) = -1
    
    Function is used in osw_rt_market.py in CST in function update_model_from_previous.
    
    Parameters
    ----------
    lst : list
        contains all the generator set points, not including lookahead window

    Returns
    -------
    integer
        initial status of the generator 
        -- this is the update to the initial status, taken from the number of most recent
        on/off periods from the model data dictionary in ['elements']['generator'][generatorname]['pg']['values']
        TODO: not clear why I set this up to increment greater than 1 -- I think this is to account for startup times.
    """
    if not lst:
        return 0
    count = 0
    value_type = 0 if lst[-1] == 0.0 else 1  # Check if trailing values are zeros or non-zeros
    for num in reversed(lst):
        if (value_type == 0 and num == 0.0) or (value_type == 1 and num != 0.0):
            count += 1
        else:
            break
    return count if value_type == 1 else -count
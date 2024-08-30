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
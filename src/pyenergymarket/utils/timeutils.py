"""Utilites related to time management should be placed here
"""

import pandas as pd
import numpy as np
from typing import Union

def mk_daterange(start:Union[str, pd.Timestamp, None]=None, 
                 end:Union[str, pd.Timestamp,None]=None, min_freq:Union[None,int]=None,
                 periods:Union[None,int] = None, **kwargs) -> pd.DatetimeIndex:
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
    return pd.date_range(start=start, end=end, freq=f"{min_freq}min", periods=periods, **kwargs)

def count_onoff(gen: dict, t0idx: int, min_freq: int = 60, max_lookback=24) -> Union[float, int]:
    """Function to determine the appropriate initial_status value when moving between
    two instances of a market model.
    Assumptions:
        * The data is (gen) is coming from a solved model that has the commitment key (thermal generators only)
        * The new instance will start at period t0idx + 1


    Args:
        gen (dict): parameter dictionary for a thermal generator (Egret format)
        t0idx (int): time index in the current model, representing t0 for the next one.
        min_freq (int, optional): time period resolution in minutes. Defaults to 60.
        max_lookback (int, optional): maximum of hours to look back before exiting loop. Defaults to 24.
    Returns:
        Union[float,int]: appropriate initial_status flag
    """

    def single_period_onoff(commitment: int, initial_status: Union[float, int], min_freq: int) -> Union[float, int]:
        """Helper function for incrementing count one period at a time

        Args:
            commitment (int): commitment for a given hour
            initial_status (Union[float,int]): accumulated count

        Returns:
            Union[float,int]: accumulated count
        """

        period2hr = min_freq / 60  # note defining here, which
        ### single instance commitment
        if initial_status == 0:
            ### INITIALIZATION only!!!
            return period2hr if commitment > 0 else -1 * period2hr
        elif (initial_status < 0) and (commitment == 0):
            ### another period off-line
            return initial_status - 1 * period2hr
        elif (initial_status < 0) and (commitment > 0):
            ### change of status: turn on
            return 1 * period2hr
        elif (initial_status > 0) and (commitment > 0):
            ### another period on-line
            return initial_status + 1 * period2hr
        elif (initial_status > 0) and (commitment == 0):
            ### change of status: turn off
            return -1 * period2hr
        else:
            ### how did I get here?
            raise ValueError(
                f"count_onoff: unknown combination of initial_status={initial_status} and commitment={commitment}")

    # Load commitment and initial status from the generator dictionary
    commitment = gen.get("commitment", None)
    initial_status = gen["initial_status"]

    if commitment is None:
        raise KeyError("count_onoff: the generator parameter dictionary must contain the 'commitment' key")
    elif isinstance(commitment, float) or isinstance(commitment, int):
        ### update initial status by the single additional commitment period
        return single_period_onoff(commitment, initial_status, min_freq)
    if isinstance(commitment, dict):
        ### time series
        # iterate backwards from t0idx until 0 or change of status
        tmp_initial_status = single_period_onoff(commitment["values"][t0idx], 0, min_freq)
        break_flag = False
        for i in range(t0idx - 1, -1, -1):
            ### iterate backwards from t0
            new_initial_status = single_period_onoff(commitment["values"][i], tmp_initial_status, min_freq)
            if np.sign(tmp_initial_status) == np.sign(new_initial_status):
                ### same direction
                tmp_initial_status = new_initial_status
            else:
                ### change of direction: break
                break_flag = True
                break
            # Check maximum lookback and break (we only care up to initial status < min up/downtime)
            if tmp_initial_status > max_lookback:
                break_flag = True
                break
        if not break_flag:
            ### reached all the way to the beginning of the array, consider appending initial_status
            if np.sign(initial_status) == np.sign(tmp_initial_status):
                ### same direction: append
                return initial_status + tmp_initial_status
            else:
                ### change of direction right at beginning
                return tmp_initial_status
        else:
            ### change of direction was found: return just tmp initial status
            return tmp_initial_status
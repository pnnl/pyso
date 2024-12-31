"""Utilites related to time management should be placed here
"""

import pandas as pd
import numpy as np
from typing import Union

def fill_real_time(da_list:list, min_freq:Union[None,int]=None):
    """
    Takes a list of values from the (hourly) day-ahead market and copies into a longer
    list based on the real-time frequency in minutes. For example, if min_freq=15
    this will copy each hourly values four times.

    Args:
        da_list (list): list of any kind of value from market day-ahead market
        min_freq (Union[None,int]): minimum frequency for copying values.
                                    If None, will return da_list unchanged.
    Returns:
        rt_list (list): list of values copied into the real-time frequency
    """
    # won't change the frequency
    if min_freq is None:
        return da_list
    # Determine the number of times to copy values
    remainder = 60 % min_freq
    if remainder != 0:
        print(f"Warning: min_freq {min_freq} is not a divisor of 60. Results may be inaccurate")
    num_copy = int(60 / min_freq)
    # Use numpy arrays and repeat function for fast copying
    da_array = np.array(da_list)
    rt_array = da_array.repeat(num_copy)
    return list(rt_array)

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

def count_onoff(commitment: list, t0idx: int, min_freq: int = 60,
                initial_status: Union[float, int] = 0) -> Union[float, int]:
    """Function to determine the appropriate initial_status value when moving between
    two instances of a market model.
    Assumptions:
        * The data is (gen) is coming from a solved model that has the commitment key (thermal generators only)
        * The new instance will start at period t0idx + 1


    Args:
        commitment (list): list of commitment values (corresponding timeseries is separate)
        t0idx (int): time index in the current model, representing t0 for the next one.
        min_freq (int, optional): time period resolution in minutes. Defaults to 60.
        initial_status (Union[float, int], optional): the initial status of the generator once list start is reached
    Returns:
        Union[float,int]: appropriate intial_status flag
    """

    def single_period_onoff(commitment: int, initial_status: Union[float, int], min_freq: int) -> Union[float, int]:
        """Helper function for incrementing count one period at a time

        Args:
            commitment (int): commitment for a given hour
            initial_status (Union[float,int]): accummulated count

        Returns:
            Union[float,int]: accummulated count
        """

        period2hr = min_freq / 60  # note defining here, which
        ### single instance commitment
        if initial_status == 0:
            ### INITIALIZATION only!!!
            return period2hr if commitment > 0 else -1 * period2hr
        elif (initial_status < 0) and (commitment == 0):
            ### another period off-line
            return -1 * period2hr # + initial_status
        elif (initial_status < 0) and (commitment > 0):
            ### change of status: turn on
            return 1 * period2hr
        elif (initial_status > 0) and (commitment > 0):
            ### another period on-line
            return 1 * period2hr # + initial_status
        elif (initial_status > 0) and (commitment == 0):
            ### change of status: turn off
            return -1 * period2hr
        else:
            ### how did I get here?
            raise ValueError(
                f"count_onoff: unknown combination of initial_status={initial_status} and commitment={commitment}")

    # if initial_status is None and len(commitment) > 0:
    #     initial_status = [1 if commitment[0] > 0 else -1][0]

    if isinstance(commitment, list):
        ### time series
        # iterate backwards from t0idx until 0 or change of status
        tmp_initial_status = single_period_onoff(commitment[t0idx], 0, min_freq)
        break_flag = False
        for i in range(t0idx - 1, -1, -1):
            ### iterate backwards from t0
            new_initial_status = single_period_onoff(commitment[i], tmp_initial_status, min_freq)
            if np.sign(tmp_initial_status) == np.sign(new_initial_status):
                ### same direction
                tmp_initial_status += new_initial_status
            else:
                ### change of direction: break
                break_flag = True
                break
        if not break_flag:
            ### reached all the way to the beginning of the array, consider appending inital_status
            if np.sign(initial_status) == np.sign(tmp_initial_status):
                ### same direction: append
                return initial_status + tmp_initial_status
            else:
                ### change of direction right at beginning
                return tmp_initial_status
        else:
            ### change of direction was found: return just tmp initial status
            return tmp_initial_status

    # Old version, save until content that the new version is working
# def count_gen_onoff_periods(lst):
#     """Tool to calculate the number of on/off periods
#     We need to pull the last (not including lookahead) setpoint data from the mdl_sol timeseries and
#     update the current self.mdl with generator values from the solution.
#     1. lst contains all the generator set points, not including lookahead window. Lookahead window is currently
#         specified as the model configuration time window -- self.em.configuration['time']['window']
#         But this might need to be changed to the model configuration time lookahead -- self.em.configuration['time']['lookahead']
#     2. if the lst is empty (if not lst), the unit has been offline -- return 0, to mean that the unit is offline
#     3. we want to know *how many periods* the generator has been online (positive) and
#         how many periods the generator has been offline (negative)
#     example:
#     lst = [0,0,1,1]
#     count_gen_onoff_periods(lst) = 2
#     lst = [0,1,1,0]
#     count_gen_onoff_periods(lst) = -1
#
#     Function is used in osw_rt_market.py in CST in function update_model_from_previous.
#
#     Parameters
#     ----------
#     lst : list
#         contains all the generator set points, not including lookahead window
#
#     Returns
#     -------
#     integer
#         initial status of the generator
#         -- this is the update to the initial status, taken from the number of most recent
#         on/off periods from the model data dictionary in ['elements']['generator'][generatorname]['pg']['values']
#         TODO: not clear why I set this up to increment greater than 1 -- I think this is to account for startup times.
#     """
#     if not lst:
#         return 0
#     count = 0
#     value_type = 0 if lst[-1] == 0.0 else 1  # Check if trailing values are zeros or non-zeros
#     for num in reversed(lst):
#         if (value_type == 0 and num == 0.0) or (value_type == 1 and num != 0.0):
#             count += 1
#         else:
#             break
#     return count if value_type == 1 else -count
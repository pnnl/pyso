"""Utilites related to time management should be placed here"""

import warnings
from typing import Union

import numpy as np
import pandas as pd


def get_value_at_time(
    values_in: Union[list, np.ndarray],
    times_in: Union[list, np.ndarray, pd.DatetimeIndex],
    target_time: Union[str, pd.Timestamp],
    min_freq: float,
    interp: str = "linear",
    wrap: str = "periodic",
    **time_parse_kwargs,
):
    """
    Returns the value at a given target time, based on a time series input and given times.
    The target time does not need to be one of the time keys, but must be within the range of
    the time keys. Extrapolation of +/- 1 interval length is enabled (if DA values end at
    hour 23, we can extrapolate between hour 23 and 24).

    Args:
          values_in (Union[list, np.ndarray]): A list or array of values
          times_in (Union[list, np.ndarray, pd.date_range]): A list or array of times
          target_time (Union[str, pd.Timestamp]): The time at which to return a value
          min_freq (float): The frequency in minutes used for interpolation.
          interp (str, optional): Interpolation method used for the time series Defaults to
                                  'linear'. Choose from pd.Series.interpolate options or
                                  'beginning' -> Fills in the entire interval with the beginning
                                  value
                                  (step function)
                                  'ending' -> Fills in the entire interval with the ending value
                                  (step function)
          wrap (Union[str,None]): If extrapolating before/after times_in, selects how to extend
                                  values_in. Options are:
                                  'periodic' -> Assumes a period series so beginning of series is
                                  appended to the end, etc.
                                  'same' -> Keeps a constant beginning/ending value for all times
                                  outside of window
          **time_parse_kwargs: Keyword arguments to pass to the pandas to_datetime method.

    Returns:
        value (float): The value at a given target time
    """

    # Helper function for sorting
    def sort_values_in(values_in, times_in):
        # Ensure times and values are sorted ascending
        sort_inds = np.argsort(times_in)
        times_in = times_in[sort_inds]
        values_in = np.array(values_in)[sort_inds]
        return values_in, times_in

    if len(values_in) != len(times_in):
        err_msg = f"Time series (len={len(values_in)}) and time keys (len={len(times_in)})"
        raise ValueError(f"{err_msg} must have the same length")
    # Get times into a consistent format
    times_in = pd.to_datetime(times_in, **time_parse_kwargs)
    target_time = pd.to_datetime(target_time, **time_parse_kwargs)
    # If we are already at one of the times then return the value - no need to interpolate
    if target_time in times_in:
        target_index = np.where(times_in == target_time)[0][0]
        return values_in[target_index]

    values_in, times_in = sort_values_in(values_in, times_in)

    # If the target time is not in the interval, we extend the values_in and times_in series
    if target_time < times_in[0] or target_time > times_in[-1]:
        # Restrict keyword options to available choices
        wrap_choices = ["periodic", "same"]
        if wrap not in wrap_choices:
            raise ValueError(f"Keyword wrap must be one of {wrap_choices}")
        times_in_delta = times_in[1] - times_in[0]  # Get the time interval
        # Get the total start to finish span (add delta to get full span from start to next start)
        times_in_span = times_in[-1] - times_in[0] + times_in_delta
        # Separate handling for adding values to the end or beginning
        if target_time > times_in[-1]:
            # Duplicate input array (periodic or constant end) as needed to reach
            # target time
            ncopies = int(np.ceil((target_time - times_in[-1]) / times_in_span))
            # Set the new times_in, including copies
            times_in = pd.date_range(
                times_in[0], times_in[-1] + times_in_span * ncopies, freq=times_in_delta
            )
            # Set the updated values_in, depending on wrap choice
            if wrap == "periodic":
                # Tile will duplicate the array (add + 1 to ncopies to account for the original)
                values_in = np.tile(values_in, ncopies + 1)
            elif wrap == "same":
                # Uses last value as a constant
                # Calculate the number of new elements needed
                n_elements = len(values_in * ncopies)
                values_in = np.concatenate((values_in, np.ones(n_elements) * values_in[-1]))
        elif target_time < times_in[0]:
            # Duplicate input array (periodic or constant end) as needed to reach
            # target time
            ncopies = int(np.ceil((times_in[0] - target_time) / times_in_span))
            # Set the new times_in, including copies
            times_in = pd.date_range(
                times_in[0] - times_in_span * ncopies, times_in[-1], freq=times_in_delta
            )
            # Set the updated values_in, depending on wrap choice
            if wrap == "periodic":
                # Tile will duplicate the array (add + 1 to ncopies to account for the original)
                values_in = np.tile(values_in, ncopies + 1)
            elif wrap == "same":
                # Uses last value as a constant
                # Calculate the number of new elements needed
                n_elements = len(values_in * ncopies)
                values_in = np.concatenate((values_in, np.ones(n_elements) * values_in[0]))
        # Warning if the number of paddings is greater than one
        if ncopies > 1:
            warn_msg = (
                f"Target time of {target_time} is {ncopies} periods away from input time range."
            )
            warnings.warn(
                f"{warn_msg} This may indicate an error in the timing inputs.", stacklevel=2
            )

    # Create series, resample and get the value at the target time
    series = pd.Series(values_in, index=times_in)
    # Resamples the time series onto a finer time grid
    series = series.resample(f"{min_freq}min")
    if interp == "beginning":
        interp_series = series.ffill()
    elif interp == "ending":
        interp_series = series.bfill()
    else:
        interp_series = series.interpolate(interp)
    value = float(interp_series.loc[target_time])
    return value


def mk_daterange(
    start: Union[str, pd.Timestamp, None] = None,
    end: Union[str, pd.Timestamp, None] = None,
    min_freq: Union[None, int] = None,
    periods: Union[None, int] = None,
    **kwargs,
) -> pd.DatetimeIndex:
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
        * The data is (gen) is coming from a solved model that has the commitment key
          (thermal generators only)
        * The new instance will start at period t0idx + 1


    Args:
        gen (dict): parameter dictionary for a thermal generator (Egret format)
        t0idx (int): time index in the current model, representing t0 for the next one.
        min_freq (int, optional): time period resolution in minutes. Defaults to 60.
        max_lookback (int, optional): maximum of hours to look back before exiting loop.
            Defaults to 24.
    Returns:
        Union[float,int]: appropriate initial_status flag
    """

    def single_period_onoff(
        commitment: int, initial_status: Union[float, int], min_freq: int
    ) -> Union[float, int]:
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
            err_msg = f"count_onoff: unknown combination of initial_status={initial_status}"
            raise ValueError(f"{err_msg} and commitment={commitment}")

    # Load commitment and initial status from the generator dictionary
    commitment = gen.get("commitment", None)
    initial_status = gen["initial_status"]

    if commitment is None:
        raise KeyError(
            "count_onoff: the generator parameter dictionary must contain the 'commitment' key"
        )
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
            # Get commitment value and update status
            commitment_value = commitment["values"][i]
            new_initial_status = single_period_onoff(commitment_value, tmp_initial_status, min_freq)
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

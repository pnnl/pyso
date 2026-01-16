"""
Created on 06/28/2024

Class market objects in Egret

This assumes EGRET functionality has been implemented as class functions that
can be called as methods. (This may not be a hard assumption.)


@author: Trevor Hardy
trevor.hardy@pnnl.gov
"""

import copy
import datetime
import logging
import os
from typing import Union

import numpy as np
import pandas as pd

# from typing import TYPE_CHECKING
# if TYPE_CHECKING:
from egret.data.model_data import ModelData

from ..utils.timeutils import get_value_at_time, mk_daterange
from .market import Market
from .marketutils import add_load_curtail, convert_64

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.WARNING)


class RTMarket(Market):
    """
    We only need three market states so we provide hard-coded defaults.
    The way this market works, market activity takes place at the transitions.
    I'm (TDH) using the "transitions" library which allows the definition
    of callback functions when entering (and exiting) any given state
    and this is the primary method by which the activity will in the
    market will take place.

    Documentation on the "transitions" library can be found here:
    https://pypi.org/project/transitions/
    """

    def __init__(
        self,
        start_date,
        end_date,
        market_name: str = "rt_energy_market",
        market_timing: dict = None,
        min_freq: int = 15,
        window: int = 4,
        lookahead: int = 0,
        fixed_commitment=True,
        unfix_fast_start=False,
        **kwargs,
    ):
        """
        Class that specifically runs the RT energy market

        The only specialization is the definition of the callback method
        that gets called when the market state machine enters the "clearing"
        state.
        """
        # Supply a default market timing object for a 15-minute real-time
        if market_timing is None:
            market_timing = {
                "states": {
                    "idle": {"start_time": 0, "duration": 600},
                    "bidding": {"start_time": 600, "duration": 180},
                    "clearing": {"start_time": 780, "duration": 120},
                },
                "initial_offset": 0,
                "initial_state": "idle",
                "market_interval": 900,
            }
        super().__init__(market_name, market_timing, start_date, end_date, **kwargs)
        self.em.configuration["time"]["min_freq"] = min_freq
        self.em.configuration["time"]["window"] = window
        self.em.configuration["time"]["lookahead"] = lookahead
        # Arguments for adding new generators with bids
        self.bids = {}
        self.extra_gens = {}
        self.__dict__.update(kwargs)
        # starts at midnight
        # Create list of market start times based on frequency
        freq = f"{min_freq}min"
        self.start_times = self.interpolate_market_start_times(start_date, end_date, freq=freq)
        # Space for day-ahead solution (used in the first clear_market call)
        self.da_mdl_sol = None
        self.fixed_commitment = fixed_commitment  # Option to use a fixed or flexible commitment
        self.unfix_fast_start = unfix_fast_start  # Fast start units can remain flexible in RT

    def interpolate_market_start_times(
        self, start_date: str, end_date: str, freq: str = "15min", start_time: str = " 00:00:00"
    ):
        """
        Overloaded method of Market:
        Interpolates 15 (by default) minute data between two date strings.
        """

        # Convert strings to datetime objects
        start_datetime = pd.to_datetime(start_date)  # + start_time)
        end_datetime = pd.to_datetime(end_date)  # - pd.Timedelta(freq)# + start_time)

        # Generate hourly datetime index
        start_time_index = pd.date_range(start_datetime, end_datetime, freq=freq, inclusive="left")
        return start_time_index

    def collect_bids(self):
        """Overloaded method of Market: adding bids from generators and storage"""
        elements = self.em.mdl.data["elements"]
        for key in self.bids.keys():
            # Allow bids from both generators and storage. Search for name (key)
            element_types = ["generator", "storage"]
            for element_type in element_types:
                if element_type not in elements.keys():
                    continue
                if key in elements[element_type].keys():
                    elements[key] = self.bids[key]

    def add_gens(self):
        """Adds generators, including full Egret model data information to the model.
        This will look for any generators in the self.extra_gens dictionary.
        """
        for g, gdict in self.extra_gens.items():
            self.em.mdl.data["elements"]["generator"][g] = gdict

    def compute_end_soc(self, storage: str, max_num_intervals: Union[int, None] = 48):
        """This computes the ending state of charge at a given time

        Args:
            storage (str): The name of the storage unit to use in the calculation
            max_num_intervals (int): Maximum number of intervals to use for interpolation
        """
        if self.storage_soc is None:
            # Log warning about missing storage state of charge data
            warning_msg = "No storage SoC reference data found."
            logger.warning(f"{warning_msg} Proceeding without fixing end-state-of-charge.")
            return

        if isinstance(self.storage_soc, ModelData):
            reference_data = copy.deepcopy(self.storage_soc.data)
        else:
            reference_data = copy.deepcopy(self.storage_soc)

        # Set up the reference state-of-charge and time series
        ref_soc_series = reference_data["elements"]["storage"][storage]["state_of_charge"]["values"]
        ref_time_keys = reference_data["system"]["time_keys"]
        # We can restrict to the last N intervals to limit interpolation over large inputs
        if max_num_intervals is not None:
            ref_soc_series = ref_soc_series[-max_num_intervals:]
            ref_time_keys = ref_time_keys[-max_num_intervals:]
        # Set up the daterange for the current model
        # Calculate total periods as window plus lookahead
        window = self.em.configuration["time"]["window"]
        lookahead = self.em.configuration["time"]["lookahead"]
        periods = window + lookahead
        min_freq = self.em.configuration["time"]["min_freq"]
        model_start_time = self.em.mdl.data["system"]["time_keys"][0]
        daterange = mk_daterange(model_start_time, min_freq=min_freq, periods=periods)
        # ref_time_keys = ref_time_keys.drop_duplicates()
        end_soc = get_value_at_time(ref_soc_series, ref_time_keys, daterange[-1], min_freq)
        # Bound soc on interval [0, 1]
        end_soc = min(1, max(0, end_soc))
        return end_soc

    def update_end_soc(self):
        """
        Updates ending state of charge for all storage units.

        Uses reference values from day-ahead market to set end state of charge.
        """
        for storage, storage_dict in self.em.mdl.elements(element_type="storage"):
            # State-of-charge is handled by its own function.
            end_soc = self.compute_end_soc(storage)
            if end_soc is not None:
                storage_dict["end_state_of_charge"] = end_soc

    def update_em_model(self, contingency_list=None):
        """
        Applies updates to the Egret model before solving.

        Determines whether to use previous RT solution or DA input based on availability.
        """
        # Default is to calculate values based on previous solution
        update_mode = "calculate"
        use_sol = self.em.mdl_sol
        # For first RT market, we will copy starting values from the first DA market.
        if self.em.mdl_sol is None:
            update_mode = "copy"
            use_sol = self.da_mdl_sol
        # Update generator initial conditions and storage ending state-of-charge
        self.em.update_initial_conditions(use_sol, update_mode=update_mode)
        self.add_gens()
        self.update_end_soc()
        # Fix infeasibilities that may occur in first RT interval with pre-simulation
        # These are the conditions where fixes are needed:
        fix_infeasible = False
        if self.em.mdl_sol is None:
            # Only apply fixes when:
            # 1. No previous real-time model exists AND
            # 2. We have at least 1 pre-simulation day
            if self.pre_simulation_days is not None:
                if self.pre_simulation_days > 0:
                    fix_infeasible = True
        self.update_model_commitment(fix_infeasible=fix_infeasible)
        self.apply_contingencies(contingency_list=contingency_list)

    def clear_market(self, local_save=False, contingency_list: list = None):
        """
        Callback method that runs EGRET and clears a market.

        This method must be overloaded in an instance of this class to implement
        the necessary operations to clear the market in question.
        """
        if self.current_start_time > max(self.start_times):
            # Log warning when current time is past the planning horizon
            horizon_time = max(self.start_times)
            logger.warning(
                f"RT Market: Current start time {self.current_start_time} is past "
                f"horizon {horizon_time}. Market will not be cleared"
            )
            return
        self.em.get_model(self.current_start_time)
        self.update_em_model()
        self.em.mdl.data = convert_64(self.em.mdl.data)
        # Ramp rates can be binding - eventually we may find a better solution
        # For now, double ramp rates if solve is infeasible
        try:
            self.em.solve_model()
        except Exception as e:
            # Log error and retry with increased ramp rates
            error_msg = f"\nException found - error solving model: {e}."
            logger.error(f"{error_msg} Retrying with doubled ramp rates.\n")
            for _g, g_dict in self.em.mdl.elements(element_type="generator"):
                ramp_keys = ["ramp_up_60min", "ramp_down_60min"]
                for ramp_key in ramp_keys:
                    if ramp_key in g_dict.keys():
                        g_dict[ramp_key] = g_dict[ramp_key] * 2
            for _s, s_dict in self.em.mdl.elements(element_type="storage"):
                # Ramp rate keys for storage units
                ramp_keys = [
                    "ramp_up_input_60min",
                    "ramp_down_input_60min",
                    "ramp_up_output_60min",
                    "ramp_down_output_60min",
                ]
                for ramp_key in ramp_keys:
                    if ramp_key in s_dict.keys():
                        s_dict[ramp_key] = s_dict[ramp_key] * 2
            self.em.solve_model()

        self.market_results = self.em.mdl_sol
        self.market_results.data = convert_64(self.market_results.data)
        # If using fixed commitment history we do not want to update this during real-time
        if not self.fixed_commitment:
            self.store_commitment_hist(omit=["_load_curtail"])
        if self.local_save:
            os.makedirs("data", exist_ok=True)
            self.em.save_model(f"data/{self.market_name}_results_{self.timestep}.json")

        self.timestep += self.em.configuration["time"]["window"]
        if self.timestep >= len(self.start_times):
            # Add an interval (exact value doesn't matter, just need something past the horizon)
            min_freq = self.em.configuration["time"]["min_freq"]
            self.current_start_time += datetime.timedelta(minutes=min_freq)
        else:
            self.current_start_time = self.start_times[self.timestep]

    def join_da_commitment(self, da_commitment: dict):
        """
        Takes the day-ahead commitment schedule and interpolates onto the real-time intervals.

        Commitment values are kept constant for each hour. Default behavior preserves
        existing values. Run after each day-ahead market clearing to add commitment values
        for the next day.
        """
        # Duplicate day-ahead values onto the (likely) more frequent real-time intervals
        min_freq = self.em.configuration["time"]["min_freq"]
        # Add an hour to last timestamp to ensure coverage through end of day
        end = max(da_commitment["timestamps"])
        if isinstance(end, str):
            # Convert string to datetime, add hour, then back to string
            # Assumes format "YYYY-mm-dd HH:MM:SS"
            end = pd.to_datetime(end) + datetime.timedelta(hours=1)
            end = end.strftime("%Y-%m-%d %H:%M:%S")
        else:  # Hopefully any other datetime form or this will fail
            end += datetime.timedelta(hours=1)
        # Note inclusive='left' ensures we do not get 00:00:00 on the next day (assuming 24hr input)
        # Create interpolated timestamps at RT frequency
        start = min(da_commitment["timestamps"])
        da_timestamps_interp = pd.to_datetime(
            mk_daterange(start=start, end=end, min_freq=min_freq, inclusive="left")
        )
        # Loop through all generators
        da_commitment_interp = {"timestamps": da_timestamps_interp}
        for etype, edict in da_commitment.items():
            if etype != "timestamps":
                for unit, u_dict in edict.items():
                    # Create dictionary structure the first time through
                    # Prepare the commitment history dictionary structure
                    da_commitment_interp = self.prep_commitment_hist(
                        da_commitment_interp, etype, unit
                    )
                    # Call the fill_real_time function on this set of values
                    da_commitment_interp[etype][unit]["commitment"]["values"] = self.fill_real_time(
                        u_dict["commitment"]["values"]
                    )
                    # Add initial status
                    da_commitment_interp[etype][unit]["initial_status"] = u_dict["initial_status"]
        # Call method from the base class. Keep old ensures RT values aren't overwritten.
        # This will just add any new da_commitment values to the existing commitment history
        self.store_commitment_hist(keep="old", merge_dict=da_commitment_interp)

    def fill_real_time(self, da_list: list) -> list:
        """
        Takes a list of values from the (hourly) day-ahead market and copies into a longer
        list based on the real-time frequency in minutes.

        For example, if min_freq=15 this will copy each hourly value four times.

        Args:
            da_list (list): list of any kind of value from market day-ahead market

        Returns:
            rt_list (list): list of values copied into the real-time frequency
        """
        min_freq = self.em.configuration["time"]["min_freq"]
        # Determine the number of times to copy values
        remainder = 60 % min_freq
        if remainder != 0:
            # Warn if frequency doesn't divide evenly into hours
            logger.warning(
                f"Parameter min_freq {min_freq} is not a divisor of 60. Results may be inaccurate"
            )
        num_copy = int(60 / min_freq)
        # Use numpy arrays and repeat function for fast copying
        da_array = np.array(da_list)
        rt_array = da_array.repeat(num_copy)
        return list(rt_array)

    def _fix_infeasible(self, gen: str):
        """
        Checks for conflicts between initial status and commitment.

        Adjusts parameters to ensure the solution is feasible in Egret.
        Note: These fixes ensure feasibility but may not be the ideal choices
        for all physical scenarios.
        """

        def _get_pmin(g_dict):
            """Gets pmin value, grabbing 1st value if a timeseries dict is used"""
            if isinstance(g_dict["p_min"], dict):
                pmin = g_dict["p_min"]["values"][0]
            else:
                pmin = g_dict["p_min"]
            g_dict["initial_p_output"] = pmin
            return pmin

        g_dict = self.em.mdl.data["elements"]["generator"][gen]
        # Don't change wind/solar
        if g_dict["fuel"] in ["Solar", "Wind"] or "fixed_commitment" not in g_dict.keys():
            return
        # If starting with power and committed off set to p_min
        if g_dict["initial_p_output"] > 0 and g_dict["fixed_commitment"]["values"][0] == 0:
            pmin = _get_pmin(g_dict)
            g_dict["initial_p_output"] = pmin
            # Set status to minimum up time since it just turned off
            minimum_up_time = 0
            if "minimum_up_time" in g_dict.keys():
                minimum_up_time = g_dict["minimum_up_time"]
            elif "min_up_time" in g_dict.keys():
                minimum_up_time = g_dict["min_up_time"]
            g_dict["initial_status"] = max(1, minimum_up_time)
        elif g_dict["initial_p_output"] == 0 and g_dict["fixed_commitment"]["values"][0] == 1:
            pmin = _get_pmin(g_dict)
            # Set status to -minimum down time since it just turned on
            minimum_down_time = 0
            if "minimum_down_time" in g_dict.keys():
                minimum_down_time = g_dict["minimum_down_time"]
            elif "min_down_time" in g_dict.keys():
                minimum_down_time = g_dict["min_down_time"]
            g_dict["initial_status"] = -max(1, minimum_down_time)

    def update_model_commitment(self, fix_infeasible: bool = False):
        """
        Pull last setpoint data from mdl_sol timeseries and
        update the current self.mdl with generator values from solution.

        Args:
            fix_infeasible (bool, optional): if True, fix possible infeasible states in self.em.mdl
        """
        # Windows
        time_window = self.em.configuration["time"]["window"]
        lookahead = self.em.configuration["time"]["lookahead"]
        # Log debug info about the current update operation
        debug_msg = (
            f"Updating commitment history for RT market at timestep {self.timestep} "
            f"(time is {self.current_start_time})"
        )
        logger.debug(debug_msg)
        if self.em.mdl is not None:
            for g, g_dict in self.em.mdl.elements(element_type="generator"):
                # Load the commitment history for this generator
                commit_hist = self.commitment_hist["generator"][g]
                # Match timestamps to find the appropriate index from the commitment history
                if self.current_start_time in self.commitment_hist["timestamps"]:
                    # Find index where current timestamp matches commitment history timestamps
                    timestamps_array = np.array(self.commitment_hist["timestamps"])
                    match_indices = np.where(self.current_start_time == timestamps_array)[0]
                    t0idx = match_indices[0]
                else:
                    # Create error message for missing timestamp
                    error_msg = (
                        f"Time {self.current_start_time} is not in commitment history timestamps:\n"
                        f"{self.commitment_hist['timestamps']}."
                    )
                    raise ValueError(error_msg)

                # It is possible for t0idx in the last interval to have no commitments available
                # (if no day-ahead lookahead). If so, there are no commitments to add.
                # Otherwise, pass the commitments for the appropriate window
                if t0idx < len(commit_hist["commitment"]["values"]):
                    # Get commitment values for the current window plus lookahead
                    window_end = t0idx + time_window + lookahead
                    commit_hist_window = commit_hist["commitment"]["values"][t0idx:window_end]
                    # If missing lookahead (possible at end of horizon) duplicate the last value
                    if len(commit_hist_window) < time_window + lookahead:
                        add_len = time_window + lookahead - len(commit_hist_window)
                        # Handling for list or array format
                        if isinstance(commit_hist_window, list):
                            # Extend list with repeats of the last value
                            last_value = commit_hist_window[-1]
                            extension = [last_value] * add_len
                            commit_hist_window = commit_hist_window + extension
                        elif isinstance(commit_hist_window, np.ndarray):
                            # For numpy arrays, extend with repeats of the last value
                            last_value = commit_hist_window[-1]
                            extension = np.ones(add_len) * last_value
                            commit_hist_window = np.concatenate((commit_hist_window, extension))
                    # Standard behavior is to fix commitment, but we can send commitment
                    # without fixing if we want a more flexible RT market.
                    if self.fixed_commitment:
                        # Only fix the values in the window (Set all lookahead values to None)
                        # Not currently using this approach
                        # Uncomment to set lookahead values to None (not currently used)
                        # lookahead_len = len(commit_hist_window[time_window:])
                        # commit_hist_window[time_window:] = [None for _ in range(lookahead_len)]
                        commit_type = "fixed_commitment"
                        # Option to unfix commitment for fast-start units
                        # Variables are still passed to 'commitment'
                        # Fixed ON (1) will remain, but fixed off (0) will be allowed to vary
                        if self.unfix_fast_start:
                            if "fast_start" in g_dict.keys() and g_dict["fast_start"]:
                                # Calculate the total number of periods
                                total_periods = time_window + lookahead
                                # If all are on (1) don't change.
                                # Otherwise check if all off or mixed on/off state
                                if sum(commit_hist_window) == total_periods:
                                    pass
                                # If all are off, pass these to the commitment variable
                                # (starts as off, but allows turn on)
                                elif sum(commit_hist_window) == 0:
                                    commit_type = "commitment"
                                # Special case - mixed commitment.
                                # Pass all to commitment AND fix any 1 values
                                # but use None instead of 0 for off
                                else:
                                    # Store commitment time series in generator dictionary
                                    g_dict["commitment"] = {
                                        "data_type": "time_series",
                                        "values": commit_hist_window,
                                    }
                                    # Keep ON (1) values fixed, but allow OFF (0) to vary
                                    commit_hist_window = [
                                        v if v == 1 else None for v in commit_hist_window
                                    ]
                        # Update the commitment
                        # (fixed_commitment or commitment for fast-start units)
                        # Store the commitment values in generator dictionary
                        g_dict[commit_type] = {
                            "data_type": "time_series",
                            "values": commit_hist_window,
                        }
                        # Pass to check for scenarios that give infeasible results
                        # (only if taking initial day-ahead input)
                        if fix_infeasible and commit_type == "fixed_commitment":
                            self._fix_infeasible(g)
                    else:
                        # Store the commitment values for the flexible model
                        g_dict["commitment"] = {
                            "data_type": "time_series",
                            "values": commit_hist_window,
                        }
        else:
            raise ValueError("No Egret model currently loaded.")

    def store_storage_soc(self, max_intervals: int = 24):
        """
        Saves the storage state-of-charge at the corresponding times.
        This could possibly be merged into a common function with store_commitment_hist
        that accepts element type and keys, but that may be hard to get correct for general cases.

        Args:
            max_intervals (int): The maximum number of time intervals to save
                (default is 24, assuming hourly DA)
        """
        # If no storage units are in the model, don't continue
        if "storage" not in self.em.mdl_sol.data["elements"].keys():
            return
        # Time keys - we pad the last interval since Egret gives soc values at END of interval
        # while keys represent the START of each interval
        time_keys = pd.to_datetime(self.em.mdl_sol.data["system"]["time_keys"])[:max_intervals]
        # Calculate time difference between last two intervals
        time_diff_seconds = (time_keys[-1] - time_keys[-2]).total_seconds()
        time_delta_end_minutes = int(time_diff_seconds / 60.0)
        # Add an additional time key at the end
        additional_time = time_keys[-1] + datetime.timedelta(minutes=time_delta_end_minutes)
        time_keys = time_keys.append(pd.to_datetime([additional_time]))
        # Convert to Timestamp to enable addition/subtraction of Timedeltas
        time_keys = [pd.Timestamp(tk) for tk in time_keys]
        # Create dict if needed with the timestamps as a top level key (shared by all storage units)
        use_soc_init = False
        if self.storage_soc is None:
            self.storage_soc = {"system": {"time_keys": time_keys}, "elements": {"storage": {}}}
            # The first time through we use soc init
            # (all other times it is the same as last value of previous)
            use_soc_init = True
        else:
            # Don't copy the first interval (it was added last time by the end padding)
            # Append new time keys (skipping the first which would be duplicate)
            current_keys = self.storage_soc["system"]["time_keys"]
            self.storage_soc["system"]["time_keys"] = current_keys.append(time_keys[1:])
        # loop through storage units
        for storage, storage_dict in self.em.mdl_sol.data["elements"]["storage"].items():
            soc_values = storage_dict["state_of_charge"]["values"][:max_intervals]
            if use_soc_init:
                soc_init = storage_dict["initial_state_of_charge"]
                soc_values = np.append(np.array([soc_init]), soc_values)
            # If previous values are in the storage dictionary, we will append new values to the end
            if storage in self.storage_soc["elements"]["storage"].keys():
                # Get previous state of charge values
                prev_storage_path = self.storage_soc["elements"]["storage"][storage]
                prev_soc_values = prev_storage_path["state_of_charge"]["values"]
                soc_values = np.append(prev_soc_values, soc_values)
            # Create storage state of charge data
            soc_data = {"state_of_charge": {"data_type": "time_series", "values": soc_values}}
            self.storage_soc["elements"]["storage"][storage] = soc_data

    def update_state_of_charge(self, storage, market_type="day_ahead"):
        """
        Updates the state of charge in the egret ModelData object for the given storage
        Two situations:
            market_type = 'day_ahead':
                Populates init_state_of_charge from the end of the previous solution
                and sends end_state_of_charge = init_state_of_charge

            market_type = 'real_time':
                Populates initial state of charge based on self.storage_soc (saved from DA)
                at the current time and end_state_of_charge at the end of the window + lookahead
        """
        window = self.em.configuration["time"]["window"]
        if market_type == "day_ahead":
            # If no solution exists (first time) just use whatever is already in the input model
            if self.em.mdl_sol is None:
                return
            # Use soc and end of window (these are the values saved, excluding lookahead)
            # Get the state of charge from the previous solution
            storage_path = self.em.mdl_sol.data["elements"]["storage"][storage]
            soc_value = storage_path["state_of_charge"]["values"][window - 1]

            # Update initial and end state of charge
            storage_model = self.em.mdl.data["elements"]["storage"][storage]
            storage_model["initial_state_of_charge"] = soc_value
            storage_model["end_state_of_charge"] = storage_model["initial_state_of_charge"]
        elif market_type == "real_time":
            # If no saved storage, we have no reference to use
            if self.storage_soc is None:
                return
            # Initial soc is the self.storage_soc at current time (which may require interpolation)
            # We restrict to the last 48 intervals
            # (assumes soc is stored hourly, which is true at time of creation)
            limit = 48
            # Get state of charge values with limit
            storage_path = self.storage_soc["elements"]["storage"][storage]["state_of_charge"]
            da_soc_series = storage_path["values"][-limit:]
            da_time_keys = self.storage_soc["system"]["time_keys"][-limit:]
            # We get initial soc from the last RT interval, when available.
            # Otherwise, we look up values from the day-ahead market
            if self.em.mdl_sol is None:
                # Get value from DA time series at current time
                lookup_init_soc = get_value_at_time(
                    da_soc_series, da_time_keys, self.current_start_time
                )
            else:
                # Get the state of charge from previous solution
                storage_path = self.em.mdl_sol.data["elements"]["storage"][storage]
                lookup_init_soc = storage_path["state_of_charge"]["values"][window - 1]
            # Bound soc on interval [0, 1]
            lookup_init_soc = min(1, max(0, lookup_init_soc))
            # Update initial state of charge in the model
            storage_model = self.em.mdl.data["elements"]["storage"][storage]
            storage_model["initial_state_of_charge"] = lookup_init_soc
            # For end soc we use the same da series and time keys, but find end interval time
            # Calculate periods and time frequency for date range
            window = self.em.configuration["time"]["window"]
            lookahead = self.em.configuration["time"]["lookahead"]
            periods = window + lookahead
            min_freq = self.em.configuration["time"]["min_freq"]
            daterange = mk_daterange(self.current_start_time, min_freq=min_freq, periods=periods)
            # While loop ensures that we don't extend past the horizon (only affects last interval)
            end_soc_found = False
            lookback, limit = 1, len(daterange)
            lookup_end_soc = None
            while not end_soc_found and lookback < limit:
                try:
                    lookup_end_soc = get_value_at_time(da_soc_series, da_time_keys, daterange[-1])
                    end_soc_found = True
                except ValueError:
                    lookback += 1
            if lookup_end_soc is not None:
                # Bound soc on interval [0, 1]
                lookup_end_soc = min(1, max(0, lookup_end_soc))
                # Update end state of charge in the model
                storage_model = self.em.mdl.data["elements"]["storage"][storage]
                storage_model["end_state_of_charge"] = lookup_end_soc

    def apply_contingencies(self, contingency_list=None, scale_branch_list=None, scale_ratio=2):
        """If including contingencies, turn off unused branches"""
        # Apply contingencies: mark specified branches out of service
        if contingency_list:
            branches = self.em.mdl.data["elements"]["branch"]
            dc_branches = self.em.mdl.data["elements"]["dc_branch"]
            for br in contingency_list:
                if br in branches:
                    branches[br]["in_service"] = False
                    logger.info(f"Applied contingency: set {br}.in_service = False")
                elif br in dc_branches:
                    dc_branches[br]["in_service"] = False
                    logger.info(f"Applied contingency: set {br}.in_service = False to dc_branch")
                else:
                    logger.warning(f"Contingency branch '{br}' not found in model")

        # Scale rating parameters for specified branches by scale_ratio
        if scale_branch_list and scale_ratio != 1.0:
            branches = self.em.mdl.data["elements"]["branch"]
            # Parameters that should be scaled
            parameters = [
                "rating_long_term",
                "rating_short_term",
                "winter_a",
                "winter_c",
                "summer_a",
                "summer_c",
            ]
            for br in scale_branch_list:
                branch_data = branches.get(br)
                if branch_data:
                    for param in parameters:
                        if param in branch_data:
                            original = branch_data[param]
                            # Multiply the original value by the given ratio
                            branch_data[param] = original * scale_ratio
                            logger.info(
                                f"Scaled {param} for branch '{br}': "
                                f"{original} -> {branch_data[param]}"
                            )
                        else:
                            # Warn if a parameter is missing
                            logger.warning(f"Parameter '{param}' not found in branch '{br}'")
                else:
                    # Warn if the branch isn't found
                    logger.warning(f"Branch '{br}' not found; cannot scale parameters")
        # Egret script to add a generator at each node at load curtailment cost
        # (ensures feasibility by allowing load shedding)
        add_load_curtail(self.em.mdl)

    def restore_lines(self):
        """Egret removes lines with in_service set to False. We will add them back in here,
        setting the pf (power flow) values to zero
        """
        line_types = ["branch", "dc_branch"]
        for line_type in line_types:
            # Loop through the input model branches
            for branch, branch_dict in self.em.mdl.data["elements"][line_type].items():
                # Look for out-of-service lines
                if not branch_dict["in_service"]:
                    mdl_sol_dict = self.em.mdl_sol.data["elements"][line_type]
                    # Double-check that the branch isn't already in the model solution
                    if branch in mdl_sol_dict.keys():
                        continue
                    # Add a copy of the model dict with this branch
                    mdl_sol_dict[branch] = copy.deepcopy(branch_dict)
                    # Set power flow == 0
                    empty_list = [0.0 for i in range(len(self.em.mdl.data["system"]["time_keys"]))]
                    if "pf" in mdl_sol_dict[branch].keys():
                        mdl_sol_dict[branch]["pf"]["values"] = empty_list
                    else:
                        mdl_sol_dict[branch]["pf"] = {
                            "data_type": "time_series",
                            "values": empty_list,
                        }
                    # Also add no pf_violation
                    mdl_sol_dict[branch]["pf_violation"] = {
                        "data_type": "time_series",
                        "values": empty_list,
                    }

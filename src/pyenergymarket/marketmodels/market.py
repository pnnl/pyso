"""
Created on 06/28/2024

Class market objects in Egret

This assumes EGRET functionality has been implemented as class functions that
can be called as methods. (This may not be a hard assumption.)


@author: Trevor Hardy
trevor.hardy@pnnl.gov
"""

import datetime as dt
import logging
import math
from copy import deepcopy
import abc
from typing import Union

import numpy as np
import pandas as pd
from transitions import Machine

from ..engine import EnergyMarket

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.WARNING)

class MarketTiming:
    """Class that defines the timing of various market states
    """
    def __init__(self, market_interval, timing:list[dict], initial_offset=0, **kwargs):
        """initialize market timing class indicating interval and the timing
        definition.
        
        Note:
            The units for all timing, interval etc. are currently not fixed.
            This is because some may work with integer counters, while others
            with timedelta objects.

        Args:
            market_interval (Any): Duration of one cycle through the state timing list
            timing (list[dict]): list of states within a market cycle (in ORDER).
                                 each entry must have the following keys:
                                     - name (str): name of the state
                                     - start_time: the time within the market interval where this state is transitioned into.
            initial_offset (optional, int): this gets added to the first state transition calculation. Probably just keep it 0.
        """

        self.intial_offset=initial_offset
        self.market_interval = market_interval
        self.timing = deepcopy(timing)

        ## calculate duration
        ## TODO: what if the first start_time is not 0 or Timedelta(0) etc....that would be a user error but we should catch it.
        for i, d in enumerate(self.timing):
            if i == (len(self.timing) - 1):
                d["duration"] = market_interval - d["start_time"]
            else:
                d["duration"] = self.timing[i+1]["start_time"] - d["start_time"]
    
    @property
    def state_list(self) -> list[str]:
        return [d["name"] for d in self.timing]


class Market(abc.ABC):
    """

    For the off-shore-wind use case, we only need three market states so
    those will be hard-coded as below. The way this market works, all of
    the activity of the market takes place at the transitions. I'm
    (TDH) using the "transitions" library which allows the definition
    of callback functions when entering (and exiting) any given state
    and this is the primary method by which the activity will in the
    market will take place.

    Documentation on the "transitions" library can be found here:
    https://pypi.org/project/transitions/


    Not to scale but the market timing looks like this:

        idle start       bidding start         clearing start       next
        |                |                     |                    idle start
        |                |                     |                    |
        |                |                     |                    |
        V                V                     V                    V
        *--idle dur------*-----bidding dur-----*--clearing dur------*

    """

    pass

    def __init__(
        self,
        market_name:str,
        market_timing:Union[MarketTiming, dict],
        start_date:str,
        end_date:str,
        market: EnergyMarket,
        local_save=False,
        **kwargs,
    ):
        """
        Generic version of all the markets used in the E-COMP LDRD initiative.
        As such, this is fairly particular to those needs and is
        correspondingly simple. When update_market is called, the market
        state machine moves to the next state and the time for the next
        market transition is called. This is all just logistics for running
        the market.

        The real magic of this happens when you sub-class this and add in
        callback methods that are called when entering particular states.

        """
        self.em = market
        self.market_name = market_name
        self.market_timing = market_timing if isinstance(market_timing, MarketTiming) else MarketTiming(**market_timing)
        # Calculate market frequency from configuration
        min_freq = self.em.configuration["time"]["min_freq"]
        time_window = self.em.configuration["time"]["window"]
        # Calculate market frequency based on time window and min frequency
        market_frequency = f"{min_freq * time_window}min"
        # Create list of market start times based on frequency
        self.start_times = self.interpolate_market_start_times(
            start_date, end_date, freq=market_frequency
        )
        logger.info("market", self.market_name, "start_times: ", self.start_times)
        self.timestep = 0
        self.current_start_time = self.start_times[self.timestep]
        self.last_state = None
        self.send_horizon_message = True  # Will send a message when timestamp is past the horizon
        self.market_timing = deepcopy(market_timing)
        self.market_results = None

        self.add_state_machine()

        # Default settings for various user inputs
        self.commitment_hist = None
        self.storage_soc = None
        self.pre_simulation_days = None
        self.local_save = local_save

        # This translates all the kwarg key-value pairs into class attributes
        # self.__dict__.update(kwargs)

    @property
    def state_list(self) -> list[str]:
        return self.market_timing.state_list

    def add_state_machine(self):
        """
        This creates and adds a transitions state machine object to the market.
        The state machine handles timing checks and transitions.

        Relies on the self.market_timing dict (an input argument for __init__)
        This dictionary provides the different state information, including start times and
        durations (default unit is second, can be set to year, day, hour, minute, second).
        Format example is given below:

            {
            "states": {
                "idle": {
                    "start_time": 0,
                    "duration": 42660,
                    "unit": "second"
                },
                "bidding": {
                    "start_time": 42660,
                    "duration": 540,
                    "unit": "second"
                },
                "clearing": {
                    "start_time": 43200,
                    "duration": 43200,
                    "unit": "second"
                },
            },
            # How many seconds into the interval to start (0=start of interval)
            "initial_offset": 0,
            # Initial state (should match initial offset)
            "initial_state": "idle",
            # Total length of interval (must equal sum of all durations)
            "market_interval": 86400
        }
        """
        # Check that market timing dictionary fits expected format
        self.validate_market_timing()
        # Set up all of the time tracking object
        self.timestep = 0
        self.current_start_time = self.start_times[self.timestep]
        self.current_state = "initialization"
        self.last_state = None
        self.last_state_time = 0
        self.next_state_time = 0
        # Add the state machine
        # self.state_machine = Machine(model=self, states=self.state_list, initial=self.current_state)
        self.state_machine = Machine(model=self, states=["initialization"] + self.state_list, initial="initialization")
        self.state_machine.add_ordered_transitions(self.state_list)
        
        # add a transition from initialization to the first state
        self.state_machine.add_transition(trigger="do_initialization", source="initialization", dest=self.state_list[0])

        # Adding definitions for state transition callbacks
        # These are automatically executed on state transitions
        
        self.state_machine.on_enter_bidding("collect_bids")
        self.state_machine.on_enter_clearing("clear_market")
        self.state_machine.on_exit_clearing("publish_results")

    @abc.abstractmethod
    def do_initialization(self) -> None:
        """This method executes any initialization steps
        """
        pass

    def validate_market_timing(self) -> None:
        """
        Validate that the provided market timing. Specifically check:
         - "states" keyword is present all states have the "start_time" and "duration" keys
         - initial offset and initial state match
         - total durations from all states are equal to the market_interval keyword
        """
        market_timing = self.market_timing
        if not isinstance(market_timing, dict):
            raise TypeError(f"Must submit market_timing as a dictionary, not {type(market_timing)}")
        # Ensure the market_timing dict has the necessary keys (extraneous keys aren't penalized)
        required_keys = ["states", "initial_offset", "initial_state", "market_interval"]
        if set(required_keys) < set(market_timing.keys()):
            # Construct error message for missing required keys
            err_msg = f"Market timing dict must contain keys: {required_keys}."
            details = f"(Passed {market_timing.keys()})"
            raise KeyError(f"{err_msg} {details}")
        # Ensure all states have the necessary keys (extraneous keys aren't penalized)
        required_state_keys = ["start_time", "duration"]
        allowed_units = ["year", "day", "hour", "minute", "second"]
        for state, state_dict in market_timing["states"].items():
            if set(state_dict.keys()) < set(required_state_keys):
                # Provide clear error for missing required keys in a state
                err_msg = f"Invalid keys for state {state}."
                details = f"All state dicts must contain keys: {required_state_keys}."
                raise KeyError(f"{err_msg} {details}")
            # If units are included, they must be from a given set
            if "unit" in state_dict:
                if state_dict["unit"] not in allowed_units:
                    # Provide clear error for invalid unit in a state
                    invalid_unit = state_dict["unit"]
                    err_msg = f"Invalid unit {invalid_unit} for state {state}."
                    details = f"Valid unit choices are: {allowed_units}."
                    raise KeyError(f"{err_msg} {details}")
        # Ensure the starting state is specified (0 start time)
        current_state = [
            st for st, val in market_timing["states"].items() if val["start_time"] == 0
        ]
        # if len(current_state) != 1:
        #     raise ValueError(f"Must include one and only one state with the start time of 0")
        # else:
        current_state = current_state[0]  # get key/string
        # Check that start times and durations are all consistent
        start_times = [val["start_time"] for val in market_timing["states"].values()]
        current_time = 0
        next_start = 0
        for _change_idx in range(len(start_times) - 1):
            duration = market_timing["states"][current_state]["duration"]
            next_start = current_time + duration
            # Search to see if any states have the next start time listed
            found_next = False
            for state, state_dict in market_timing["states"].items():
                if math.isclose(state_dict["start_time"], next_start):
                    current_state = state
                    current_time = state_dict["start_time"]
                    found_next = True
            if not found_next:
                raise ValueError(f"No state found with expected start time {next_start}")
        # Finally, check if the total duration equals the market_interval
        # (total is 'next_start' from above loop + final state's duration)
        total_duration = next_start + market_timing["states"][current_state]["duration"]
        if not math.isclose(total_duration, market_timing["market_interval"]):
            err_msg = f"Total state durations of {next_start}"
            market_interval = market_timing["market_interval"]
            raise ValueError(f"{err_msg} do not match market_interval of {market_interval}")

    def move_to_next_state(self, *args, **kwargs) -> str:
        """
        Transitions to the next state in the state machine and updates
        appropriate object parameters.
        Input arguments and kwargs can be provided for the function call to the next state
        """
        # Store previous state, move states, then update current state
        # Note: transitions automatically execute methods specified in add_state_machine
        self.last_state = self.current_state
        self.next_state(*args, **kwargs)
        self.current_state = self.state
        logger.debug(self.market_name, "Last state:", self.last_state)
        logger.debug(self.market_name, "Next state:", self.current_state)
        logger.info(f"{self.market_name} moved from {self.last_state} to {self.current_state}")
        return self.current_state

    def calculate_next_state_time(self, return_last=True) -> tuple[float, float]:
        """
        Calculate the value of the next state in terms of simulation time
        based on the timing of the next state in the state machine.
        """
        last_state_time = self.last_state_time
        # Calculate next state time based on current state duration, last time, and initial offset
        current_state_duration = self.market_timing["states"][self.current_state]["duration"]
        initial_offset = self.market_timing["initial_offset"]
        self.next_state_time = current_state_duration + last_state_time + initial_offset
        # Initial offset only matters on first pass (included above).
        # After first pass, set to 0 for correct timing
        self.market_timing["initial_offset"] = 0
        logger.info(f"{self.market_name}.next_state_time: {self.next_state_time}")
        if return_last:
            return last_state_time, self.next_state_time
        else:
            return self.next_state_time

    def update_market(self):
        """
        This method drives the state machine which drives all the other
        functionality via callbacks.

        An earlier version of this received the simulation time and checked
        to see if it was time to move to the next market state. For now
        that check is done by the instantiating object and it is assumed
        when this method is called, it's time to move to the next state
        """
        _, next_state_time = self.calculate_next_state_time()
        self.last_state_time = next_state_time
        return next_state_time  # current time

    def interpolate_market_start_times(
        self, start_date, end_date, freq="24h", start_time=" 00:00:00"
    ):
        """Interpolates 24 (by default) hourly data between two date strings."""

        # Convert strings to datetime objects
        start_datetime = pd.to_datetime(start_date + start_time)
        end_datetime = pd.to_datetime(end_date + start_time)

        # Generate hourly datetime index
        start_time_index = pd.date_range(start_datetime, end_datetime, freq=freq, inclusive="left")
        return start_time_index

    @abc.abstractmethod
    def collect_bids(self):
        """
        Callback method to pull in data.

        This method must be overloaded in an instance of this class to
        implement the necessary operations to collect the bids in question.
        """
        pass

    @abc.abstractmethod
    def publish_results(self):
        """
        Method to publish results from clear_market method.

        This method must be overloaded in an instance of this class to
        implement the necessary operations to publish the results in question.
        """
        pass
    
    @abc.abstractmethod
    def clear_market(self, local_save=False, contingency_list=None):
        """
        Callback method that runs EGRET and clears a market.

        This method must be overloaded in an instance of this class to
        implement the necessary operates to clear the market in question.

        Args:
            local_save (bool, optional): if True, will save a JSON with the results at each timestep
        """
        # Don't run market if this start time exceeds the start time list
        if not self.valid_time_horizon():
            return

        self.em.get_model(self.current_start_time)
        # Modifications to model before solve, depending on use-case
        self.em.update_initial_conditions(self.em.mdl_sol)
        self.em.solve_model()
        if local_save:
            self.em.save_model(f"data/{self.market_name}_results_{self.timestep}.json")
        self.market_results = self.em.mdl_sol
        self.timestep += 1
        if self.timestep >= len(self.start_times):
            # Add a day (exact value doesn't matter, just need something past the horizon)
            self.current_start_time += dt.timedelta(days=1)
        else:
            self.current_start_time = self.start_times[self.timestep]
        logger.info("Market ", self.market_name, "next start time: ", self.current_start_time)

    def reset_timestep(self, timestep=0, shift_commitment=True):
        """Resets the timestep to 0 (option to fix to a different value)
            This also sends the commitment history backward by the number
            of timesteps.

        Args:
            timestep (int): Specifies the timestep after the reset
            shift_commitment (bool): Option to also shift the commitment history times back
                                     by the start/stop time difference. This behavior supports
                                     pre-simulation runs where commitments happened in the past
        """
        self.timestep = timestep
        self.current_start_time = self.start_times[self.timestep]  # Also reset current start time
        # Check conditions for shifting commitment history
        has_presim = self.pre_simulation_days is not None
        has_commit_hist = self.commitment_hist is not None
        if shift_commitment and has_presim and has_commit_hist:
            # Compute the time to shift as the difference between the
            start_time = self.start_times[0]
            commitment_end_time = self.commitment_hist["timestamps"][-1]
            # Add the last interval since end time doesn't include the last time step
            interval = commitment_end_time - self.commitment_hist["timestamps"][-2]
            commitment_end_time += interval
            time_shift = (commitment_end_time - start_time) * self.pre_simulation_days
            for i in range(len(self.commitment_hist["timestamps"])):
                self.commitment_hist["timestamps"][i] -= time_shift
            # We also shift the state_of_charge, if it is present
            if self.storage_soc is not None:
                time_keys = list(self.storage_soc["system"]["time_keys"])
                for j in range(len(self.storage_soc["system"]["time_keys"])):
                    time_keys[j] -= time_shift
                self.storage_soc["system"]["time_keys"] = pd.Index(time_keys)

    def valid_time_horizon(self):
        """Returns T if current start time is within the horizon, otherwise F"""
        if self.current_start_time > max(self.start_times):
            if self.send_horizon_message:
                # Log warning when current start time exceeds the planning horizon
                horizon_time = max(self.start_times)
                # Create warning message about exceeding horizon
                # Format message about current time exceeding horizon
                info_msg = (
                    f"Current start time {self.current_start_time} is past horizon {horizon_time}"
                )
                logger.info(f"{info_msg} Market will not be cleared")
                self.send_horizon_message = False  # Only send warning once
            return False
        return True

    @staticmethod
    def prep_commitment_hist(commitment_dict, etype, unit):
        """
        Creates an empty dictionary structure for the commitment history for a given element
        and generator/unit

        Args:
            etype (str): Type of element ('generator', 'storage', etc.)
            unit (str): Name of unit (typical use case is Egret generator name)
        """
        if etype not in commitment_dict.keys():
            # Create the empty structure for the commitment history
            commitment_data = {
                "initial_status": None,
                "commitment": {"data_type": "time_series", "values": []},
            }
            commitment_dict[etype] = {unit: commitment_data}
        if unit not in commitment_dict[etype].keys():
            # Create the empty structure for this specific unit
            commitment_dict[etype][unit] = {
                "initial_status": None,
                "commitment": {"data_type": "time_series", "values": []},
            }
        return commitment_dict

    def store_commitment_hist(self, keep="new", merge_dict=None, omit=None):
        """
        Updates the commitment and initial status of generators (and storage) based on the
        model solution from a cleared market. Stored in the self.commitment_hist dictionary
        This is a partial copy of the Egret generator element dictionary, specifically designed
        to hold and update commitment history (and initial status) as markets pass

        Implementation Notes:
        - We could merge entire egret models (not just commitment history),
          though conflicts may arise if settings change
        - RAM usage would likely not be an issue even with larger models
        - This method could be generalized to merge any time series,
          with appropriate special handling where needed

        Args:
            keep (string): For duplicate timestamps, whether to keep 'new' or 'old' values.
                           Defaults to 'new'.
            merge_dict (dict): Option to merge a commitment history (e.g., DA into RT).
                               When specified, Egret model is ignored. Keep='new' will use
                               the merge_dict values for duplicate timestamps.
                               Defaults to None.
            omit (list): List of strings for generators to omit. Can use partial matches.
                         Example: omit = ['_w_new'] will omit generators with '_w_new' in name.
        """
        if omit is None:
            omit = []

        # Helper function to check if any omit strings are in the unit name
        def omit_unit(unit: str, omit: list):
            omit_status = False
            for om in omit:
                if om in unit:
                    omit_status = True
                    break
            return omit_status

        # Create dict if needed with timestamps as top level key (shared by all elements)
        if self.commitment_hist is None:
            self.commitment_hist = {"timestamps": []}
        # Keep a copy of the old and the new timestamps
        commit_times_hist = self.commitment_hist["timestamps"]
        # Get new timestamps either from model solution or merge dictionary
        if merge_dict is None:
            commit_times_new = pd.to_datetime(self.em.mdl_sol.data["system"]["time_keys"])
        else:
            commit_times_new = merge_dict["timestamps"]
        # Join times, ensuring that any shared times are not duplicated
        # Find common timestamps and their indices
        common_times, i_hist, i_new = np.intersect1d(
            commit_times_hist, commit_times_new, return_indices=True
        )
        # Append new timestamps that aren't in the history
        # Get timestamps from new data that don't exist in history
        new_indices = [i for i in range(len(commit_times_new)) if i not in i_new]
        new_timestamps = [commit_times_new[i] for i in new_indices]
        commit_times_all = commit_times_hist.extend(new_timestamps)
        # Check whether to loop over stored PyEnergyMarket Model or an input model dictionary
        loop_dict = self.em.mdl_sol.data["elements"] if merge_dict is None else merge_dict
        for etype, e_dict in loop_dict.items():
            # etype is 'generator', 'renewable', 'load', etc. - Egret element types
            # e_dict holds individual unit info for each element type
            # Restrict to committable elements for efficiency (slight risk of missing types)
            if etype in ["generator"]:
                for unit, u_dict in e_dict.items():
                    if omit_unit(unit, omit):
                        continue  # Skip if unit name is in the omit list
                    # Add empty structure if it doesn't exist. Format matches Egret plus timestamps.
                    # Prepare the commitment history dictionary structure
                    self.commitment_hist = self.prep_commitment_hist(
                        self.commitment_hist, etype, unit
                    )
                    # First time through, set initial status from the unit's starting initial_status
                    if self.commitment_hist[etype][unit]["initial_status"] is None:
                        # Get initial status from unit dictionary
                        unit_initial_status = u_dict["initial_status"]
                        self.commitment_hist[etype][unit]["initial_status"] = unit_initial_status
                    # Get current and new values
                    commit_values_hist = self.commitment_hist[etype][unit]["commitment"]["values"]
                    if merge_dict is None:
                        if "commitment" in u_dict.keys():
                            commit_values_new = u_dict["commitment"]["values"]
                        else:  # If missing, Egret accepts the None input for unfixed
                            commit_values_new = [None] * len(commit_times_new)
                    else:
                        commit_values_new = merge_dict[etype][unit]["commitment"]["values"]
                    # Join values, handling overlap with the keep parameter ('new' or 'old')
                    if keep == "new":
                        # Keep only values that aren't in the overlap with old values
                        # Find indices that are not in the overlap
                        hist_indices = [
                            j for j in range(len(commit_values_hist)) if j not in i_hist
                        ]
                        commit_values_hist = [commit_values_hist[j] for j in hist_indices]
                    else:
                        # Keep only values from new that aren't in the overlap
                        new_indices = [j for j in range(len(commit_values_new)) if j not in i_new]
                        commit_values_new = [commit_values_new[j] for j in new_indices]
                    commit_values_all = commit_values_hist.extend(commit_values_new)
                    # This ensures that times are strictly ascending (ideally unnecessary)
                    # Sort the combined arrays to ensure times are in order
                    commit_times_all_sort, commit_values_all_sort = sort_array(
                        commit_times_all, commit_values_all
                    )
                    # Set commitment values
                    # Store the sorted commitment values in history
                    target_path = self.commitment_hist[etype][unit]["commitment"]
                    target_path["values"] = commit_values_all_sort
        self.commitment_hist["timestamps"] = sorted(commit_times_all)


def sort_array(ref_array, paired_array):
    """
    Takes two arrays and sorts both based on the values in the reference array.

    Args:
        ref_array: Reference array used for sorting order
        paired_array: Array to be sorted in the same order as the reference

    Returns:
        Tuple of (sorted_reference_array, sorted_paired_array)
    """
    # If inputs are lists instead of arrays, covert to lists before return
    return_list = False
    if isinstance(ref_array, list):
        return_list = True
    sorted_inds = np.argsort(ref_array)
    sorted_ref_array = np.array(ref_array)[sorted_inds]
    sorted_paired_array = np.array(paired_array)[sorted_inds]
    if return_list:
        sorted_ref_array = sorted_ref_array.tolist()
        sorted_paired_array = sorted_paired_array.tolist()
        # Convert any numpy.int64/float64 to int/float
        # Convert numpy types to native Python types
        sorted_paired_array = [
            int(cvh) if isinstance(cvh, int) else float(cvh) if isinstance(cvh, float) else cvh
            for cvh in sorted_paired_array
        ]
    return sorted_ref_array, sorted_paired_array

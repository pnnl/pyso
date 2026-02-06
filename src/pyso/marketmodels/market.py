"""
Created on 06/28/2024

Class market objects in Egret

This assumes EGRET functionality has been implemented as class functions that
can be called as methods. (This may not be a hard assumption.)


@author: Trevor Hardy
trevor.hardy@pnnl.gov
"""

import abc
import os
from collections import deque
from copy import deepcopy
from typing import Union

import numpy as np
import pandas as pd
from transitions import Machine

from pyso.engine import EnergyMarket
from pyso.utils.ioutils import Logger, merge_dicts


class MarketTiming:
    """Class that defines the timing of various market states"""

    def __init__(
        self,
        market_interval: Union[pd.Timedelta, int],
        timing: list[dict],
        time_unit="hour",
        initial_offset=0,
        **kwargs,
    ):
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

        self.time_unit = time_unit
        self.intial_offset = self.ensure_timedelta(initial_offset)
        self.market_interval = self.ensure_timedelta(market_interval)
        self.timing = deepcopy(timing)

        ## calculate duration
        for i, d in enumerate(reversed(self.timing)):
            # ensure timedelta
            d["start_time"] = self.ensure_timedelta(d["start_time"], unit=d.get("unit", ""))
            if i == 0:
                d["duration"] = self.market_interval - d["start_time"]
            else:
                d["duration"] = self.timing[-i]["start_time"] - d["start_time"]

        self.validate()

    def ensure_timedelta(self, v: Union[int, pd.Timedelta], unit: str = "") -> pd.Timedelta:
        if isinstance(v, pd.Timedelta):
            return v
        else:
            if not unit:
                unit = self.time_unit
            return pd.Timedelta(v, unit=unit)

    @property
    def state_list(self) -> list[str]:
        return [d["name"] for d in self.timing]

    def __getitem__(self, index: Union[int, str]) -> dict:
        """return the timing dictionary for a particular state

        Args:
            index (Union[int, str]): if int, the order of the state.
                                     if str, the name of the state.

        Returns:
            dict: the state timing dictionary
        """
        if isinstance(index, str):
            index = self.state_list.index(index)
        return self.timing[index]

    def validate(self):
        ## first state must start at time 0
        if self[0]["start_time"] != pd.Timedelta(0):
            raise ValueError(f"The start time for the first state {self[0]['name']} must be 0.")

        ## no start time greater than the market interval
        for s in self.state_list:
            if self[s]["start_time"] >= self.market_interval:
                raise ValueError(
                    f"Start time for state {s} is {self[s]['start_time']} which is >= the market interval of {self.market_interval}."
                )


class AbstractMarket(abc.ABC):
    """

    Abstract market class to handle various market phases using
    a state machine.

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

    def __init__(
        self,
        market_name: str,
        market_timing: Union[MarketTiming, dict],
        start_time: Union[pd.Timestamp, str],
        end_time: Union[pd.Timestamp, str],
        market: EnergyMarket,
        logging=None,
        history_maxlen=10,
        **kwargs,
    ):
        """Initializes a market object with state machine

        Args:
            market_name (str): name for the market (maily for logging etc.)
            market_timing (Union[MarketTiming, dict]): Market timing description of the states.
                Note that `bidding` and `clearing` are **assumed** to be states and have callbacks
                attached automatically.
            start_time (Union[pd.Timestamp,str]): The market iterates through time starting at this timestamp
            end_time (Union[pd.Timestamp,str]): When the next state time is this timestamp or greater, the market finalizes
            market (EnergyMarket): underlying EnergyMarket instance to solve the market.
            logging (dict, optional): logging settings. Defaults to {}.
            history_maxlen (int, optional): maximum length of state history queue. Defaults to 10.
        """
        if logging is None:
            logging = {}
        self.logger = Logger(**merge_dicts({"name": "Market", "level": "WARNING"}, logging))
        self.em = market
        self.market_name = market_name
        self.market_timing = (
            market_timing
            if isinstance(market_timing, MarketTiming)
            else MarketTiming(**market_timing)
        )
        self.start_time = pd.Timestamp(start_time)
        self.end_time = pd.Timestamp(end_time)

        self.send_horizon_message = True  # Will send a message when timestamp is past the horizon
        self.market_results = None

        self.history = deque(maxlen=history_maxlen)
        self.add_state_machine()

        self._current_time = None

    @property
    def state_list(self) -> list[str]:
        return self.market_timing.state_list

    @property
    def current_time(self):
        """the current market time"""
        return self._current_time

    @current_time.setter
    def current_time(self, t: pd.Timestamp):
        """sets the current market time.
        If this time is equal to the next state time,
        the move is triggered.

        Args:
            t (pd.Timestamp): _description_
        """
        if self.current_time is not None:
            # check that we are moving forward (or staying in place)
            if t < self.current_time:
                raise ValueError(
                    f"Time must be monotonically increasing. Current time is {self.current_time} and received {t}."
                )
        self._current_time = t
        self.logger.debug(
            f"[current_time setter] setting current time to {t} | next_state_time = {self.next_state_time}"
        )
        while (not self.is_final) and (self.current_time >= self.next_state_time):
            self.logger.debug(f"[current_time setter] calling move_to_next_state at time {t}")
            self.move_to_next_state()

    def add_state_machine(self):
        """
        This creates and adds a transitions state machine object to the market.
        The state machine calls callback functions that act the market moves from
        state to state.

        Relies on self.market_timing.timing that provides the state order and duration.
        (note duration is calculated internally by the MarketTiming class).
        """

        # Set up all of the time tracking object
        # self.timestep = 0
        # self.current_start_time = self.start_times[self.timestep]
        # self.current_state = "initialization"
        self.last_state = None
        # self.last_state_time = 0
        self.next_state_time = self.start_time
        # Add the state machine
        self.state_machine = Machine(
            model=self,
            states=["initialization", {"name": "finalization", "final": True}] + self.state_list,
            initial="initialization",
            send_event=True,
            before_state_change="track_state",
            after_state_change="update_market",
        )
        # create ordered transitions between the market states (excludes initialization and finalization)
        self.state_machine.add_ordered_transitions(self.state_list)

        # add a transition from initialization to the first state
        self.state_machine.add_transition(
            trigger="initialize", source="initialization", dest=self.state_list[0]
        )

        # add a transition to the final state
        self.state_machine.add_transition(
            trigger="finalize", source=self.state_list, dest="finalization"
        )

        ## specify the initialization callback
        self.state_machine.on_exit_initialization("do_initialization")
        ## specify the finalization callback
        self.state_machine.on_enter_finalization("do_finalization")

        ## specify market stages callbacks
        self.state_machine.on_enter_bidding("collect_bids")
        self.state_machine.on_enter_clearing("clear_market")
        self.state_machine.on_exit_clearing("publish_results")

    @property
    def current_state(self) -> str:
        """returns the current state machine state"""
        return self.state

    @property
    def is_final(self) -> bool:
        """Returns True if the model is in the `finalization` state."""
        return self.state_machine.get_state(self.state).final

    def track_state(self, event):
        """This method is called *before* every transition is executed.
        it is used to track/update the state history
        """
        self.history.appendleft(
            {
                "time": self.current_time,
                "source": event.transition.source,
                "dest": event.transition.dest,
            }
        )
        self.logger.debug(f"[track_state] {self.market_name} latest transition: {self.history[0]}")

    @abc.abstractmethod
    def do_initialization(self, *args, **kwargs) -> None:
        """This method executes any necessary initialization steps"""
        pass

    @abc.abstractmethod
    def do_finalization(self, *args, **kwargs) -> None:
        """This method executes at the end of the simulation, and can capture
        any necessary finalization steps.
        """
        pass

    def move_to_next_state(self, *args, **kwargs) -> str:
        """
        Transitions to the next state in the state machine and updates
        appropriate object parameters.
        The ability to pass arguments and kwargs to the callbacks is not currently implemented.
        """
        # Store previous state, move states, then update current state
        # Note: transitions automatically execute methods specified in add_state_machine
        self.last_state = self.current_state
        if self.current_state == "initialization":
            ## just getting started, do intialization
            self.logger.debug(
                f"[move_to_next_state] calling initialization callback at time {self.current_time}"
            )
            self.initialize()
        elif self.next_state_time >= self.end_time:
            ## reached the end, finalize
            self.logger.debug(
                f"[move_to_next_state] calling finalization callback at time {self.current_time}"
            )
            self.finalize()
        else:
            ## next state will call any state specific callbacks.
            ## it also calls the transition callback which is update_market.
            self.logger.debug(
                f"[move_to_next_state] calling next_state callback at time {self.current_time}"
            )
            self.next_state()
        # self.current_state = self.state
        # self.logger.info(f"[move_to_next_state]{self.market_name} moved from {self.last_state} to {self.current_state}")
        return self.current_state

    def update_market(self, event):
        """
        This method drives the state machine which drives all the other
        functionality via callbacks.

        An earlier version of this received the simulation time and checked
        to see if it was time to move to the next market state. For now
        that check is done by the instantiating object and it is assumed
        when this method is called, it's time to move to the next state
        """

        if not self.is_final:
            # update the time for the next state
            self.next_state_time += self.market_timing[self.current_state].get(
                "duration", pd.Timedelta(0)
            )
            self.logger.debug(
                f"[update_market] {self.market_name} next state time is {self.next_state_time}. Current time is {self.current_time}"
            )

    def market_loop(self, res: Union[pd.Timedelta, None] = None):
        """Loop of the time instances of the market, beginning with
        start_time until the finalization state is reached.
        If res is None, the loop will move directly to the next state time.
        If res is provided as a pandas Timedelta object, the loop will progress
        with this resolution.

        A simple market can run with
        ```
        for t in market.market_loop():
            market.current_time = t
        ```

        Args:
            res (Union[pd.Timedelta,None], optional): time loop resolution. Defaults to None.

        Yields:
            pd.Timestamp: the next time in the loop.
        """
        t0 = self.start_time
        while not self.is_final:
            if res is None:
                yield t0
                t0 = self.next_state_time
            else:
                yield t0
                t0 += res

    @abc.abstractmethod
    def collect_bids(self, event):
        """
        Callback method to pull in data.
        """
        pass

    @abc.abstractmethod
    def publish_results(self, event):
        """
        Method to publish results at the end of the clearing state.
        """
        pass

    @abc.abstractmethod
    def clear_market(self, event):
        """
        Callback method to clear a market in EGRET.
        This is usually the method to call the solve method
        of the attached EnergyMarket.
        """
        pass


class BasicMarket(AbstractMarket):
    def __init__(
        self,
        market_name: str,
        market_timing: Union[MarketTiming, dict],
        start_time: Union[pd.Timestamp, str],
        end_time: Union[pd.Timestamp, str],
        market: EnergyMarket,
        local_save=None,
        logging=None,
        history_maxlen=10,
        **kwargs,
    ):
        if logging is None:
            logging = {}
        if local_save is None:
            local_save = {}
        super().__init__(
            market_name,
            market_timing,
            start_time,
            end_time,
            market,
            logging,
            history_maxlen,
            **kwargs,
        )
        self.local_save = merge_dicts({"save": False, "path": "", "ext": ".json.gz"}, local_save)

        self.market_clearing_counter = 0

        ## OLD PARAMETERS, CONSIDER REMOVING
        # Default settings for various user inputs
        self.commitment_hist = None
        self.storage_soc = None
        self.pre_simulation_days = None

    def do_initialization(self, *args, **kwargs):
        pass

    def do_finalization(self, *args, **kwargs):
        pass

    def collect_bids(self, event):
        """Initialize the model at the current time."""
        ## initialize model
        self.em.get_model(self.current_time)
        # Modifications to model before solve, depending on use-case
        self.em.update_initial_conditions(self.em.mdl_sol)

    def clear_market(self, event):
        """Solve the market model"""
        ## solve the model
        self.em.solve_model()
        self.market_results = self.em.mdl_sol

    def publish_results(self, event):
        """Save the results"""
        if self.local_save["save"]:
            self.em.save_model(
                os.path.join(
                    self.local_save["path"],
                    f"{self.market_name}_results_{self.market_clearing_counter}{self.local_save['ext']}",
                )
            )
        self.market_clearing_counter += 1

    ### THE METHODS BELOW ARE OLDER AND MAY NEED TO BE REMOVED.

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
                self.logger.info(f"{info_msg} Market will not be cleared")
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

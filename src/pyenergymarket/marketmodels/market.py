"""
Created on 06/28/2024

Class market objects in Egret

This assumes EGRET functionality has been implemented as class functions that 
can be called as methods. (This may not be a hard assumption.)


@author: Trevor Hardy
trevor.hardy@pnnl.gov
"""
import datetime as dt
import json
import logging
import pandas as pd
import numpy as np
import copy
import math

from transitions import Machine
from ..engine import EnergyMarket
from ..utils.timeutils import count_onoff, mk_daterange

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.WARNING)

class Market():
    """

    For the off-shore-wind use case, we only need three market states so
    those will be hard-coded as below. The way this market works, all of 
    the activity of the market takes place at the transisitions. I'm 
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

    def __init__(self, market_name, market_timing, start_date, end_date, market:EnergyMarket=None, **kwargs):
        """
        Generic version of all the markets used in the E-COMP LDRD intiative.
        As such, this is fairly particular to those needs and is 
        correspondingly simple. When update_market is called, the market
        state machine moves to the next state and the time for the next
        market transition is called. This is all just logistics for running
        the market.

        The real magic of this happens when you sub-class this and add in
        callback methods that are called when entering particular states.
        
        """
        self.em = market # EnergyMarket object
        self.market_name = market_name # String for tracking the name
        self.market_timing = market_timing
        self.start_times = self.interpolate_market_start_times(start_date, end_date)
        logger.info("osw_market", self.market_name, "start_times: ", self.start_times)

        # Adds the state machine from the transitions library to track time
        self.add_state_machine(market_timing)
        # Initialize other internal variables
        self.send_horizon_message = True  # Will send a message when timestamp is past the horizon
        self.commitment_hist = None
        self.storage_soc = None
        self.pre_simulation_days = None
        self.market_results = None

        # This translates all the kwarg key-value pairs into class attributes
        self.__dict__.update(kwargs)

    def interpolate_market_start_times(self, start_date, end_date, freq='24h', start_time=' 00:00:00'):
        """Interpolates 24 (by default) hourly data between two date strings."""

        # Convert strings to datetime objects
        start_datetime = pd.to_datetime(start_date + start_time)
        end_datetime = pd.to_datetime(end_date + start_time)

        # Generate hourly datetime index
        start_time_index = pd.date_range(start_datetime, end_datetime, freq=freq, inclusive='left')
        return start_time_index

    def add_state_machine(self):
        """
        This creates and adds a transitions state machine object to the market.
        The state machine handles timing checks and transitions.

        Relies on the self.market_timing dict (an input argument for __init__)
        This dictionary provides the different state information, including start times and
        durations (in seconds). Format example is given below:

            {
            "states": {
                "idle": {
                    "start_time": 0,
                    "duration": 42660
                },
                "bidding": {
                    "start_time": 42660,
                    "duration": 540
                },
                "clearing": {
                    "start_time": 43200,
                    "duration": 43200
                },
            },
            "initial_offset": 0, <- how many seconds into the interval to start (0=start of interval)
            "initial_state": "idle", <- initial state (should match initial offset)
            "market_interval": 86400 <- total length of interval (must equal sum of all durations)
        }
        """
        # Check that market timing dictionary fits expected format
        self.validate_market_timing(self.market_timing)
        # Set up all of the time tracking object
        self.timestep = 0
        self.current_start_time = self.start_times[self.timestep]
        self.current_state = self.market_timing["initial_state"]
        self.last_state = None
        self.last_state_time = 0
        self.next_state_time = 0
        # Add the state machine
        self.state_list = list(market_timing["states"].keys())
        self.state_machine = Machine(model=self, states=self.state_list, initial=self.current_state)
        self.state_machine.add_ordered_transitions()
        # Adding definitions for state transition callbacks
        # These are automatically executed on state transitions
        self.state_machine.on_enter_bidding("collect_bids")
        self.state_machine.on_enter_clearing("clear_market")

    def collect_bids(self):
        """
        Callback method that pulls in generator bids

        This method must be overloaded in an instance of this class to
        implement the necessary operations to update the market in question.
        """
        pass

    def clear_market(self, local_save=False):
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
        self.em.update_initial_conditions(self.em.mdl_sol)
        self.em.solve_model()
        if local_save:
            self.em.save_model(f'data/{self.market_name}_results_{self.timestep}.json')
        self.market_results = self.em.mdl_sol
        self.update_commitment_hist()
        self.timestep += 1
        if self.timestep >= len(self.start_times):
            # Add a day (exact value doesn't matter, just need something past the horizon)
            self.current_start_time += dt.timedelta(days=1)
        else:
            self.current_start_time = self.start_times[self.timestep]
        logger.info("Market ", self.market_name, "next start time: ", self.current_start_time)

    def store_commitment_hist(self, keep='new', merge_dict=None):
        """
        Updates the commitment and initial status of generators (and storage) based on the
        model solution from a cleared market. Stored in the self.commitment_hist dictionary
        This is a partial copy of the Egret generator element dictionary, specifically designed
        to hold and update commitment history (and initial status) as markets pass

        Note - there is a case for merging entire egret models (rather than just commitment history),
        although there is the chance for conflicts if settings change and the overall size is larger (though
        probably not large enough to cause RAM issues, so maybe that doesn't matter)
        Option - this type of method could also be generalized to merge particular time series, although
        some special handling may still be needed.

        Args:
            keep (string): In the case of duplicate timestamps whether to keep 'new' or 'old' values. Defaults to new.
            merge_dict (dict): Option to merge a commitment history (typically merging DA into RT). Defaults to None.
                               Note, if merge_dict is specified, Egret model will be ignored. Keep='new' will use
                               the merge_dict values in case of duplicate timestamps.
        """
        assert keep in ['new', 'old'], f"keep must be either 'new' or 'old', not {keep}"
        # Create dict if needed with the timestamps as a top level key (shared by all generators/elements)
        if self.commitment_hist is None:
            self.commitment_hist = {'timestamps':[]}
        # Keep a copy of the old and the new timestamps
        commit_times_hist = self.commitment_hist['timestamps']
        if merge_dict is None:
            commit_times_new = pd.to_datetime(self.em.mdl_sol.data['system']['time_keys'])
        else:
            commit_times_new = merge_dict['timestamps']
        # Check whether to loop over stored PyEnergyMarket Model or an input model dictionary
        if merge_dict is None:
            loop_dict = self.em.mdl_sol.data['elements']
        else:
            loop_dict = merge_dict
        for etype, e_dict in loop_dict.items():
            # etype is 'generator', 'renewable', 'load', etc. - Egret types. e_dict holds each unit's info
            # Restrict to committable elements (optional - slight speedup but risk of missing new types)
            if etype in ['generator']:
                for unit, u_dict in e_dict.items():
                    # Add empty key if it doesn't already exist. Structure matches Egret (with timestamps added)
                    self.commitment_hist = self._prep_commitment_hist(self.commitment_hist, etype, unit)
                    # First time through, set the initial status (this is fixed based on the starting initial_status)
                    if self.commitment_hist[etype][unit]['initial_status'] is None:
                        self.commitment_hist[etype][unit]['initial_status'] = u_dict['initial_status']
                    # Get current commitment_hist, then check for duplicate timestamps in the incoming solution
                    # This is expected for RT and for DA if using a lookahead window.
                    # We will use the new value (from the model) as the latest
                    # [Optional] Could clean this up with np.intersect1d or something
                    commit_values_hist = self.commitment_hist[etype][unit]['commitment']['values']
                    _commit_vals_hist = copy.copy(commit_values_hist)
                    if merge_dict is None:
                        if 'commitment' in u_dict.keys():
                            commit_values_new = u_dict['commitment']['values']
                        else: # If missing, Egret accepts the None input for unfixed
                            commit_values_new = [None] * len(commit_times_new)
                    else:
                        commit_values_new = merge_dict[etype][unit]['commitment']['values']
                    _commit_times_hist = copy.copy(commit_times_hist)
                    for i, timestamp in enumerate(commit_times_new):
                        if timestamp in _commit_times_hist:
                            if keep == 'new':
                                # Find the index of the previous value and overwrite it with the new value
                                hidx = _commit_times_hist.index(timestamp)
                                commit_values_hist[hidx] = commit_values_new[i]
                        else:
                            _commit_times_hist.append(timestamp)
                            commit_values_hist.append(commit_values_new[i])
                    # May be unnecessary, but ensuring that times are strictly ascending
                    sorted_inds = np.argsort(_commit_times_hist)
                    _commit_times_hist = list(np.array(_commit_times_hist)[sorted_inds])
                    commit_values_hist = list(np.array(commit_values_hist)[sorted_inds])
                    commit_values_hist = [int(cvh) for cvh in commit_values_hist] # Change to int instead of int64
                    # Set commitment values
                    self.commitment_hist[etype][unit]['commitment']['values'] = commit_values_hist
        self.commitment_hist['timestamps'] = _commit_times_hist

    @staticmethod
    def _prep_commitment_hist(commitment_dict, etype, unit):
        """
        Creates an empty dictionary structure for the commitment history for a given element and generator/unit

        Args:
            etype (str): Type of element ('generator', 'storage', etc.)
            unit (str): Name of unit (typical use case is Egret generator name)
        """
        if etype not in commitment_dict.keys():
            commitment_dict[etype] = {unit: {'initial_status': None,
                                             'commitment':
                                                  {'data_type': 'time_series',
                                                   'values': []}}}
        if unit not in commitment_dict[etype].keys():
            commitment_dict[etype][unit] = {'initial_status': None,
                                            'commitment':
                                                 {'data_type': 'time_series',
                                                  'values': []}}
        return commitment_dict

    def valid_time_horizon(self):
        """ Returns T if current start time is within the horizon, otherwise F """
        if self.current_start_time > max(self.start_times):
            if self.send_horizon_message:
                logger.info(f"Current start time {self.current_start_time} is past horizon {max(self.start_times)}; "
                            "Market will not be cleared")
                self.send_horizon_warning = False  # Only send warning once
            return False
        return True

    def validate_market_timing(self, market_timing) -> None:
        """
        Validate that the provided market timing. Specifically check:
         - "states" keyword is present all states have the "start_time" and "duration" keys
         - initial offset and initial state match
         - total durations from all states are equal to the market_interval keyword
        """
        if not isinstance(market_timing, dict):
            raise TypeError(f"Must submit market_timing as a dictionary, not {type(market_timing)}")
        # Ensure the market_timing dict has the necessary keys (extraneous keys aren't penalized)
        required_keys = ["states", "initial_offset", "initial_state", "market_interval"]
        if set(required_keys) <= set(market_timing.keys()):
            raise KeyError(f"Market timing dict must contain keys: {required_keys}. (Passed {market_timing.keys()})")
        # Ensure all states have the necessary keys (extraneous keys aren't penalized)
        required_state_keys = ["start_time", "duration"]
        for state, state_dict in market_timing["states"].items():
            if set(required_state_keys) <= set(state_dict.keys()):
                raise KeyError(f"Invalid keys for state {state}. All state dicts must contain keys: {required_state_keys}.")
        # Ensure the starting state is specified (0 start time)
        current_state = [state for state in market_timing["states"].keys() if state["start_time"] == 0]
        if len(start_state) != 1:
            raise ValueError(f"Must include one and only one state with the start time of 0")
        else:
            current_state = current_state[0] # get key/string
        # Check that start times and durations are all consistent
        start_times = [state['start_time'] for state in market_timing["states"].keys()]
        current_time = 0
        for change_idx in range(len(start_times)-1):
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
        # Finally, check if the total duration (which will be 'next_start' from the above loop) equals the market_interval
        if not math.isclose(next_start, market_timing["market_interval"]):
            raise ValueError(f"Total state durations of {next_start} do not match market_interval of {market_timing['market_interval']}")

    def reset_timestep(self, timestep=0, shift_commitment=True):
        """ Resets the timestep to 0 (option to fix to a different value)
            This also sends the commitment history backward by the number
            of timesteps.

        Args:
            timestep (int): Specifies the timestep after the reset
            shift_commitment (bool): Option to also shift the commitment history times back by the
                                     start/stop time difference. This behavior is intended to support
                                     pre-simulation runs in which the commitments happened in the past
        """
        self.timestep = timestep
        self.current_start_time = self.start_times[self.timestep] # Also reset current start time
        if shift_commitment:
            # Compute the time to shift as the difference between the
            start_time = self.start_times[0]
            commitment_end_time = self.commitment_hist['timestamps'][-1]
            # We also add the interval for day-ahead since the end time is not inclusive of the last time step
            if 'day_ahead' in self.market_name.lower():
                interval = commitment_end_time - self.commitment_hist['timestamps'][-2]
                commitment_end_time += interval
            time_shift = commitment_end_time - start_time
            for i in range(len(self.commitment_hist['timestamps'])):
                self.commitment_hist['timestamps'][i] -= time_shift

    def move_to_next_state(self, *args, **kwargs) -> str:
        """
        Transitions to the next state in the state machine and updates
        appropriate object parameters.
        Input arguments and kwargs can be provided for the function call to the next state
        """
        # Store previous state, move states, then update current state
        # Note, transitions will automatically execute a method if specified in 'add_state_machine' method
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
        self.next_state_time = self.market_timing["states"][self.current_state]["duration"] \
                            + last_state_time \
                            + self.market_timing["initial_offset"]
       
        # Initial offset only matters on the first pass (and is included above). After, set to 0 for correct timing
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
        return next_state_time # current time
    

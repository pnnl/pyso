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

from numba.cuda.cudaimpl import ptx_max_f4
from transitions import Machine
from ..engine import EnergyMarket
from ..utils.timeutils import count_onoff, mk_daterange, get_value_at_time
# from egret.model_library.extensions.pcm_acopf.tools.model_data_manipulation import add_load_curtail

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.WARNING)

class OSWMarket():
    """
    TODO: describe this class

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
        self.em = market
        self.market_name = market_name
        self.current_state = market_timing["initial_state"]
        self.start_times = self.interpolate_market_start_times(start_date, end_date)
        logger.info("osw_market", self.market_name, "start_times: ", self.start_times)
        self.timestep = 0
        self.current_start_time = self.start_times[self.timestep]
        self.last_state = None
        self.send_horizon_message = True # Will send a message when timestamp is past the horizon
        self.market_timing  = market_timing
        self.last_state_time = 0
        self.next_state_time = 0
        self.market_results = {}
        self.state_list = list(market_timing["states"].keys())

        self.osw_bids = {}
        
        self.state_machine = Machine(model=self, states=self.state_list, initial=self.current_state)
        self.state_machine.add_ordered_transitions()
        self.new_data = False # Whethere there is new data to be published to the federation
        # Adding definitions for state transition callbacks
        # "self.clear_market" is the name of the method called when entering
        # the "clearing" state
        # _e.g.:_ self.state_machine.on_enter_clearing("self.clear_market")
        self.state_machine.on_enter_bidding("collect_bids")
        self.state_machine.on_enter_clearing("clear_market")
        self.validate_market_timing(self.market_timing)
        self.commitment_hist = None
        self.storage_soc = None
        self.pre_simulation_days = None

        # This translates all the kwarg key-value pairs into class attributes
        self.__dict__.update(kwargs)

    def collect_bids(self):
        """
        Callback method that pulls in T2 bids to grid data.

        This method must be overloaded in an instance of this class to
        implement the necessary operations to update the market in question.
        # """

        print("BIDS COLLECTED", self.market_name, self.osw_bids)
        for key in self.osw_bids.keys():
            self.em.mdl.data['elements']['generator'][key] = self.osw_bids[key]

        # print(market, bid['time'], key, self.markets[f"{market}_energy_market"].em.mdl.data['elements']['generator'][key])

    def reset_timestep(self, timestep=0, shift_commitment=True):
        """ Resets the timestep to 0 (option to fix to a different value)
            This also sends the commitment history backward by the number
            of timesteps.
        """
        self.timestep = timestep
        self.current_start_time = self.start_times[self.timestep] # Also reset current start time
        # Option to also shift the commitment history times back by the
        # start/stop time difference. This behavior is intended to support
        # pre-simulation runs in which the commitments happened in the past
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

    # @staticmethod
    # def _prep_storage_soc(storage_dict, etype, unit):
    #     """
    #     Creates an empty dictionary structure for the commitment history for a given element and generator/unit
    #
    #     Args:
    #         etype (str): Type of element ('generator', 'storage', etc.)
    #         unit (str): Name of unit (typical use case is Egret generator name)
    #     """
    #     if etype not in commitment_dict.keys():
    #         commitment_dict[etype] = {unit: {'initial_status': None,
    #                                          'commitment':
    #                                              {'data_type': 'time_series',
    #                                               'values': []}}}
    #     if unit not in commitment_dict[etype].keys():
    #         commitment_dict[etype][unit] = {'initial_status': None,
    #                                         'commitment':
    #                                             {'data_type': 'time_series',
    #                                              'values': []}}
    #     return commitment_dict

    def store_commitment_hist(self, keep='new', merge_dict=None):
        """
        Updates the commitment and initial status of generators (and storage) based on the
        model solution from a cleared market. Stored in the self.commitment_hist dictionary
        This is a partial copy of the Egret generator element dictionary, specifically designed
        to hold and update commitment history (and initial status) as markets pass

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

    def apply_contingencies(self, contingency_list=None, scale_branch_list=['4202_4203_1'],
                            scale_ratio=1.2):
        """ If including contingencies, turn off unused branches """
        # Apply contingencies: mark specified branches out of service
        if contingency_list:
            branches = self.em.mdl.data['elements']['branch']
            dc_branches = self.em.mdl.data['elements']['dc_branch']
            for br in contingency_list:
                if br in branches:
                    branches[br]['in_service'] = False
                    logger.info(f"Applied contingency: set {br}.in_service = False")
                elif br in dc_branches:
                    dc_branches[br]['in_service'] = False
                    logger.info(f"Applied contingency: set {br}.in_service = False to dc_branch")
                else:
                    logger.warning(f"Contingency branch '{br}' not found in model")

        # Scale rating parameters for specified branches by scale_ratio
        if scale_branch_list and scale_ratio != 1.0:
            branches = self.em.mdl.data['elements']['branch']
            # Parameters that should be scaled
            parameters = [
                'rating_long_term',
                'rating_short_term',
                'winter_a',
                'winter_c',
                'summer_a',
                'summer_c'
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
                            logger.warning(
                                f"Parameter '{param}' not found in branch '{br}'"
                            )
                else:
                    # Warn if the branch isn't found
                    logger.warning(
                        f"Branch '{br}' not found; cannot scale parameters"
                    )
        # Egret script to add a generator at each node at load curtailment cost (ensures feasibility)
        # add_load_curtail(self.em.mdl)

    def restore_lines(self):
        """ Egret removes lines with in_service set to False. We will add them back in here,
            setting the pf (power flow) values to zero
        """
        line_types = ['branch', 'dc_branch']
        for line_type in line_types:
            # Loop through the input model branches
            for branch, branch_dict in self.em.mdl.data['elements'][line_type].items():
                # Look for out-of-service lines
                if not branch_dict['in_service']:
                    mdl_sol_dict = self.em.mdl_sol.data['elements'][line_type]
                    # Double-check that the branch isn't already in the model solution
                    if branch in mdl_sol_dict.keys():
                        continue
                    # Add a copy of the model dict with this branch
                    mdl_sol_dict[branch] = copy.deepcopy(branch_dict)
                    # Set power flow == 0
                    empty_list = [0.0 for i in range(len(self.em.mdl.data['system']['time_keys']))]
                    if 'pf' in mdl_sol_dict[branch].keys():
                        mdl_sol_dict[branch]['pf']['values'] = empty_list
                    else:
                        mdl_sol_dict[branch]['pf'] = {'data_type': 'time_series',
                                                      'values': empty_list}
                    # Also add no pf_violation
                    mdl_sol_dict[branch]['pf_violation'] = {'data_type': 'time_series',
                                                            'values': empty_list}


    def store_storage_soc(self, max_intervals:int=24):
        """
        Saves the storage state-of-charge at the corresponding times. This could possible be merged into a
        common function with store_commitment_hist that accepts element type and keys, but that may be hard
        to get correct for general cases.

        Args:
            max_intervals (int): The maximum number of time intervals to save (default is 24, assuming hourly DA)
        """
        # If no storage units are in the model, don't continue
        if 'storage' not in self.em.mdl_sol.data['elements'].keys():
            return
        # Time keys - we pad the last interval since Egret gives soc values at END of interval while keys are START
        time_keys = pd.to_datetime(self.em.mdl_sol.data['system']['time_keys'])[:max_intervals]
        time_delta_end_minutes = int((time_keys[-1] - time_keys[-2]).total_seconds() / 60.0)
        time_keys = time_keys.append(pd.to_datetime([time_keys[-1] + dt.timedelta(minutes=time_delta_end_minutes)]))
        # Create dict if needed with the timestamps as a top level key (shared by all storage units)
        use_soc_init = False
        if self.storage_soc is None:
            self.storage_soc = {'timestamps': time_keys, 'storage': {}}
            # The first time through we use soc init (all other times it is same as last of previous)
            use_soc_init = True
        else:
            # Don't copy the first interval (it was added last time by the end padding)
            self.storage_soc['timestamps'] = self.storage_soc['timestamps'].append(time_keys[1:])
        # loop through storage units
        for storage, storage_dict in self.em.mdl_sol.data['elements']['storage'].items():
            soc_values = storage_dict['state_of_charge']['values'][:max_intervals]
            if use_soc_init:
                soc_init = storage_dict['initial_state_of_charge']
                soc_values = np.append(np.array([soc_init]), soc_values)
            # If previous values are in the storage dictionary, we will append new values to the end
            if storage in self.storage_soc['storage'].keys():
                prev_soc_values = self.storage_soc['storage'][storage]['state_of_charge']['values']
                soc_values = np.append(prev_soc_values, soc_values)
            self.storage_soc['storage'][storage] = {'state_of_charge': {'data_type': 'time_series',
                                                                        'values': soc_values}}

    def valid_time_horizon(self):
        """ Returns T if current start time is within the horizon, otherwise F """
        if self.current_start_time > max(self.start_times):
            if self.send_horizon_message:
                logger.info(f"Current start time {self.current_start_time} is past horizon {max(self.start_times)}; "
                            "Market will not be cleared")
                self.send_horizon_warning = False  # Only send warning once
            return False
        return True

    def get_price_forecast(self):
        """ Runs a pricing instance with binaries relaxed to get price forecasts for market participants """
        if not self.valid_time_horizon():
            return
        # Get
        self.em.get_model(self.current_start_time)
        self.em.pricing_model("achp", use_mdl_sol=False)
        # TODO: load self.em.mdl_price results into a format that can be sent to each generator
        # we want to send the price corresponding to the generator bus(es).

    def clear_market(self, local_save=True, get_mdl=True, contingency_list=None):
        """
        Callback method that runs EGRET and clears a market.

        This method must be overloaded in an instance of this class to
        implement the necessary operates to clear the market in question.

        Args:
            local_save (bool, optional): if True, will save a JSON with the results at each timestep
            get_mdl (bool, optional): if True, will get Egret model from parser (otherwise uses existing mdl)
        """
        # Don't run market if this start time exceeds the start time list
        if not self.valid_time_horizon():
            return

        if get_mdl:
            self.em.get_model(self.current_start_time)

        self.collect_bids() 
        for g in self.em.mdl.data['elements']['generator']:
            print(self.market_name, g)

        self.em.mdl.write(f'data/{self.market_name}_model_{self.timestep}.json')
        # Modifications to model before solve, depending on use-case
        self.apply_contingencies(contingency_list=contingency_list)
        self.em.solve_model()
        # Put back in_service=False branches (these are removed by default in Egret solution)
        self.restore_lines()
        if local_save:
            self.em.save_model(f'data/{self.market_name}_results_{self.timestep}.json')
        self.market_results = self.em.mdl_sol
        self.store_commitment_hist()
        self.store_storage_soc() # Note this is intended for DA only right now - RT uses DA values
        self.timestep += 1
        if self.timestep >= len(self.start_times):
            # Add a day (exact value doesn't matter, just need something past the horizon)
            self.current_start_time += dt.timedelta(days=1)
        else:
            self.current_start_time = self.start_times[self.timestep]
        logger.info("OSW ", self.market_name, "next start time: ", self.current_start_time)

    def validate_market_timing(self, market_timing) -> None:
        """
        Validate that the provided market timing is self-consistent.
        """
        pass
    
    def move_to_next_state(self) -> str:
        """
        Transitions to the next state in the state machine and updates
        appropriate object parameters.
        """
        self.last_state = self.current_state
        self.next_state()
        # self.current_state = self.state_machine.state
        self.current_state = self.state
        logger.debug(self.market_name, "Last state:", self.last_state)
        logger.debug(self.market_name, "Next state:", self.current_state)
        logger.info(f"{self.market_name} moved from {self.last_state} to {self.current_state}")
        return self.current_state
        
    def calculate_next_state_time(self) -> tuple[float, float]:
        """
        Calculate the value of the next state in terms of simulation time
        based on the timing of the next state in the state machine.
        """
        last_state_time = self.last_state_time
        self.next_state_time = self.market_timing["states"][self.current_state]["duration"] \
                            + last_state_time \
                            + self.market_timing["initial_offset"]
       
        # Rather than checking to see if its zero before setting it to zero,
        # just set it to zero (even if it already was.) The only time this
        # needs to be non-zero is the first time we do the first transition
        self.market_timing["initial_offset"] = 0
        logger.info(f"{self.market_name}.next_state_time: {self.next_state_time}")
        return last_state_time, self.next_state_time
 

    def update_market(self):
        """
        This method drives the state machine which drives all the other
        functionality via callbacks.

        An earlier version of this received the simulation time and checked
        to see if it was time to move to the next market state. For now
        that check is done by the instantiating object and it is assumed
        when this method is called, it's time to move to the next state
        """
        _, self.last_state_time = self.calculate_next_state_time()
        return self.last_state_time # current time

    def interpolate_market_start_times(self, start_date, end_date, freq='24h', start_time=' 00:00:00'):
        """Interpolates 24 (by default) hourly data between two date strings."""

        # Convert strings to datetime objects
        start_datetime = pd.to_datetime(start_date + start_time)
        end_datetime = pd.to_datetime(end_date + start_time)

        # Generate hourly datetime index
        start_time_index = pd.date_range(start_datetime, end_datetime, freq=freq, inclusive='left')
        return start_time_index

    def update_initial_status(self, gen:str, min_freq:int, return_commit:bool=False):
        """ Updates the initial status of the egret ModelData object for the given generator """
        # Load the commitment history and find the index corresponding to the current time
        commit_hist = self.commitment_hist['generator'][gen]
        if self.current_start_time in self.commitment_hist['timestamps']:
            t0idx = np.where(self.current_start_time == np.array(self.commitment_hist['timestamps']))[0][0]
        else:
            t0idx = len(self.commitment_hist['timestamps'])
        # If we are at the first point, we just use the 'initial_status' value for that generator
        if t0idx == 0:
            # If using day-ahead, update the initial status to ensure the units can meet commitments
            gen_dict = self.em.mdl.data['elements']['generator'][gen]
            initial_status = gen_dict['initial_status']
            self.em.mdl.data['elements']['generator'][gen]['initial_status'] = initial_status
        # Otherwise we look at all the intervals before t0idx (excluding current interval) to get initial_status
        else:
            # Function to find initial status (number of hours the unit has been on or off)
            self.em.mdl.data['elements']['generator'][gen]['initial_status'] = (
                count_onoff(commit_hist, t0idx - 1, min_freq=min_freq))
        # Option to return commitment history and starting commitment index (used in RT market)
        if return_commit:
            return commit_hist, t0idx

    def update_state_of_charge(self, storage, market_type='day_ahead'):
        """
        Updates the state of charge in the egret ModelData object for the given storage
        Two situations:
            market_type = 'day_ahead' populates init_state_of_charge from the end of the previous solution
                           and sends end_state_of_charge = init_state_of_charge
            market_type = 'real_time' populates initial state of charge based on self.storage_soc (saved from DA)
                          at the current time and end_state_of_charge at the end of the window + lookahead
        """
        if market_type == 'day_ahead':
            # If no solution exists (first time) just use whatever is already in the input model
            if self.em.mdl_sol is None:
                return
            # Use soc and end of window (these are the values saved, excluding lookahead)
            window = self.em.configuration["time"]["window"]
            self.em.mdl.data['elements']['storage'][storage]['initial_state_of_charge'] \
                = self.em.mdl_sol.data['elements']['storage'][storage]['state_of_charge']['values'][window-1]
            self.em.mdl.data['elements']['storage'][storage]['end_state_of_charge'] \
                = self.em.mdl.data['elements']['storage'][storage]['initial_state_of_charge']
        elif market_type == 'real_time':
            # If no saved storage, we have no reference to use
            if self.storage_soc is None:
                return
            # Initial soc is the self.storage_soc at current time (which may require interpolation)
            # We restrict to the last 48 intervals (assumes soc is stored hourly, which is true at time of creation)
            limit = 48
            da_soc_series = self.storage_soc['storage'][storage]['state_of_charge']['values'][-limit:]
            da_time_keys = self.storage_soc['timestamps'][-limit:]
            lookup_init_soc = get_value_at_time(da_soc_series, da_time_keys, self.current_start_time)
            # Bound soc on interval [0, 1]
            lookup_init_soc = min(1, max(0, lookup_init_soc))
            self.em.mdl.data['elements']['storage'][storage]['initial_state_of_charge'] = lookup_init_soc
            # For end soc we use the same da series and time keys, but find end interval time
            periods = self.em.configuration["time"]["window"] + self.em.configuration["time"]["lookahead"]
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
                self.em.mdl.data['elements']['storage'][storage]['end_state_of_charge'] = lookup_end_soc
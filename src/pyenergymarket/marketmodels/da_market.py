"""
Created on 06/28/2024

Class market objects in Egret

This assumes EGRET functionality has been implemented as class functions that 
can be called as methods. (This may not be a hard assumption.)


@author: Trevor Hardy
trevor.hardy@pnnl.gov
"""
import datetime
import logging
from .market import Market
from .marketutils import convert_64, add_load_curtail
from ..utils.timeutils import mk_daterange, get_value_at_time
import numpy as np
import pandas as pd
import copy

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.WARNING)

class DAMarket(Market):
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

    def __init__(self, start_date, end_date, market_name:str="da_energy_market", market_timing:dict=None,
                 min_freq:int=60, window:int=24, lookahead:int=0, **kwargs):
        """
        Class the specifically runs the DA energy market

        The only specialization is the definition of the callback method
        that gets called when the market state machine enters the "clearing"
        state.
        """
        # if market_timing isn't specified input default vaules.
        if market_timing == None:
            market_timing = {
                "states": {
                    "idle": {
                        "start_time": 0,
                        "duration": 85800
                    },
                    "bidding": {
                        "start_time": 85800,
                        "duration": 540
                    },
                    "clearing": {
                        "start_time": 86340,
                        "duration": 60
                    },
                },
                "initial_offset": 0,
                "initial_state": "idle",
                "market_interval": 86400
            }
        super().__init__(market_name, market_timing, start_date, end_date, **kwargs)
        # These update the EnergyMarket defaults with specified arguments
        self.em.configuration["time"]["min_freq"] = min_freq
        self.em.configuration["time"]["window"] = window
        self.em.configuration["time"]["lookahead"] = lookahead
        # Arguments for adding new generators with bids
        self.bids = {}
        self.extra_gens = {}
        # This translates all the kwarg key-value pairs into class attributes
        self.__dict__.update(kwargs)

    def collect_bids(self):
        """ Overloaded method of Market: adding bids from generators and storage """
        elements = self.em.mdl.data['elements']
        for key in self.bids.keys():
            # Allow bids from both generators and storage. Search for name (key)
            element_types = ['generator', 'storage']
            for element_type in element_types:
                if element_type not in elements.keys():
                    continue
                if key in elements[element_type].keys():
                    elements[key] = self.bids[key]

    def add_gens(self):
        """ Adds generators, including full Egret model data information to the model.
            This will look for any generators in the self.extra_gens dictionary.
        """
        for g, gdict in self.extra_gens.items():
            self.em.mdl.data['elements']['generator'][g] = gdict

    def clear_market(self, local_save=False, contingency_list=None):
        """
        Overload of base clear_market.

        Args:
            local_save (bool, optional): if True, will save a JSON with the results at each timestep
            contingency_list (list, optional): if provided, will enforce line contingencies at certain times
        """
        # Don't run market if this start time exceeds the start time list
        if not self.valid_time_horizon():
            return

        self.em.get_model(self.current_start_time)
        # Modifications to model before solve, depending on use-case
        self.add_gens()
        self.em.update_initial_conditions(self.em.mdl_sol)
        if contingency_list is not None:
            self.apply_contingencies(contingency_list=contingency_list)
        self.em.mdl.write(f'data/{self.market_name}_model_{self.timestep}.json')
        self.em.solve_model()
        # Put back in_service=False branches (these are removed by default in Egret solution)
        self.restore_lines()
        if local_save:
            self.em.save_model(f'data/{self.market_name}_results_{self.timestep}.json')
        self.market_results = self.em.mdl_sol
        self.market_results.data = convert_64(self.market_results.data)
        self.store_commitment_hist(omit=['_load_curtail'])
        self.store_storage_soc()  # Note this is intended for DA only right now - RT uses DA values
        self.timestep += 1
        if self.timestep >= len(self.start_times):
            # Add a day (exact value doesn't matter, just need something past the horizon)
            self.current_start_time += datetime.timedelta(days=1)
        else:
            self.current_start_time = self.start_times[self.timestep]
        logger.info("Market ", self.market_name, "next start time: ", self.current_start_time)

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
        if shift_commitment and self.pre_simulation_days is not None:
            # Compute the time to shift as the difference between the
            start_time = self.start_times[0]
            commitment_end_time = self.commitment_hist['timestamps'][-1]
            # We also add the last interval for since the end time is not inclusive of the last time step
            interval = commitment_end_time - self.commitment_hist['timestamps'][-2]
            commitment_end_time += interval
            time_shift = (commitment_end_time - start_time)*self.pre_simulation_days
            for i in range(len(self.commitment_hist['timestamps'])):
                self.commitment_hist['timestamps'][i] -= time_shift
                # We also shift the state_of_charge
                self.storage_soc['system']['time_keys'][i] -= time_shift

    @staticmethod
    def prep_commitment_hist(commitment_dict, etype, unit):
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

    def store_commitment_hist(self, keep='new', merge_dict=None, omit=[]):
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
            omit (list): List of strings for generators to omit. This can be part of the name. For example:
                             omit = ['_w_new'] will omit any generators containing '_w_new' in their name
        """

        # Helper function to check if any omit strings are in the unit name
        def omit_unit(unit: str, omit: list):
            omit_status = False
            for om in omit:
                if om in unit:
                    omit_status = True
                    break
            return omit_status

        assert keep in ['new', 'old'], f"keep must be either 'new' or 'old', not {keep}"
        # Create dict if needed with the timestamps as a top level key (shared by all generators/elements)
        if self.commitment_hist is None:
            self.commitment_hist = {'timestamps': []}
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
                    if omit_unit(unit, omit):
                        continue  # Skip if unit name is in the omit list
                    # Add empty key if it doesn't already exist. Structure matches Egret (with timestamps added)
                    self.commitment_hist = self.prep_commitment_hist(self.commitment_hist, etype, unit)
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
                        else:  # If missing, Egret accepts the None input for unfixed
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
                    commit_values_hist = [int(cvh) if isinstance(cvh, int) else cvh for cvh in
                                          commit_values_hist]  # Change to int instead of int64
                    # Set commitment values
                    self.commitment_hist[etype][unit]['commitment']['values'] = commit_values_hist
        self.commitment_hist['timestamps'] = _commit_times_hist

    def store_storage_soc(self, max_intervals: int = 24):
        """
        Saves the storage state-of-charge at the corresponding times. This could possibly be merged into a
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
        time_keys = time_keys.append(
            pd.to_datetime([time_keys[-1] + datetime.timedelta(minutes=time_delta_end_minutes)]))
        # Create dict if needed with the timestamps as a top level key (shared by all storage units)
        use_soc_init = False
        if self.storage_soc is None:
            self.storage_soc = {'system': {'time_keys': time_keys}, 'elements': {'storage': {}}}
            # The first time through we use soc init (all other times it is same as last of previous)
            use_soc_init = True
        else:
            # Don't copy the first interval (it was added last time by the end padding)
            self.storage_soc['system']['time_keys'] = self.storage_soc['system']['time_keys'].append(time_keys[1:])
        # loop through storage units
        for storage, storage_dict in self.em.mdl_sol.data['elements']['storage'].items():
            soc_values = storage_dict['state_of_charge']['values'][:max_intervals]
            if use_soc_init:
                soc_init = storage_dict['initial_state_of_charge']
                soc_values = np.append(np.array([soc_init]), soc_values)
            # If previous values are in the storage dictionary, we will append new values to the end
            if storage in self.storage_soc['elements']['storage'].keys():
                prev_soc_values = self.storage_soc['elements']['storage'][storage]['state_of_charge']['values']
                soc_values = np.append(prev_soc_values, soc_values)
            self.storage_soc['elements']['storage'][storage] = {'state_of_charge': {'data_type': 'time_series',
                                                                                    'values': soc_values}}

    def update_state_of_charge(self, storage, market_type='day_ahead'):
        """
        Updates the state of charge in the egret ModelData object for the given storage
        Two situations:
            market_type = 'day_ahead' populates init_state_of_charge from the end of the previous solution
                           and sends end_state_of_charge = init_state_of_charge
            market_type = 'real_time' populates initial state of charge based on self.storage_soc (saved from DA)
                          at the current time and end_state_of_charge at the end of the window + lookahead
        """
        window = self.em.configuration["time"]["window"]
        if market_type == 'day_ahead':
            # If no solution exists (first time) just use whatever is already in the input model
            if self.em.mdl_sol is None:
                return
            # Use soc and end of window (these are the values saved, excluding lookahead)
            self.em.mdl.data['elements']['storage'][storage]['initial_state_of_charge'] \
                = self.em.mdl_sol.data['elements']['storage'][storage]['state_of_charge']['values'][window - 1]
            self.em.mdl.data['elements']['storage'][storage]['end_state_of_charge'] \
                = self.em.mdl.data['elements']['storage'][storage]['initial_state_of_charge']
        elif market_type == 'real_time':
            # If no saved storage, we have no reference to use
            if self.storage_soc is None:
                return
            # Initial soc is the self.storage_soc at current time (which may require interpolation)
            # We restrict to the last 48 intervals (assumes soc is stored hourly, which is true at time of creation)
            limit = 48
            da_soc_series = self.storage_soc['elements']['storage'][storage]['state_of_charge']['values'][-limit:]
            da_time_keys = self.storage_soc['system']['time_keys'][-limit:]
            # We get initial soc from the last RT interval, when available. Otherwise we lookup from DA value
            if self.em.mdl_sol is None:
                lookup_init_soc = get_value_at_time(da_soc_series, da_time_keys, self.current_start_time)
            else:
                lookup_init_soc \
                    = self.em.mdl_sol.data['elements']['storage'][storage]['state_of_charge']['values'][window - 1]
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

    def apply_contingencies(self, contingency_list=None, scale_branch_list=None,
                            scale_ratio=2):
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
        add_load_curtail(self.em.mdl)

    def restore_lines(self):
        """ Egret removes lines with in_service set to False. We will add them back in here,
            setting the pf (power flow) values to zero
        """
        line_types = ['branch', 'dc_branch']
        for line_type in line_types:
            if line_type not in self.em.mdl.data['elements'].keys():
                continue
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
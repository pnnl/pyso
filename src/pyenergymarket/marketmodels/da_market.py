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
from .market import Market

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
            self.current_start_time += dt.timedelta(days=1)
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
                self.storage_soc['timestamps'][i] -= time_shift

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
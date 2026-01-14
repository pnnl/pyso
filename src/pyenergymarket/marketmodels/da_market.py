"""
Class market objects in Egret

This assumes EGRET functionality has been implemented as class functions that
can be called as methods. (This may not be a hard assumption.)
"""
import copy
import datetime
import logging

import numpy as np
import pandas as pd

from ..utils.timeutils import get_value_at_time, mk_daterange
from .market import Market
from .marketutils import add_load_curtail, convert_64

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

    def __init__(
        self,
        start_date,
        end_date,
        market_name: str = "da_energy_market",
        market_timing: dict = None,
        min_freq: int = 60,
        window: int = 24,
        lookahead: int = 0,
        **kwargs,
    ):
        """
        Class the specifically runs the DA energy market

        The only specialization is the definition of the callback method
        that gets called when the market state machine enters the "clearing"
        state.
        """
        # if market_timing isn't specified input default values.
        if market_timing is None:
            market_timing = {
                "states": {
                    "idle": {"start_time": 0, "duration": 85800},
                    "bidding": {"start_time": 85800, "duration": 540},
                    "clearing": {"start_time": 86340, "duration": 60},
                },
                "initial_offset": 0,
                "initial_state": "idle",
                "market_interval": 86400,
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

    def clear_market(self, local_save=False, contingency_list=None):
        """
        Overload of base clear_market.

        Args:
            local_save (bool, optional): if True, will save a JSON with the results at each timestep
            contingency_list (list, optional): if provided, will enforce line contingencies
                at certain times
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
        self.em.mdl.write(f"data/{self.market_name}_model_{self.timestep}.json")
        self.em.solve_model()
        # Put back in_service=False branches (these are removed by default in Egret solution)
        self.restore_lines()
        if local_save:
            self.em.save_model(f"data/{self.market_name}_results_{self.timestep}.json")
        self.market_results = self.em.mdl_sol
        self.market_results.data = convert_64(self.market_results.data)
        self.store_commitment_hist(omit=["_load_curtail"])
        self.store_storage_soc()  # Note this is intended for DA only right now - RT uses DA values
        self.timestep += 1
        if self.timestep >= len(self.start_times):
            # Add a day (exact value doesn't matter, just need something past the horizon)
            self.current_start_time += datetime.timedelta(days=1)
        else:
            self.current_start_time = self.start_times[self.timestep]
        # Log the next market start time
        logger.info(f"Market {self.market_name} next start time: {self.current_start_time}")

    @staticmethod
    def prep_commitment_hist(commitment_dict, etype, unit):
        """
        Creates an empty dictionary structure for the commitment history
        for a given element and generator/unit

        Args:
            etype (str): Type of element ('generator', 'storage', etc.)
            unit (str): Name of unit (typical use case is Egret generator name)
        """
        if etype not in commitment_dict.keys():
            commitment_dict[etype] = {
                unit: {
                    "initial_status": None,
                    "commitment": {"data_type": "time_series", "values": []},
                }
            }
        if unit not in commitment_dict[etype].keys():
            commitment_dict[etype][unit] = {
                "initial_status": None,
                "commitment": {"data_type": "time_series", "values": []},
            }
        return commitment_dict

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
        # while keys are START
        time_keys = pd.to_datetime(self.em.mdl_sol.data["system"]["time_keys"])[:max_intervals]
        # Calculate time difference between last two intervals
        time_diff_seconds = (time_keys[-1] - time_keys[-2]).total_seconds()
        time_delta_end_minutes = int(time_diff_seconds / 60.0)
        # Append an additional time key at the end
        additional_time = time_keys[-1] + datetime.timedelta(minutes=time_delta_end_minutes)
        time_keys = time_keys.append(pd.to_datetime([additional_time]))
        # Create dict if needed with the timestamps as a top level key (shared by all storage units)
        use_soc_init = False
        # Check if storage state of charge tracking has been initialized
        if self.storage_soc is None:
            self.storage_soc = {"system": {"time_keys": time_keys}, "elements": {"storage": {}}}
            # The first time through we use soc init
            # (all other times it is same as last of previous)
            use_soc_init = True
        else:
            # Don't copy the first interval (it was added last time by the end padding)
            time_keys_from_prev = self.storage_soc["system"]["time_keys"]
            self.storage_soc["system"]["time_keys"] = time_keys_from_prev.append(time_keys[1:])
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
            # Get state of charge values and time keys with limit
            storage_path = self.storage_soc["elements"]["storage"][storage]["state_of_charge"]
            da_soc_series = storage_path["values"][-limit:]
            da_time_keys = self.storage_soc["system"]["time_keys"][-limit:]
            # We get initial soc from the last RT interval, when available. Otherwise lookup from DA
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
                            # Log scaling information with original and new values
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
        # (ensures feasibility)
        add_load_curtail(self.em.mdl)

    def restore_lines(self):
        """Egret removes lines with in_service set to False. We will add them back in here,
        setting the pf (power flow) values to zero
        """
        line_types = ["branch", "dc_branch"]
        for line_type in line_types:
            if line_type not in self.em.mdl.data["elements"].keys():
                continue
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
                    # Create an empty list with zeros matching the number of time intervals
                    num_time_keys = len(self.em.mdl.data["system"]["time_keys"])
                    empty_list = [0.0 for _ in range(num_time_keys)]
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

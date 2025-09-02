"""The core functionality of pyenergymarket, encapsulated in the 
EnergyMarket class is here.
"""
from .utils.ioutils import merge_configs, Logger
from .utils.timeutils import mk_daterange, count_onoff, get_value_at_time
from .utils.egretutils import NumpyEncoder
from .pyenergymarket_defaults import energymarket_defaults
import abc
from egret.data.model_data import ModelData
from egret.models.unit_commitment import solve_unit_commitment, SlackType
import pandas as pd
import numpy as np
from typing import Union
import copy

class DataProvider(abc.ABC):
    
    @abc.abstractmethod
    def get_model(self, daterange:pd.DatetimeIndex) -> ModelData:
        """Generate an Egret model based on the timeindex provided
         see also utils.timeutils.mk_daterange
        """
        pass

class EnergyMarket:
    def __init__(self, data_provider:DataProvider, config:dict=None, **kwargs):
        """Initalize the energy market wrapper

        Args:
            data_provider (_type_): an object with method get_model 
                    with inputs date_from, date_to that returns an egret model 
        """
        self.data_provider = data_provider
        self.mdl = None
        self.mdl_sol = None
        ### get configuration
        self.configuration = copy.deepcopy(energymarket_defaults)
        if config is not None:
            merge_configs(self.configuration, config)
        
        ### set up logger
        self.logger =Logger(**self.configuration["logging"])
        if self.configuration["logging"]["file"] is not None:
            self.logger.set_logfile(self.configuration["logging"]["file"])

    def set_property(self, value, *args, d=None):
        """set a property in the configuration dictionary.
        the arguments following `value` should be the keys in the dictionary 
        tree to the desired property to set 

        Args:
            value (Any): value to set
            *args: keys (in sequence) in the configuration dictionary to the location of the value to set

        Example:
            To set the price_model property to None,
            which is at self.configuration["simulation"]["price_model"] do

            self.set_property(None, "simulation", "price_model")
        """
        if d is None:
            d = self.configuration
        if len(args) == 1:
            d[args[0]] = value
        elif len(args) < 1:
            raise ValueError("EnergyMarket::set_property: the length of *args should never be less than 1.")
        else:
            self.set_property(value, *args[1:], d=d[args[0]])

    def get_model(self, start:Union[str, pd.Timestamp]):
        """form the Egret Model at start time

        Args:
            start (Union[str, pd.Timestamp]): time start time of the model
        """

        periods = self.configuration["time"]["window"] + self.configuration["time"]["lookahead"]
        min_freq = self.configuration["time"]["min_freq"]

        daterange = mk_daterange(start, min_freq=min_freq, periods=periods)

        # get the model for the specified time range 
        self.logger.info(f"Forming model starting at: {daterange[0]} - {daterange[-1]}")
        self.mdl = self.data_provider.get_model(daterange)

    def update_initial_conditions(self, mdl_sol:Union[ModelData, None]=None, update_mode:str='calculate',
                                  soc_reference:Union[ModelData, dict, None]=None):
        """ This function updates 'initial_p_output' and 'initial_status' for all
            generators in an Egret ModelData object. For the reference it will make a
            selection in this order:
            1. Use the mdl_sol input variable
            2. If mdl_sol is None, uses solution saved to EnergyMarket, self.mdl_sol
            3. If self.mdl_sol is None, will not make any updates

        Args:
            mdl_sol (Union[ModelData, None]): Egret ModelData with solutions, defaults to None
            update_mode (str): Choose how to update initial conditions.
                               copy - will use the same initial conditions as those in mdl_sol
                               calculate - will use the mdl_sol state at the end of the last window as initial conditions
            soc_reference (Union[ModelData, dict, None]): Reference state-of-charge targets.
                               Used only in computing the end_soc for 'calculate' mode.
                               These may be on a different time resolution than the current EnergyMarket model.
        """
        # Two different update modes (can add more as needed)
        update_options = ['calculate', 'copy']
        if update_mode not in update_options:
            raise ValueError(f"Invalid update_mode: {update_mode}, must be one of {update_options}")
        # The number of intervals between the start of the last model solve and the upcoming model solve:
        window = self.configuration["time"]["window"]
        # The duration in minutes of each interval:
        min_freq = self.configuration["time"]["min_freq"]

        # Select the appropriate previous model solution
        previous_mdl_sol = mdl_sol
        if previous_mdl_sol is None:
            # No need to proceed if no solutions are available
            if self.mdl_sol is None:
                return
            previous_mdl_sol = self.mdl_sol

        # Loop through all generators in the upcoming model (self.mdl) and update initial_p_output and initial_status
        for g, g_dict in self.mdl.elements(element_type='generator'):
            # When simulating multiple market instances, we may copy information from one market to another.
            # For example, we may want to pass day-ahead results to a real-time market.
            if update_mode == 'copy':
                g_dict['initial_p_output'] = float(
                    previous_mdl_sol.data['elements']['generator'][g]['initial_p_output'])
                g_dict['initial_status'] = float(previous_mdl_sol.data['elements']['generator'][g]['initial_status'])
            # In all other cases, we calculate initial conditions from the end of the previous cleared market.
            elif update_mode == 'calculate':
                # Initial power is the last power cleared in the previous window (subtract 1 to get on 0-base)
                g_dict['initial_p_output'] = float(
                    previous_mdl_sol.data['elements']['generator'][g]['pg']['values'][window - 1])
                # we could also update the q/reactive power, but this first test will be dc only
                # g_dict['initial_q_output'] = float(
                #                 previous_mdl_sol.data['elements']['generator'][g]['qg']['values'][window - 1])
                # Update initial status for this generator, using timeutils function
                new_initial_status = count_onoff(previous_mdl_sol.data['elements']['generator'][g], window-1, min_freq)
                g_dict['initial_status'] = new_initial_status

        # Loop through all storage units in the upcoming model (self.mdl) and update initial_state_of_charge,
        # end_state_of_charge, initial_charge_rate and initial_discharge_rate
        for storage, storage_dict in self.mdl.elements(element_type='storage'):
            # List of keys to update for storage with the max values (or a string for key of max value)
            update_maxes = {'initial_state_of_charge': 1, 'end_state_of_charge': 1}
            # When simulating multiple market instances, we may copy information from one market to another.
            # For example, we may want to pass day-ahead results to a real-time market.
            if update_mode == 'copy':
                for key, maxval in update_maxes.items():
                    if key in previous_mdl_sol.data['elements']['storage'][storage].keys():
                        storage_dict[key] = float(previous_mdl_sol.data['elements']['storage'][storage][key])
                        # Enforce maximum (avoids floating point roundoff errors causing constraint violations)
                        storage_dict[key] = min(storage_dict[key], maxval)
            elif update_mode == 'calculate':
                # Get the last value of the time window in the previous solution
                previous_soc = previous_mdl_sol.data['elements']['storage'][storage]['state_of_charge']['values'][window - 1]
                storage_dict['initial_state_of_charge'] = min(previous_soc, update_maxes['initial_state_of_charge'])
                # State-of-charge is handled by its own function.
                end_soc = self.compute_end_soc(storage, soc_reference)
                if end_soc is not None:
                    storage_dict['end_state_of_charge'] = end_soc

    def compute_end_soc(self, storage:str, soc_reference:Union[ModelData, dict, None]=None,
                        max_num_intervals:Union[int, None]=None):
        """ This computes the ending state of charge at a given time

        Args:
            storage (str): The name of the storage unit to use in the calculation
            soc_reference (Union[ModelData, dict, None]): Reference state-of-charge from a ModelData object (or dict
                                                          with EGRET ModelData structure)
            max_num_intervals (int): Maximum number of intervals to use for interpolation
        """
        # Parser to interpret soc_reference as either ModelData or dict
        if soc_reference is None:
            self.logger.warning("No state-of-charge reference provided to compute ending state-of-charge."
                                "Proceeding with end state-of-charge defaulting to initial state-of-charge.")
            return # Cannot proceed without a reference
        if isinstance(soc_reference, ModelData):
            reference_data = soc_reference.data
        else:
            reference_data = soc_reference

        # Set up the reference state-of-charge and time series
        ref_soc_series = reference_data['elements']['storage'][storage]['state_of_charge']['values']
        ref_time_keys = reference_data['system']['time_keys']
        # We can restrict to the last N intervals to limit interpolation over large inputs
        if max_num_intervals is  not None:
            ref_soc_series = ref_soc_series[-max_num_intervals:]
            ref_time_keys = ref_time_keys[-max_num_intervals:]
        # Set up the daterange for the current model
        periods = self.configuration["time"]["window"] + self.configuration["time"]["lookahead"]
        min_freq = self.configuration["time"]["min_freq"]
        model_start_time = self.mdl.data['system']['time_keys'][0]
        daterange = mk_daterange(model_start_time, min_freq=min_freq, periods=periods)
        # Find the state_of_charge for the time at the end of the daterange within the reference soc series
        # While loop ensures that we don't extend past the horizon (this only affects the model if the reference has
        # insufficient lookahead, which may happen at the end of a simulation)
        end_soc_found = False
        lookback, limit = 1, len(daterange)
        lookup_end_soc = None
        while not end_soc_found and lookback < limit:
            try:
                # End soc is determined based on the reference values.
                lookup_end_soc = get_value_at_time(ref_soc_series, ref_time_keys, daterange[-lookback])
                end_soc_found = True
            except ValueError:
                lookback += 1
        if lookup_end_soc is not None:
            # Bound soc on interval [0, 1]
            lookup_end_soc = min(1, max(0, lookup_end_soc))
        return lookup_end_soc

    def solve_model(self):
        """Run the egret model in self.mdl
        """
        self.logger.info(f"Solving Model\n")
        self.mdl_sol : ModelData = solve_unit_commitment(self.mdl, self.configuration["solve_arguments"]["solver"], 
                                        slack_type=SlackType[self.configuration["solve_arguments"]["slack"]],
                                        **self.configuration["solve_arguments"]["kwargs"])
        pricing_model = self.configuration["simulation"]["price_model"]
        if  pricing_model is not None:
            self.logger.info(f"Solving pricing model\n")
            self.pricing_model(pricing_model)

    def save_model(self, filename:str):
        if self.mdl_sol is not None:
            self.mdl_sol.write(filename, encoder=NumpyEncoder)
        elif self.mdl is not None:
            self.mdl.write(filename, encoder=NumpyEncoder)
        else:
            raise ValueError("No model currently loaded.")
        
    def pricing_model(self, pricing_model:str):
        """Run a pricing model (with binaries relaxed) and extract locational prices
        and reserve prices.
        
        NOTE: The solved prices are added to the solved dispatch model (self.mdl_sol).
        NO other values from the pricing model are kept!!!
        That is, if the dispatch in the pricing model differs from the original dispatch model,
        those changes WILL NOT be reflected in the result. 

        Args:
            pricing_model (str): pricing model, options are "lmp" or "achp"
        """
        pricing_instance = self.mdl_sol.clone()
        ## copy from Prescient/prescient/engine/egret/egret_plugin.py
        ## function solve_deterministic_day_ahead_pricing_problem
        if pricing_model == "lmp":
            ### fix all commitment variables
            for g, g_dict in pricing_instance.elements(element_type='generator', generator_type='thermal'):
                ## loop over all thermal generators, since they are the only ones with commitment variables.
                g_dict['fixed_commitment'] = g_dict['commitment']
                if 'reg_provider' in g_dict:
                    g_dict['fixed_regulation'] = g_dict['reg_provider']
            ### fix storage
            self.storage2load(pricing_instance)
        elif pricing_model == "achp":
            ## don't do anything, binaries just relaxed
            pass
        
        ## TODO: we may want to get the pyomo model here so we can get the duals
        ## on other constraints such as flow, or contingency
        ## solve relaxed problem to populate LMPs
        self.mdl_price : ModelData = solve_unit_commitment(pricing_instance, self.configuration["solve_arguments"]["solver"], 
                                        slack_type=SlackType[self.configuration["solve_arguments"]["slack"]],
                                        relaxed=True,
                                        **self.configuration["solve_arguments"]["kwargs"]) 

        ## update prices in solution
        for b, b_dict in self.mdl_price.elements(element_type="bus"):
            self.mdl_sol.data["elements"]["bus"][b]["lmp"] = b_dict["lmp"]

        for elem in ["area", "zone"]:
            for a, a_dict in self.mdl_price.elements(element_type=elem):
                for k in a_dict.keys():
                    if "_price" in k:
                        self.mdl_sol.data["elements"][elem][a][k] = a_dict[k]
        for k, v in self.mdl_price.data["system"].items():
            if "_price" in k:
                self.mdl_sol.data["system"][k] = v

    def storage2load(self, mdl:ModelData):
        """Convert all storage to pairs of loads to fix it for pricing evaluation

        Args:
            mdl (ModelData): egret model to convert

        Returns:
            ModelData: converted egret model
        """
        new_loads = {}
        for g, g_dict in mdl.elements(element_type="storage"):
            for direction in ["pos", "neg"]:
                name = g+"_"+direction
                p_load_key = "p_charge" if (direction == "pos") else "p_discharge" # double check the sign on this
                tmp = {}
                for k in ["bus", "in_service", "area", "zone"]:
                    tmp[k] = g_dict[k]
                tmp["p_load"] = g_dict[p_load_key] 
                if direction == 'neg':
                    tmp["p_load"]["values"] = -1*np.array(tmp["p_load"]["values"])
                new_loads[name] = tmp
        ## add new loads
        mdl.data["elements"]["load"].update(new_loads)
        ## remove the storage from the model
        mdl.data["elements"].pop("storage", None)


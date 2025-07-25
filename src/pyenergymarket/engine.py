"""The core functionality of pyenergymarket, encapsulated in the 
EnergyMarket class is here.
"""
from .utils.ioutils import merge_configs, Logger
from .utils.timeutils import mk_daterange
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
        self._monitored_branches = {}
        ### get configuration
        self.configuration = copy.deepcopy(energymarket_defaults)
        if config is not None:
            merge_configs(self.configuration, config)
        
        ### set up logger
        self.logger =Logger(**self.configuration["logging"])
        if self.configuration["logging"]["file"] is not None:
            self.logger.set_logfile(self.configuration["logging"]["file"])

    
    @property
    def monitored_branches(self) -> dict:
        """ dictionary containing elements to force mointor, i.e. set lazy to FALSE 
        Structure is ... keys are branches/constraines etc. and values are counts where this 
        element was **Not** binding
        Returns:
            dict: _description_
        """
        return self._monitored_branches

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

    # def add_constraints(self):
    #     """
    #     Add constraints to the model before solving.

    #     Returns:
    #         None: Updates the `lazy` attribute for constraints in the model.
    #     """
    #     # Loop through all branches
    #     for b, b_dict in self.mdl.elements(“branch”):
    #         # Check if the constraint is in the list of binding constraints
    #         # monitored_branches: dictionary tracking binding constraints. Format: {constraint_name: counter}
    #         if b in self.monitored_branches:
    #             # if we want to enforce:
    #                 # Set lazy attribute to False for tracked binding constraints
    #                 b_dict[“lazy”] = False
    #             # if we want to toggle off
    #                 # Set lazy attribute to True for untracked constraints
    #                 b_dict[“lazy”] = True

    def update_constraints(self, mdl_sol:ModelData=None, max_counter=5, tolerance_percentage=0.2):
        """
        Update binding constraints violations before each model solve

        Parameters:
            mdl_sol: solved model
            max_counter (int): Maximum counter value allowed before removing constraint from the tracker.
            tolerance_percentage (float): A small percentage value indicating how close to the limit a flow must be to consider a constraint binding.
        """
        if mdl_sol is None:
            mdl_sol = self.mdl_sol
            #this ensures that this function is skipped on the first pass when the model is None
            if mdl_sol is None:
                return

        # Loop over all branches
        for b, b_dict in mdl_sol.elements("branch"):
            max_flow = np.max(np.abs(b_dict["pf"]["values"]))  # Max absolute value of the flow on the element
            limit = abs(b_dict["rating_long_term"])       # Limit on the element (NEED TO MODIFY TO EMERGENCY LIMIT IF CONTINGENCY)
            tolerance = tolerance_percentage * limit # Calculate dynamic tolerance based on percentage

            # Check if constraint is tracked
            if b in self.monitored_branches:
                # Check if the constraint is binding
                if (abs(max_flow - limit) <= tolerance) or (max_flow >= limit):
                    # Constraint is still binding; keep it in the tracker and reset value to 
                    # zero to show that it is still freshly violating
                    self.monitored_branches[b] = 0
                else:
                    # Constraint is no longer binding; increment the counter
                    self.monitored_branches[b] += 1
                    
                    # Remove the constraint if the counter exceeds the threshold
                    if self.monitored_branches[b] > max_counter:
                        del self.monitored_branches[b]
                        # Reset the "lazy" constraint to not track
                        b_dict["lazy"] = True
            else:
                # Constraint is not tracked; check if it is binding
                if (abs(max_flow - limit) <= tolerance) or (max_flow >= limit):
                    # Add the constraint to the tracker with a counter value of 0
                    self.monitored_branches[b] = 0
                    # Since it is binding, set "lazy" attribute to track
                    b_dict["lazy"] = False

    def solve_model(self, mdl_sol:ModelData=None):
        """Run the egret model in self.mdl
        """
        self.logger.info(f"Solving Model\n")
        self.update_constraints(mdl_sol)
        # self.add_constraints()
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


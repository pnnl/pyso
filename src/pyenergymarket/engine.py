"""The core functionality of pyenergymarket, encapsulated in the
EnergyMarket class is here.
"""

import abc
import copy
from typing import Union
import inspect

import numpy as np
import pandas as pd
from egret.data.model_data import ModelData
from egret.models.unit_commitment import SlackType, solve_unit_commitment

from .pyenergymarket_defaults import energymarket_defaults
from .utils.egretutils import NumpyEncoder
from .utils.ioutils import Logger, merge_configs
from .utils.timeutils import count_onoff, mk_daterange


class DataProvider(abc.ABC):
    @abc.abstractmethod
    def get_model(self, daterange: pd.DatetimeIndex) -> ModelData:
        """Generate an Egret model based on the timeindex provided
        see also utils.timeutils.mk_daterange
        """
        pass


class EnergyMarket:
    def __init__(self, data_provider: DataProvider, config: dict = None, **kwargs):
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
        self.logger = Logger(**self.configuration["logging"])
        if self.configuration["logging"]["file"] is not None:
            self.logger.set_logfile(self.configuration["logging"]["file"])

    @property
    def monitored_branches(self) -> dict:
        """dictionary containing elements to force mointor, i.e. set lazy to FALSE
        Structure is ... keys are branches/constraines etc. and values are counts where this
        element was **Not** binding
        Returns:
            dict: _description_
        """
        return self._monitored_branches

    @property
    def max_nonviolation(self) -> int:
        """number of times a constraint needs to be non-binding, before it
        is removed from the automatic monitor branches list.

        Returns:
            int: count
        """
        return self.configuration["simulation"]["constraint_monitor"]["max_nonviolation"]

    @property
    def monitor_tolerance_percentage(self) -> float:
        """Flows within this percent of the branch limit will be considered "binding"
        for the purposes of the monitored branches tracking.

        Returns:
            float: percent below branch limit
        """
        return self.configuration["simulation"]["constraint_monitor"]["tolerance_percentage"]

    def set_property(self, value, *args, d=None):
        """set a property in the configuration dictionary.
        the arguments following `value` should be the keys in the dictionary
        tree to the desired property to set

        Args:
            value (Any): value to set
            *args: keys (in sequence) in the configuration dictionary to the location
                of the value to set

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
            err_msg = "EnergyMarket::set_property: the length of *args should never be less than 1."
            raise ValueError(err_msg)
        else:
            self.set_property(value, *args[1:], d=d[args[0]])

    def get_model(self, start: Union[str, pd.Timestamp]):
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

    def update_initial_conditions(
        self, mdl_sol: Union[ModelData, None] = None, update_mode: str = "calculate"
    ):
        """This function updates 'initial_p_output' and 'initial_status' for all
            generators in an Egret ModelData object. For the reference it will make a
            selection in this order:
            1. Use the mdl_sol input variable
            2. If mdl_sol is None, uses solution saved to EnergyMarket, self.mdl_sol
            3. If self.mdl_sol is None, will not make any updates

        Args:
            mdl_sol (Union[ModelData, None]): Egret ModelData with solutions, defaults to None
            update_mode (str): Choose how to update initial conditions.
                               copy - will use the same initial conditions as those in mdl_sol
                               calculate - will use the mdl_sol state at the end of the last window
                               as initial conditions
        """
        # Two different update modes (can add more as needed)
        update_options = ["calculate", "copy"]
        if update_mode not in update_options:
            raise ValueError(f"Invalid update_mode: {update_mode}, must be one of {update_options}")
        # The number of intervals between the start of the last model solve and the upcoming solve:
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

        # Loop through all generators in the upcoming model (self.mdl) and update
        # initial_p_output and initial_status
        for g, g_dict in self.mdl.elements(
            element_type="generator", generator_type=("thermal", "dispatchable")
        ):
            # When simulating multiple market instances, we may copy information
            # from one market to another.
            # For example, we may want to pass day-ahead results to a real-time market.
            if update_mode == "copy":
                g_dict["initial_p_output"] = float(
                    previous_mdl_sol.data["elements"]["generator"][g]["initial_p_output"]
                )
                g_dict["initial_status"] = float(
                    previous_mdl_sol.data["elements"]["generator"][g]["initial_status"]
                )
            # In all other cases, we calculate initial conditions from the end
            # of the previous cleared market.
            elif update_mode == "calculate":
                # Initial power is the last power cleared in the previous window
                # (subtract 1 to get on 0-base)
                g_dict["initial_p_output"] = float(
                    previous_mdl_sol.data["elements"]["generator"][g]["pg"]["values"][window - 1]
                )
                # we could also update the q/reactive power, but this first test will be dc only
                # g_dict['initial_q_output'] = float(
                #     previous_mdl_sol.data['elements']['generator'][g]['qg']['values'][window - 1])
                # Update initial status for this generator, using timeutils function
                new_initial_status = count_onoff(
                    previous_mdl_sol.data["elements"]["generator"][g], window - 1, min_freq
                )
                g_dict["initial_status"] = new_initial_status

        # Loop through all storage units in the upcoming model (self.mdl) and update:
        # - initial_state_of_charge
        # - end_state_of_charge
        # - initial_charge_rate and initial_discharge_rate
        for storage, storage_dict in self.mdl.elements(element_type="storage"):
            # Keys to update for storage with max values (or string for key of max value)
            update_maxes = {"initial_state_of_charge": 1, "end_state_of_charge": 1}
            # When simulating multiple markets, we may copy data between them.
            # For example, passing day-ahead results to a real-time market.
            if update_mode == "copy":
                for key, maxval in update_maxes.items():
                    if key in previous_mdl_sol.data["elements"]["storage"][storage].keys():
                        storage_dict[key] = float(
                            previous_mdl_sol.data["elements"]["storage"][storage][key]
                        )
                        # Enforce maximum (avoids floating point errors in constraints)
                        storage_dict[key] = min(max(0, storage_dict[key]), maxval)
            elif update_mode == "calculate":
                # Get the last value of the time window in the previous solution
                previous_soc = previous_mdl_sol.data["elements"]["storage"][storage][
                    "state_of_charge"
                ]["values"][window - 1]
                storage_dict["initial_state_of_charge"] = min(
                    max(0, previous_soc), update_maxes["initial_state_of_charge"]
                )

    def update_constraints(self, mdl_sol: ModelData = None):
        """
        Update binding constraints violations before each model solve
        Depends on:
        self.max_nonviolation:  Maximum count before removing constraint from tracker.
        self.monitor_tolerance_percentage: How close to the limit a flow must be to be
        considered a binding constraint.

        Parameters:
            mdl_sol: solved model. Defaults to None in which case self.mdl_sol will be used.
        """
        if mdl_sol is None:
            mdl_sol = self.mdl_sol
            # this ensures that this function is skipped on the first pass when the model is None
            if mdl_sol is None:
                return

        # Loop over all branches
        for b, b_dict in mdl_sol.elements("branch"):
            max_flow = np.max(
                np.abs(b_dict["pf"]["values"])
            )  # Max absolute value of the flow on the element
            # Check if long-term rating is available. If not, skip this branch
            if b_dict.get("rating_long_term", None) is None:
                continue
            limit = abs(
                b_dict["rating_long_term"]
            )  # Limit on the element (NEED TO MODIFY TO EMERGENCY LIMIT IF CONTINGENCY)
            tolerance = (
                self.monitor_tolerance_percentage * limit
            )  # Calculate dynamic tolerance based on percentage

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
                    if self.monitored_branches[b] > self.max_nonviolation:
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

    def solve_model(self, mdl_sol: ModelData = None):
        """Run the egret model in self.mdl"""
        self.logger.info("Solving Model\n")
        self.update_constraints(mdl_sol)
        # self.add_constraints()
        self.mdl_sol: ModelData = solve_unit_commitment(
            self.mdl,
            self.configuration["solve_arguments"]["solver"],
            slack_type=SlackType[self.configuration["solve_arguments"]["slack"]],
            **self.configuration["solve_arguments"]["kwargs"],
        )
        pricing_model = self.configuration["simulation"]["price_model"]
        if pricing_model is not None and not self.configuration["solve_arguments"]["kwargs"].get(
            "relaxed", False
        ):
            self.logger.info("Solving pricing model\n")
            self.pricing_model(pricing_model)

    def save_model(self, filename: str):
        def _encoder_safe_write(md, filename, encoder=NumpyEncoder):
            """Check that md.write method has encoder kwarg (for backward compatibility)"""
            write_args = inspect.getfullargspec(md.write)[0]
            if 'encoder' in write_args:
                md.write(filename, encoder=encoder)
            else:
                md.write(filename)
        if self.mdl_sol is not None:
            _encoder_safe_write(self.mdl_sol, filename)
        elif self.mdl is not None:
            _encoder_safe_write(self.mdl, filename)
        else:
            raise ValueError("No model currently loaded.")

    def pricing_model(self, pricing_model: str):
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
            # Loop over thermal generators to fix their commitment variables
            for _g, g_dict in pricing_instance.elements(
                element_type="generator", generator_type="thermal"
            ):
                # Only thermal generators have commitment variables
                g_dict["fixed_commitment"] = g_dict["commitment"]
                if "reg_provider" in g_dict:
                    g_dict["fixed_regulation"] = g_dict["reg_provider"]
            ### fix storage
            self.storage2load(pricing_instance)
        elif pricing_model == "achp":
            ## don't do anything, binaries just relaxed
            pass

        ## TODO: we may want to get the pyomo model here so we can get the duals
        ## on other constraints such as flow, or contingency
        ## solve relaxed problem to populate LMPs
        # Solve the relaxed problem for pricing
        self.mdl_price: ModelData = solve_unit_commitment(
            pricing_instance,
            self.configuration["solve_arguments"]["solver"],
            slack_type=SlackType[self.configuration["solve_arguments"]["slack"]],
            relaxed=True,
            **self.configuration["solve_arguments"]["kwargs"],
        )

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

    def storage2load(self, mdl: ModelData):
        """Convert all storage to pairs of loads to fix it for pricing evaluation

        Args:
            mdl (ModelData): egret model to convert

        Returns:
            ModelData: converted egret model
        """
        new_loads = {}
        for g, g_dict in mdl.elements(element_type="storage"):
            for direction in ["pos", "neg"]:
                name = g + "_" + direction
                # Note: double check the sign on this
                p_load_key = "p_charge" if (direction == "pos") else "p_discharge"
                tmp = {}
                for k in ["bus", "in_service", "area", "zone"]:
                    if k in g_dict.keys():
                        tmp[k] = g_dict[k]
                tmp["p_load"] = g_dict[p_load_key]
                if direction == "neg":
                    tmp["p_load"]["values"] = -1 * np.array(tmp["p_load"]["values"])
                new_loads[name] = tmp
        ## add new loads
        mdl.data["elements"]["load"].update(new_loads)
        ## remove the storage from the model
        mdl.data["elements"].pop("storage", None)

"""
This script adds a market operator capable of running the DA and RT market for
a user-defined time range.
"""

import datetime
import json
import logging
import os
import time as pytime

import numpy as np
import pandas as pd
from egret.data.model_data import ModelData
from scipy.interpolate import CubicSpline

import pyenergymarket as pyen
from pyenergymarket.engine import DataProvider
from pyenergymarket.marketmodels import da_market, rt_market
from pyenergymarket.marketmodels import market as generic_market

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.INFO)

default_options = {
    "start_time": "202401010000",  # Start time in YYYYmmddHHMM format
    "end_time": "202401080000",  # End time in YYYYmmddHHMM format
    "filename": "../../../../egret/egret/models/tests/uc_test_instances/tiny_uc_2.json",
    # Name (with path) to egret model_data file
    "case": None,  # String to append to the save directory
    "time_resolution": 30,  # Time resolution for simulation steps
    "time_unit": "second",  # Unit of time_resolution (allows second, minute, hour, day, year)
    "save": True,  # Whether to save output (will save locally)
}


class EgretProvider(DataProvider):
    """Generic Egret-based data provider. Draws from tiny_uc_1.json by default.
    This is configured for UC models with a single, hourly timeseries as the input.
    """

    def __init__(self, market_type="da", seed=None, filename="tiny_uc_1.json"):
        self.market_type = market_type
        self.filename = filename
        if seed is not None:
            np.random.seed(seed)

    def get_model(self, daterange: pd.DatetimeIndex) -> ModelData:
        """Loads the file, puts a daterange in the system and
        (for RT only) interpolates DA values"""
        with open(self.filename) as f:
            model_data = json.load(f)
        # For DA, we are just keeping everything at 1 day, so no changes except to set time keys
        daterange_str = [
            f"{d.year}-{d.month}-{d.day} {d.hour}:{d.minute}:{d.second}" for d in daterange
        ]
        model_data["system"]["time_keys"] = daterange_str
        # For RT we build the da_daterange, which we will used in the interpolation
        if self.market_type == "rt":
            # Use whatever is the given starting time
            year, month, day = daterange[0].year, daterange[0].month, daterange[0].day
            start = datetime.datetime(year, month, day, 0, 0, 0)
            da_daterange = pd.date_range(start=start, freq="60min", periods=24)
            # Interpolate all time series
            for _elem, elem_dict in model_data["elements"].items():
                for _etype, etype_dict in elem_dict.items():
                    for _ename, eentries in etype_dict.items():
                        if isinstance(eentries, dict):
                            if (
                                "data_type" in eentries.keys()
                                and eentries["data_type"] == "time_series"
                            ):
                                orig = eentries["values"]
                                cs = CubicSpline(da_daterange, orig)
                                new = cs(daterange)
                                # Enforce non-negativity
                                new[new < 0] = 0
                                eentries["values"] = new
            # Interpolate for system as well
            for _sys, sys_val in model_data["system"].items():
                if (
                    isinstance(sys_val, dict)
                    and "data_type" in sys_val.keys()
                    and sys_val["data_type"] == "time_series"
                ):
                    orig = sys_val["values"]
                    cs = CubicSpline(da_daterange, orig)
                    new = cs(daterange)
                    # Enforce non-negativity
                    new[new < 0] = 0
                    sys_val["values"] = new
        return ModelData(source=model_data)


class TSO:
    """
    This provides a transmission system operator (TSO) model.
    It enables the user to initialize custom markets and will run all markets
    """

    def __init__(self, options: dict):
        # Loads in the options
        self.save = options.get("save", True)
        self.filename = options["filename"]
        self.seed = options.get("seed", None)
        self.da_only = options.get("da_only", False)
        self.simulation_time = 0
        # Time resolution in seconds - will default to 30 seconds
        time_resolution = options.get("time_resolution", None)
        self.time_resolution = 1 if time_resolution is None else time_resolution
        # Figure out conversion from unit into seconds
        self.time_unit = options.get("time_unit", "seconds")
        scaling_options = {"second": 1, "minute": 60, "hour": 3600, "day": 86400, "year": 31536000}
        self.time_scaling = scaling_options[self.time_unit]

        # Initialize the market models
        self.start = pd.to_datetime(options["start_time"], format="%Y%m%d%H%M")
        self.end = pd.to_datetime(options["end_time"], format="%Y%m%d%H%M")
        self.markets = {}

    def add_market(self, market_name, market_timing, freq=None):
        market_object = create_market(
            market_name,
            start=self.start,
            end=self.end,
            filename=self.filename,
            seed=self.seed,
            market_timing=market_timing,
            freq=freq,
        )
        self.markets.update({market_name: market_object})

    def run_market(self, mtype):
        """Uses the market transition methods to clear the market
        Args:
            mtype (string): Can specify either 'da_market' or 'rt_market' mtype
        Returns:
            market_cleared (bool): True if a market was run, otherwise False
        """
        # Selects the market object from the saved dictionary
        market = self.markets[mtype]
        market_cleared = False
        # First check if we have hit a transition point (simulation time == next state time)
        if self.simulation_time / self.time_scaling == market.next_state_time:
            # Can supply kwargs to each state transition (idle, bidding, clearing are default)
            state_kwargs = {"clearing": {"local_save": self.save}}
            # Figure out which state is coming next
            state_order = list(market.market_timing["states"].keys())
            state_mapping = dict(zip(state_order, state_order[1:] + [state_order[0]]))
            mkt_state = market.current_state
            next_mkt_state = state_mapping[mkt_state]
            # Adjust kwargs (can add arguments here also)
            use_kwargs = {}
            if next_mkt_state in state_kwargs.keys():
                use_kwargs = state_kwargs[next_mkt_state]
            # Move to next state and adjust next_state_time
            market.move_to_next_state(**use_kwargs)
            if market.current_state == "clearing":
                market_cleared = True
            market.update_market()
        return market_cleared

    def initialize_steps(self):
        """Performs any steps needed before the simulation loop.
        Often the initial state must be set up - for example with an
        initial day-ahead market clearing
        """

        def clear_and_adjust(mtype):
            market = self.markets[mtype]
            market.clear_market(local_save=self.save)
            market.reset_timestep()
            market.update_market()

        for mtype in self.markets.keys():
            # Check to see if day-ahead market clearing happens at the start of the simulation
            clearing_start = self.markets[mtype].market_timing["states"]["clearing"]["start_time"]
            # In the (likely) case that these aren't the same, we will run an initial DA market
            # and pass results to RT
            if clearing_start != self.simulation_time:
                clear_and_adjust(mtype)
                logger.info(f"{mtype} initializing at simulation time {self.simulation_time}")

    def simulate(self):
        """Runs a test simulation with options specified"""
        t0 = pytime.time()  # For tracking simulation computational time
        # Initialized necessary parameters
        self.initialize_steps()
        horizon_reached = False
        # Run the simulation until the finish
        while not horizon_reached:
            # Clear DA (will only run when self.simulation_time == clearing_time
            for market_name in self.markets.keys():
                market_cleared = self.run_market(market_name)
                if market_cleared:
                    scaled_time = self.simulation_time / self.time_scaling
                    unit = self.time_unit
                    logger.info(f"{market_name} cleared at simulation time {scaled_time} {unit}s")
            # Can add callback features to pass data between markets here
            # Increment time and see if the end horizon is reached
            self.simulation_time += self.time_resolution * self.time_scaling
            if self.start + datetime.timedelta(seconds=self.simulation_time) >= self.end:
                horizon_reached = True
        t1 = pytime.time()
        simulation_wallclock = t1 - t0
        logger.info(f"Simulation complete.\nTotal computation time is {simulation_wallclock:.2f}s")

    def write_results(self):
        pass


class TSO_DART:
    """
    This provides a transmission system operator (TSO) model.
    This class holds a DA and RT market model instance and handles
    the timing and data passing between markets.
    It also stores the results for saving
    """

    def __init__(self, options: dict):
        # Loads in the options
        self.save = options.get("save", True)
        self.filename = options["filename"]
        self.seed = options.get("seed", None)
        self.da_only = options.get("da_only", False)
        self.simulation_time = 0
        # Time resolution in seconds - will default to 30 seconds
        time_resolution = options.get("time_resolution", None)
        self.time_resolution = 30 if time_resolution is None else time_resolution

        # Initialize the market models
        self.start = pd.to_datetime(options["start_time"], format="%Y%m%d%H%M")
        self.end = pd.to_datetime(options["end_time"], format="%Y%m%d%H%M")
        self.da_market = create_market(
            mtype="da", start=self.start, end=self.end, filename=self.filename, seed=self.seed
        )
        if not self.da_only:
            self.rt_market = create_market(
                mtype="rt", start=self.start, end=self.end, filename=self.filename, seed=self.seed
            )

    def _pass_da_to_rt(self):
        # Commitment
        da_commitment = self.da_market.commitment_hist
        self.rt_market.join_da_commitment(da_commitment)
        # State-of-Charge
        if hasattr(self.rt_market, "storage_soc") and hasattr(self.da_market, "storage_soc"):
            self.rt_market.storage_soc = self.da_market.storage_soc
        # Also saving day-ahead solutions to RT for 1st RT initialization
        if self.rt_market.da_mdl_sol is None:
            self.rt_market.da_mdl_sol = self.da_market.em.mdl_sol

    def run_market(self, mtype):
        """Uses the market transition methods to clear the market
        Args:
            mtype (string): Can specify either 'da_market' or 'rt_market' mtype
        Returns:
            market_cleared (bool): True if a market was run, otherwise False
        """
        # Selects either self.da_market or self.rt_market
        market = getattr(self, mtype)
        market_cleared = False
        # First check if we have hit a transition point (simulation time == next state time)
        if self.simulation_time == market.next_state_time:
            # Can supply kwargs to each state transition (idle, bidding, clearing are default)
            state_kwargs = {"clearing": {"local_save": self.save}}
            # Figure out which state is coming next
            state_order = list(market.market_timing["states"].keys())
            state_mapping = dict(zip(state_order, state_order[1:] + [state_order[0]]))
            mkt_state = market.current_state
            next_mkt_state = state_mapping[mkt_state]
            # Adjust kwargs (can add arguments here also)
            use_kwargs = {}
            if next_mkt_state in state_kwargs.keys():
                use_kwargs = state_kwargs[next_mkt_state]
            # Move to next state and adjust next_state_time
            market.move_to_next_state(**use_kwargs)
            if market.current_state == "clearing":
                market_cleared = True
            market.update_market()
        return market_cleared

    def initialize_steps(self):
        """Performs any steps needed before the simulation loop.
        Often the initial state must be set up - for example with an
        initial day-ahead market clearing
        """

        def clear_and_adjust(mtype):
            market = getattr(self, mtype)
            market.clear_market(local_save=self.save)
            market.reset_timestep()
            market.update_market()

        # Check to see if day-ahead market clearing happens at the start of the simulation
        clearing_start = self.da_market.market_timing["states"]["clearing"]["start_time"]
        # In the (likely) case that these aren't the same, we will run an initial DA market
        # and pass results to RT
        if clearing_start != self.simulation_time:
            logger.info(f"DA market initializing at simulation time {self.simulation_time}")
            clear_and_adjust("da_market")
            self._pass_da_to_rt()
            clear_and_adjust("rt_market")

    def simulate(self):
        """Runs a test simulation with options specified"""
        # Initialized necessary parameters
        self.initialize_steps()
        horizon_reached = False
        t0 = pytime.time()  # For tracking simulation computational time
        # Run the simulation until the finish
        while not horizon_reached:
            # Clear DA (will only run when self.simulation_time == clearing_time
            da_cleared = self.run_market("da_market")
            if not self.da_only:
                if da_cleared:
                    logger.info(f"DA market cleared at simulation time {self.simulation_time}")
                    # Send commitment and storage soc to RT after the DA market runs
                    self._pass_da_to_rt()
                # Clear RT (will only run when self.simulation_time == clearing_time
                rt_cleared = self.run_market("rt_market")
                if rt_cleared:
                    logger.info(f"RT market cleared at simulation time {self.simulation_time}")
            # Increment time and see if the end horizon is reached
            self.simulation_time += self.time_resolution
            if self.start + datetime.timedelta(seconds=self.simulation_time) >= self.end:
                horizon_reached = True
        t1 = pytime.time()
        simulation_wallclock = t1 - t0
        logger.info(f"Simulation complete.\nTotal computation time is {simulation_wallclock:.2f}s")
        with open("simulation_time.json", "w") as f:
            json.dump({"simulation_time": simulation_wallclock}, f)

    def write_results(self):
        pass


def get_market_timing(mtype):
    # Use adjustable minute frequency to allow variable-length RTM

    # Daily market with bidding beginning nine minutes before the end of
    # the market interval and ending when clearing begins one minutee before
    # the end of the interval.

    if mtype == "da":
        market_timing = {
            "states": {
                "idle": {"start_time": 0, "duration": 42660},
                "bidding": {"start_time": 42660, "duration": 540},
                "clearing": {"start_time": 43200, "duration": 43200},
            },
            "initial_offset": 0,
            "initial_state": "idle",
            "market_interval": 86400,
        }
    elif mtype == "rt":
        rtm_min_freq = 15  # options['market']['rt_min_freq'] * options['market']['rt_window']
        rtm_mkt_interval = rtm_min_freq * 60
        market_timing = {
            "states": {
                "idle": {
                    "start_time": 0,
                    "duration": int(rtm_mkt_interval * 2 / 3),
                },
                "bidding": {
                    "start_time": int(rtm_mkt_interval * 2 / 3),
                    "duration": int(rtm_mkt_interval * 0.2),
                },
                "clearing": {
                    "start_time": int(rtm_mkt_interval * 2.6 / 3),
                    "duration": int(rtm_mkt_interval * 0.4 / 3),
                },
            },
            "initial_offset": 0,
            "initial_state": "idle",
            "market_interval": rtm_mkt_interval,
        }
    return market_timing


def create_market(
    mtype="da", start=None, end=None, filename=None, seed=None, market_timing=None, freq=None
):
    """Builds a market instance"""
    uncertainty_data_provider = EgretProvider(market_type=mtype, filename=filename, seed=seed)
    em = pyen.EnergyMarket(uncertainty_data_provider)
    if market_timing is None:
        # Have da and rt options pre-configured
        market_timing = get_market_timing(mtype)
    # Format start/end as strings so they will work in market.py
    if not isinstance(start, str):
        start = f"{start.year}-{start.month:02d}-{start.day:02d}"
    if not isinstance(end, str):
        end = f"{end.year}-{end.month:02d}-{end.day:02d}"
    # Reset the timing parameters for RT
    if mtype == "da":
        market = da_market.DAMarket(start, end, market_timing=market_timing, market=em)
    elif mtype == "rt":
        window = 1
        lookahead = 4
        market = rt_market.RTMarket(
            start, end, market_timing=market_timing, market=em, window=window, lookahead=lookahead
        )
    else:
        # Generic market
        market = generic_market.Market(mtype, market_timing, start, end, market=em, freq=freq)
    return market


def execute_generic(options, time_unit="hour"):
    """Runs a market instance with the given options"""
    options["time_unit"] = time_unit
    # Creates a market operator
    tso = TSO(options)
    # Edit the market timing here #TODO: pull from a file or alternate input
    market_timing = {
        "states": {
            "idle": {"start_time": 0, "duration": 9, "unit": time_unit},
            "bidding": {"start_time": 9, "duration": 3, "unit": time_unit},
            "clearing": {"start_time": 12, "duration": 12, "unit": time_unit},
        },
        "initial_offset": 0,
        "initial_state": "idle",
        "market_interval": 24,
    }
    tso.add_market("daily_market", market_timing)
    # Runs the simulation
    tso.simulate()


def execute_dart(options):
    """Runs a market instance with the given options"""
    # Creates a market operator
    tso = TSO_DART(options)
    # Runs the simulation
    tso.simulate()


if __name__ == "__main__":
    # Read in configuration settings
    # (if this file doesn't exist, create a file with default settings)
    if not os.path.exists("tso_config_dart.json"):
        logger.critical(
            "No configuration (tso_config_dart.json) found. Creating file with defaults."
        )
        with open("tso_config.json", "w") as f:
            json.dump(default_options, f, indent=4)
        logger.critical("Default config created. Edit tso_config_dart.json to update run settings")
        exit()

    with open("tso_config_dart.json") as f:
        options = json.load(f)

    execute_dart(options)

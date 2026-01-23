"""
This script adds a market operator capable of running the DA and RT market for
a user-defined time range.
"""

import argparse
import datetime
import json
import logging
import os
import abc
import time as pytime

import pandas as pd

import pyenergymarket as pyen
from pyenergymarket.marketmodels import market as generic_market
from pyenergymarket.marketmodels.default_tso_config import get_defaults
from pyenergymarket.parsers.egretparser import DailyEgretProvider
from pyenergymarket.utils.ioutils import merge_configs

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.INFO)


class TSO(abc.ABC):
    """
    This provides a transmission system operator (TSO) model.
    It enables the user to initialize custom markets and will run all markets
    """

    def __init__(self, options: dict):
        # Loads in the options
        self.save = options.get("save", True)
        self.filename = options["filename"]
        self.simulation_time = 0
        # Time resolution and unit will default to 1 hour resolution
        self.time_resolution = options.get("time_resolution", 1)
        self.time_unit = options.get("time_unit", "hour")
        scaling_options = {"second": 1, "minute": 60, "hour": 3600, "day": 86400, "year": 31536000}
        if self.time_unit.lower() not in scaling_options.keys():
            raise ValueError(
                f"Invalid time unit {self.time_unit}. "
                f"Time unit must be one of: {scaling_options.keys()}"
            )
        self.time_scaling = scaling_options[self.time_unit.lower()]

        # Initialize the market models
        self.start = pd.to_datetime(options["start_time"], format="%Y%m%d%H%M")
        self.end = pd.to_datetime(options["end_time"], format="%Y%m%d%H%M")
        self.markets = {}
        self.market_order = options["market_order"]

    @abc.abstractmethod
    def add_market(self, market_name, market_timing, em_config, freq=None):
        """Adds an energymarket object, containing market characteristcs"""
        if market_name not in self.market_order:
            raise ValueError(
                f"Market {market_name} not in the market_order input ({self.market_order})"
            )
        market_object = create_market(
            market_name,
            em_config,
            start=self.start,
            end=self.end,
            filename=self.filename,
            market_timing=market_timing,
            freq=freq,
        )
        self.markets.update({market_name: market_object})

    @abc.abstractmethod
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

    @abc.abstractmethod
    def simulate(self):
        """Runs a test simulation with options specified"""
        t0 = pytime.time()  # For tracking simulation computational time
        horizon_reached = False
        # Run the simulation until the finish
        while not horizon_reached:
            # Ask markets for their next start times
            next_starts =
            for market_name in self.market_order:
                market_cleared = self.run_market(market_name)
                if market_cleared:
                    logger.info(
                        f"{market_name} cleared at simulation time {self.simulation_time} "
                        f"{self.time_unit}s"
                    )
            # Can add callback features to pass data between markets here
            # Once all market start times are at the end (inclusive), terminate the simulation
            horizon_reached = all([self.start + self.markets[mkt].next_state_time >=
                                   self.end for mkt in self.market_order])
        t1 = pytime.time()
        simulation_wallclock = t1 - t0
        logger.info(f"Simulation complete.\nTotal computation time is {simulation_wallclock:.2f}s")

    def write_results(self):
        pass


def create_market(mtype, em_config, market_timing, start=None, end=None, filename=None, freq=None):
    """Builds a market instance"""
    data_provider = DailyEgretProvider(filename)
    em = pyen.EnergyMarket(data_provider, config=em_config)
    # Format start/end as strings so they will work in market.py
    if not isinstance(start, str):
        start = f"{start.year}-{start.month:02d}-{start.day:02d}"
    if not isinstance(end, str):
        end = f"{end.year}-{end.month:02d}-{end.day:02d}"
    market = generic_market.Market(mtype, market_timing, start, end, market=em, freq=freq)
    return market


def execute_sequence(options):
    """Runs a market instance with the given options"""
    # Check to make sure empty default options have been specified
    empty_defaults = ["start_time", "end_time", "filename"]
    for default in empty_defaults:
        if options.get(default, "") == "":
            raise ValueError(f"Must specify a value for config option {default}")
    # Creates a market operator
    tso = TSO(options)
    # Add markets from options (requires a market_timing and em_config specified)
    for market in options["markets"].keys():
        market_timing = options["markets"][market]["market_timing"]
        em_config = options["markets"][market]["em_config"]
        freq = em_config["time"]["min_freq"]
        tso.add_market(market, market_timing, em_config, freq=freq)
    # Runs the simulation
    tso.simulate()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-c", "--config", help="Name/path of tso configuration file", default="tso_config.json"
    )
    args = parser.parse_args()

    config_file = args.config

    # Import default settings
    default_options = get_defaults()

    # Check if the configuration file exists.
    # If this file doesn't exist, create a file with default settings
    if not os.path.exists(args.config):
        logger.critical(f"No configuration ({config_file}) found. Creating file with defaults.")
        with open(config_file, "w") as f:
            json.dump(default_options, f, indent=4)
        logger.critical(f"Default config created. Edit {config_file} to update run settings")
        exit()

    # Read in configuration settings and merge with the defaults (defaults will only be applied
    # to any missing/unspecified configuration elements
    with open(config_file) as f:
        options = json.load(f)
    # Joins any user options onto the default options
    merge_configs(default_options, options)

    execute_sequence(default_options)

"""
This script adds a market operator capable of running the DA and RT market for
a user-defined time range.
"""

import pandas as pd
import numpy as np
from egret.data.model_data import ModelData
from pyenergymarket.marketmodels import da_market
from pyenergymarket.marketmodels import rt_market
from pyenergymarket.marketmodels import market as generic_market
from pyenergymarket.parsers.egretparser import DailyEgretProvider
import pyenergymarket as pyen
import argparse, json, datetime
from reverse_argparse import ReverseArgumentParser
import time as pytime
import logging

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.INFO)

class TSO:
    """
    This provides a transmission system operator (TSO) model.
    It enables the user to initialize custom markets and will run all markets
    """
    def __init__(self, options:dict):
        # Loads in the options
        self.save = options.get('save', True)
        self.filename = options['filename']
        self.da_only = options.get('da_only', False)
        self.simulation_time = 0
        # Time resolution in seconds - will default to 30 seconds
        time_resolution = options.get('time_resolution', None)
        self.time_resolution = 1 if time_resolution is None else time_resolution
        # Figure out conversion from unit into seconds
        self.time_unit = options.get('time_unit', 'seconds')
        scaling_options = {'second': 1, 'minute': 60, 'hour': 3600, 'day': 86400, 'year': 31536000}
        self.time_scaling = scaling_options[self.time_unit]

        # Initialize the market models
        self.start = pd.to_datetime(options['start_time'], format='%Y%m%d%H%M')
        self.end = pd.to_datetime(options['end_time'], format='%Y%m%d%H%M')
        self.markets = {}

    def add_market(self, market_name, market_timing, freq=None):
        market_object = create_market(market_name, start=self.start, end=self.end, filename=self.filename,
                                      market_timing=market_timing, freq=freq)
        self.markets.update({market_name: market_object})

    def run_market(self, mtype):
        """ Uses the market transition methods to clear the market
        Args:
            mtype (string): Can specify either 'da_market' or 'rt_market' mtype
        Returns:
            market_cleared (bool): True if a market was run, otherwise False
        """
        # Selects the market object from the saved dictionary
        market = self.markets[mtype]
        market_cleared = False
        # First check if we have hit a transition point (simulation time == next state time)
        if self.simulation_time/self.time_scaling == market.next_state_time:
            # Can supply kwargs to each state transition (idle, bidding, clearing are default)
            state_kwargs = {'clearing': {'local_save': self.save}}
            # Figure out which state is coming next
            state_order = list(market.market_timing['states'].keys())
            state_mapping = dict(zip(state_order, state_order[1:] + [state_order[0]]))
            mkt_state = market.current_state
            next_mkt_state = state_mapping[mkt_state]
            # Adjust kwargs (can add arguments here also)
            use_kwargs = {}
            if next_mkt_state in state_kwargs.keys():
                use_kwargs = state_kwargs[next_mkt_state]
            # Move to next state and adjust next_state_time
            market.move_to_next_state(**use_kwargs)
            if market.current_state == 'clearing':
                market_cleared = True
            market.update_market()
        return market_cleared

    def initialize_steps(self):
        """ Performs any steps needed before the simulation loop.
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
            clearing_start = self.markets[mtype].market_timing['states']['clearing']['start_time']
            # In the (likely) case that these aren't the same, we will run an initial DA market and pass results to RT
            if clearing_start != self.simulation_time:
                clear_and_adjust(mtype)
                logger.info(f"{mtype} initializing at simulation time {self.simulation_time}")

    def simulate(self):
        """ Runs a test simulation with options specified """
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
                    logger.info(f"{market_name} cleared at simulation time {self.simulation_time/self.time_scaling} {self.time_unit}s")
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

def get_market_timing(mtype):
    # Use adjustable minute frequency to allow variable-length RTM

    # Daily market with bidding beginning nine minutes before the end of
    # the market interval and ending when clearing begins one minutee before
    # the end of the interval.

    if mtype == 'da':
        market_timing = {
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
            "initial_offset": 0,
            "initial_state": "idle",
            "market_interval": 86400
        }
    elif mtype == 'rt':
        rtm_min_freq = 15 #options['market']['rt_min_freq'] * options['market']['rt_window']
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
                }
            },
            "initial_offset": 0,
            "initial_state": "idle",
            "market_interval": rtm_mkt_interval
        }
    return market_timing

def create_market(mtype, start=None, end=None, filename=None, market_timing=None, freq=None):
    """ Builds a market instance """
    data_provider = DailyEgretProvider(filename)
    em_config = {
        "time": {
            "min_freq": 60,  # period length in minutes
            "window": 24,  # solution window
            "lookahead": 24  # solution lookahead
        },
        "solve_arguments": {
            "solver": "gurobi_persistent",
        },
    }
    em = pyen.EnergyMarket(data_provider, config=em_config)
    if market_timing is None:
        # Have da and rt options pre-configured
        market_timing = get_market_timing(mtype)
    # Format start/end as strings so they will work in market.py
    if not isinstance(start, str):
        start = f'{start.year}-{start.month:02d}-{start.day:02d}'
    if not isinstance(end, str):
        end = f'{end.year}-{end.month:02d}-{end.day:02d}'
    market = generic_market.Market(mtype, market_timing, start, end, market=em, freq=freq)
    return market

def execute_sequence(options, time_unit='hour'):
    """ Runs a market instance with the given options """
    options['time_unit'] = time_unit
    # Creates a market operator
    tso = TSO(options)
    # Edit the market timing here #TODO: pull from a file or alternate input
    market_timing = {
        "states": {
            "idle": {
                "start_time": 0,
                "duration": 9,
                "unit": time_unit
            },
            "bidding": {
                "start_time": 9,
                "duration": 3,
                "unit": time_unit
            },
            "clearing": {
                "start_time": 12,
                "duration": 12,
                "unit": time_unit
            },
        },
        "initial_offset": 0,
        "initial_state": "idle",
        "market_interval": 24
    }
    tso.add_market("daily_market", market_timing)
    # Runs the simulation
    tso.simulate()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-s", "--start_time", help="Start time in YYYYmmddHHMM format",
                        default='202401010000')
    parser.add_argument("-e", "--end_time", help="End time in YYYYmmddHHMM format",
                        default='202401080000')
    parser.add_argument("-f", "--filename", help="Name (with path) to egret model_data file",
                        default='../../../../pcm-data-pipeline/output')
    parser.add_argument("--da_only", help="If included, will only run the day-ahead market", action='store_true')
    parser.add_argument("-c", "--case", help="Will be appended to the save directory")
    parser.add_argument("-r", "--time_resolution", type=int, help="The simulation time resolution in"
                                                                      "units of seconds.", default=None)
    args = parser.parse_args()
    # Show command line options
    rev_parser = ReverseArgumentParser(parser, args)
    logger.info(f"Command line options selected:\n{rev_parser.get_pretty_command_line_invocation()}")

    options = args.__dict__
    options.update({'save':True})
    execute_sequence(options)

"""
This script adds a market operator capable of running the DA and RT market for
a user-defined time range.
"""
import os.path

import pandas as pd
from pyenergymarket.marketmodels import market as generic_market
from pyenergymarket.parsers.egretparser import DailyEgretProvider
import pyenergymarket as pyen
import json, datetime
import time as pytime
import logging

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.INFO)

default_options = {
    "start_time": '202401010000', # Start time in YYYYmmddHHMM format
    "end_time": '202401080000', # End time in YYYYmmddHHMM format
    "filename": '../../../../pcm-data-pipeline/output', # Name (with path) to egret model_data file
    "case": None, # String to append to the save directory
    "time_resolution": 1, # Time resolution for simulation steps
    "time_unit": 'hour', # Unit of time_resolution (allows second, minute, hour, day, year)
    "save": True, # Whether to save output (will save locally)
    # Dictionaries for the different market types
    # These must be of the form
    #    "market_name": {
    #       "market_timing": { market_timing_dictionary }
    #       "em_config": { energymarket_config_dictionary }
    #    }
    "market_order": ["weekly", "daily"],
    "markets": {
        "daily": {
            "market_timing": {
                "states": {
                    "clearing": {
                        "start_time": 0,
                        "duration": 3,
                    },
                    "idle": {
                        "start_time": 3,
                        "duration": 18,
                    },
                    "bidding": {
                        "start_time": 21,
                        "duration": 3,
                    },
                },
                "initial_offset": 0,
                "initial_state": "idle",
                "market_interval": 24
                },
            "em_config": {
                "time": {
                    "min_freq": 60,  # period length in minutes
                    "window": 24,  # solution window
                    "lookahead": 24  # solution lookahead
                },
                "solve_arguments": {
                    "solver": "gurobi_persistent",
                    "solver_options": {"ConcurrentMethod":0, "Method":3, "MIPFocus":1, "CutPasses": 2},
                },
                "ptdf_options": {
                        "rel_ptdf_tol" : 0.0,
                        "abs_ptdf_tol" : 1e-7,
                        "abs_flow_tol" : 1e-3, # solver tolerance, plus a bit
                        "rel_flow_tol" : 0.0,
                        "branch_kv_threshold" : 100.0,
                        "kv_threshold_type" : "both",
                        "max_violations_per_iteration" : 20
                        #    "lp_cleanup_phase" : False,
                }
        },
        "weekly": {
            "market_timing": {
                "states": {
                    "clearing": {
                        "start_time": 0,
                        "duration": 1,
                    },
                    "idle": {
                        "start_time": 1,
                        "duration": 46,
                    },
                    "bidding": {
                        "start_time": 47,
                        "duration": 1,
                    },

                },
                "initial_offset": 0,
                "initial_state": "idle",
                "market_interval": 48
            },
            "em_config": {
                "time": {
                    "min_freq": 240, # period length in minutes
                    "window": 48, # solution window
                    "lookahead": 6 # solution lookahead
                },
                "solve_arguments": {
                    "solver": "gurobi_persistent",
                    "solver_options": {"ConcurrentMethod":0, "Method":3, "MIPFocus":1, "CutPasses": 2},
                },
                "ptdf_options": {
                        "rel_ptdf_tol" : 0.0,
                        "abs_ptdf_tol" : 1e-7,
                        "abs_flow_tol" : 1e-3, # solver tolerance, plus a bit
                        "rel_flow_tol" : 0.0,
                        "branch_kv_threshold" : 100.0,
                        "kv_threshold_type" : "both",
                        "max_violations_per_iteration" : 20
                        #    "lp_cleanup_phase" : False,
                }
            }
        }
    }
}

class TSO:
    """
    This provides a transmission system operator (TSO) model.
    It enables the user to initialize custom markets and will run all markets
    """
    def __init__(self, options:dict):
        # Loads in the options
        self.save = options.get('save', True)
        self.filename = options['filename']
        self.simulation_time = 0
        # Time resolution and unit will default to 1 hour resolution
        self.time_resolution = options.get('time_resolution', 1)
        self.time_unit = options.get('time_unit', 'hour')

        # Initialize the market models
        self.start = pd.to_datetime(options['start_time'], format='%Y%m%d%H%M')
        self.end = pd.to_datetime(options['end_time'], format='%Y%m%d%H%M')
        self.markets = {}
        self.market_order = options['market_order']

    def add_market(self, market_name, market_timing, em_config, freq=None):
        """ Adds an energymarket object, containing market characteristcs """
        if market_name not in self.market_order:
            raise ValueError(f"Market {market_name} not in the market_order input ({self.market_order})")
        market_object = create_market(market_name, em_config, start=self.start, end=self.end, filename=self.filename,
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
        if self.simulation_time == market.next_state_time:
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
        for mtype in self.market_order:
            # Perform an initial clearing of each market
            logger.info(f"Performing an initial clearing of market {mtype}")
            clear_and_adjust(mtype)
            logger.info(f"{mtype} initialized at simulation time {self.simulation_time}")

    def simulate(self):
        """ Runs a test simulation with options specified """
        t0 = pytime.time()  # For tracking simulation computational time
        # Initialized necessary parameters
        self.initialize_steps()
        horizon_reached = False
        # Run the simulation until the finish
        while not horizon_reached:
            # Clear DA (will only run when self.simulation_time == clearing_time
            for market_name in self.market_order:
                print(f"At simulation time {self.simulation_time} checking on run for market", market_name)
                market_cleared = self.run_market(market_name)
                if market_cleared:
                    logger.info(f"{market_name} cleared at simulation time {self.simulation_time} {self.time_unit}s")
            # Can add callback features to pass data between markets here
            # Increment time and see if the end horizon is reached
            self.simulation_time += self.time_resolution
            if self.start + datetime.timedelta(seconds=self.simulation_time) >= self.end:
                horizon_reached = True
        t1 = pytime.time()
        simulation_wallclock = t1 - t0
        logger.info(f"Simulation complete.\nTotal computation time is {simulation_wallclock:.2f}s")

    def write_results(self):
        pass


def create_market(mtype, em_config, market_timing, start=None, end=None, filename=None, freq=None):
    """ Builds a market instance """
    data_provider = DailyEgretProvider(filename)
    em = pyen.EnergyMarket(data_provider, config=em_config)
    # Format start/end as strings so they will work in market.py
    if not isinstance(start, str):
        start = f'{start.year}-{start.month:02d}-{start.day:02d}'
    if not isinstance(end, str):
        end = f'{end.year}-{end.month:02d}-{end.day:02d}'
    print("Creating market in range", start, "to", end)
    market = generic_market.Market(mtype, market_timing, start, end, market=em, freq=freq)
    return market

def execute_sequence(options, time_unit='hour'):
    """ Runs a market instance with the given options """
    options['time_unit'] = time_unit
    # Creates a market operator
    tso = TSO(options)
    # Add markets from options (requires a market_timing and em_config specified)
    for market in options['markets'].keys():
        market_timing = options['markets'][market]['market_timing']
        em_config = options['markets'][market]['em_config']
        freq = em_config["time"]["min_freq"]
        tso.add_market(market, market_timing, em_config, freq=freq)
    # Runs the simulation
    tso.simulate()

if __name__ == '__main__':
    # Read in configuration settings (if this file doesn't exist, create a file with default settings
    if not os.path.exists('tso_config.json'):
        logger.critical("No configuration (tso_config.json) found. Creating file with defaults.")
        with open('tso_config.json', 'w') as f:
            json.dump(default_options, f, indent=4)
        logger.critical("Default config created. Edit tso_config.json to update run settings")
        exit()

    with open('tso_config.json', 'r') as f:
        options = json.load(f)

    execute_sequence(options)

"""
This script adds a market operator capable of running the DA and RT market for
a user-defined time range.
"""

import pandas as pd
import numpy as np
from egret.data.model_data import ModelData
from pyenergymarket.marketmodels import osw_da_market as da_market
from pyenergymarket.marketmodels import osw_rt_market as rt_market
from pyenergymarket.engine import DataProvider
import pyenergymarket as pyen
import argparse, json, datetime
from scipy.interpolate import CubicSpline

class UncertaintyProvider(DataProvider):
    """ Uncertainty-based data provider. Draws from tiny_uc_1_uncert.json by default  """
    def __init__(self, market_type ='da', seed=None, filename='tiny_uc_1_uncert.json'):
        self.market_type = market_type
        self.filename = filename
        if seed is not None:
            np.random.seed(seed)

    def get_model(self, daterange:pd.DatetimeIndex) -> ModelData:
        """ Loads the file, then randomizes all uncertain generators """
        with open(self.filename, 'r') as f:
            model_data = json.load(f)
        # For DA, we are just keeping everything at 1 day, so no changes except to set time keys
        daterange_str = [f'{d.year}-{d.month}-{d.day} {d.hour}:{d.minute}:{d.second}' for d in daterange]
        model_data['system']['time_keys'] = daterange_str
        # For RT we build the da_daterange, which we will used in the interpolate
        if self.market_type == 'rt':
            # Use whatever is the given starting time
            year, month, day = daterange[0].year, daterange[0].month, daterange[0].day
            start = datetime.datetime(year, month, day, 0, 0, 0)
            da_daterange = pd.date_range(start=start, freq="60min", periods=24)
            # Interpolate all time series
            for elem, elem_dict in model_data['elements'].items():
                for etype, etype_dict in elem_dict.items():
                    for ename, eentries in etype_dict.items():
                        if isinstance(eentries, dict):
                            if 'data_type' in eentries.keys() and eentries['data_type'] == 'time_series':
                                orig = eentries['values']
                                cs = CubicSpline(da_daterange, orig)
                                new = cs(daterange)
                                # Enforce non-negativity #TODO: check if this is okay. Maybe do linear instead of spline
                                new[new < 0] = 0
                                eentries['values'] = new
            # Interpolate for system as well
            for sys, sys_val in model_data['system'].items():
                if isinstance(sys_val, dict) and 'data_type' in sys_val.keys() and sys_val['data_type'] == 'time_series':
                    orig = sys_val['values']
                    cs = CubicSpline(da_daterange, orig)
                    new = cs(daterange)
                    # Enforce non-negativity #TODO: check if this is okay. Maybe do linear instead of spline
                    new[new < 0] = 0
                    sys_val['values'] = new
        # For real-time markets, run an interpolation
        # Randomize uncertain generators
        # TODO: Can make this more sophisticated later, time permitting
        for gen, gen_dict in model_data['elements']['generator'].items():
            if 'pg_sigma' in gen_dict.keys():
                orig_gen = gen_dict['p_max']['values']
                sigma = gen_dict['pg_sigma']['values']
                new_gen = np.array(orig_gen) + np.random.normal(scale=sigma, size=len(orig_gen))
                # Impose max/capacity cutoff and zero cutoff
                new_gen[new_gen > np.max(orig_gen)] = np.max(orig_gen)
                new_gen[new_gen < 0] = 0
                gen_dict['p_max']['values'] = new_gen

        # Randomize load by small amount
        randomize_load = True
        if randomize_load:
            factor = 0.02
            for load, load_dict in model_data['elements']['load'].items():
                orig_load = load_dict['p_load']['values']
                new_load = [ol + np.random.normal(scale=factor*ol) for ol in orig_load]
                load_dict['p_load']['values'] = new_load

        return ModelData(source=model_data)

class MarketOperator:
    """
    This operator holds a DA and RT market model instance and handled the timing and data passing
    between markets.

    It also stores the results for saving
    """
    def __init__(self, options):
        # Loads in the options
        self.save = options.get('save', True)
        self.filename = options['filename']
        self.seed = options.get('seed', None)
        self.da_only = options.get('da_only', False)

        # Initialize the market models
        self.start = pd.to_datetime(options['start_time'], format='%Y%m%d%H%M')
        self.end = pd.to_datetime(options['end_time'], format='%Y%m%d%H%M')
        self.da_market = create_market(mtype='da', start=self.start, end=self.end, filename=self.filename, seed=self.seed)
        if not self.da_only:
            self.rt_market = create_market(mtype='rt', start=self.start, end=self.end, filename=self.filename, seed=self.seed)

    def _pass_da_to_rt(self):
        # Commitment
        da_commitment = self.da_market.commitment_hist
        self.rt_market.join_da_commitment(da_commitment)
        # State-of-Charge
        if hasattr(self.rt_market, 'storage_soc') and hasattr(self.da_market, 'storage_soc'):
            self.rt_market.storage_soc = self.da_market.storage_soc
        # Also saving day-ahead solutions to RT for 1st RT initialization
        if not hasattr(self.rt_market, 'da_mdl_sol'):
            self.rt_market.da_mdl_sol = self.da_market.em.mdl_sol

    def simulate(self):
        """ Runs a test simulation with options specified """
        # Initialized necessary parameters
        horizon_reached = False
        time = self.start
        # Run the simulation until the finish
        while not horizon_reached:
            # First clear DA
            self.da_market.clear_market(local_save=self.save)
            if not self.da_only:
                rt_minutes = self.rt_market.em.configuration['time']['min_freq']
                num_rt_intervals = int(24 * 60 / rt_minutes)
                # Send commitment and storage soc to RT
                self._pass_da_to_rt()
                # Run all RT test instances for this day
                for icnt in range(num_rt_intervals):
                    self.rt_market.clear_market(local_save=self.save)
                # Increment time and see if the end horizon is reached
            time += datetime.timedelta(days=1)
            if time >= self.end:
                horizon_reached = True

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

def create_market(mtype='da', start=None, end=None, filename=None, seed=None):
    """ Builds a market instance """
    uncertainty_data_provider = UncertaintyProvider(market_type=mtype, filename=filename, seed=seed)
    em = pyen.EnergyMarket(uncertainty_data_provider)
    market_timing = get_market_timing(mtype)
    # Format start/end as strings so they will work in osw_market.py
    if not isinstance(start, str):
        start = f'{start.year}-{start.month:02d}-{start.day:02d}'
    if not isinstance(end, str):
        end = f'{end.year}-{end.month:02d}-{end.day:02d}'
    # Reset the timing parameters for RT
    if mtype == 'da':
        market = da_market.OSWDAMarket(start, end, market_timing=market_timing, market=em)
    elif mtype == 'rt':
        market = rt_market.OSWRTMarket(start, end, market_timing=market_timing, market=em)
    return market

def main(options):
    """ Runs a market instance with the given options """
    # Creates a market operator
    operator = MarketOperator(options)
    # Runs the simulation
    operator.simulate()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-s", "--start_time", help="Start time in YYYYmmddHHMM format",
                        default='202005010000')
    parser.add_argument("-e", "--end_time", help="End time in YYYYmmddHHMM format",
                        default='202005020000')
    parser.add_argument("-f", "--filename", help="Name (with path) to egret model_data file",
                        default='../../../../egret/egret/models/tests/uc_test_instances/five_bus.json')
    parser.add_argument("-d", "--seed", help="Integer random seed", type=int, default=9425)
    parser.add_argument("--da_only", help="If included, will only run the day-ahead market", action='store_true')
    args = parser.parse_args()
    options = args.__dict__
    options.update({'save':True})
    main(options)

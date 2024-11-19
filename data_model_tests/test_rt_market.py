#%%
import datetime
import json
import logging
import os
import sys
import pandas
from datetime import datetime, timedelta

from egret.data.model_data import ModelData
from egret.models.unit_commitment import solve_unit_commitment, SlackType
import pyenergymarket as pyen


logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.ERROR)

#%%
def format_filename(datetime_str):
    return datetime_str.replace(':', '-').replace(' ', '_')
#%%
rt_market_timing = {
        "states": {
            "idle": {
                "start_time": 0,
                "duration": 600 # 10 minutes
            },
            "bidding": {
                "start_time": 600, # from 10 min
                "duration": 180 # to 13 min
            },
            "clearing": {
                "start_time": 780, # from 13 min
                "duration": 120 # to 15 min
            }
        },
        "initial_offset": 0,
        "initial_state": "idle",
        "market_interval": 900
    }

market_timing = {  #"da": da_market_timing, 
                    #"reserves": da_market_timing,
                    "rt": rt_market_timing}

#%%
h5filepath = "/Users/camp426/github/pyenergymarket/WECC240_20240807.h5"
default = {
    "time": {
        "datefrom": "2032-02-01"
    },
    "interpolate": {
        "method": None #None, zero -- options in scipy.interpolate
    },
    "simulation": {
        "thermal_model": "cost", # this is the default
    },
    "elements": {
        "branch":{
            "rating_long_term": "A",
            "rating_short_term": "A",
            "rating_emergency": "B"
        },
        "generator": {
            "generator_type_map":{
                "storage": [3, 10]
            },
            "renewable_type_override": {3: "Solar"},
            "ignore_non_fuel_startup": False,
            "scale_fuel_cost": 1.0
        }
    }
}
#%%
loglevel = "INFO"
solver = "gurobi" # "gurobi" or "cbc"
svname = 'rt_test.json'
gv = pyen.GVParse(h5filepath, default=default, logger_options={"level": loglevel})

#%%
pyenconfig = {
    "time": {
        "datefrom": "2032-01-01 00:00:00", # whole year
        "dateto": "2032-01-02 00:00:00",
        'min_freq':15, # 15 minutes
        'window':1,
        'lookahead':1
    },
    "solve_arguments": {
        "kwargs":{
            "solver_tee": True # change to False to remove some logging
        }
    }
}
#%%

markets = {}
em = pyen.EnergyMarket(gv, pyenconfig)

#%%
em.market_timing = rt_market_timing
#%%
testdir = '/Users/camp426/github/pyenergymarket/data_model_tests/realtime_out'
if not os.path.exists(testdir):
    os.makedirs(testdir)


#%%


current_date = pyenconfig['time']['datefrom']
while current_date < pyenconfig['time']['dateto']:
    em.get_model(current_date) 
    em.solve_model()
    em.save_model(
        os.path.join(testdir,
                     'rt_'+format_filename(current_date)+'.json')
    )
    current_date = (datetime.strptime(current_date,'%Y-%m-%d %H:%M:%S') + 
                     timedelta(minutes = 
                               pyenconfig['time']['min_freq']*
                               pyenconfig['time']['window'])).strftime('%Y-%m-%d %H:%M:%S')


#%%

# %%

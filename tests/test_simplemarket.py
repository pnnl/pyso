import os
from pyenergymarket.marketmodels.market import Market
from pyenergymarket import EnergyMarket
from pyenergymarket.parsers.egretparser import EgretProvider

THIS_DIR = os.path.split(__file__)[0]

datapath = os.path.join(THIS_DIR, "tiny_uc_2.json")

egretprovide = EgretProvider(datapath)

## This should run 4 instances of the market sequentially.


## initialize Market Engine
emconfig = {"time": {"window": 6, "min_freq": 60, "lookahead": 3},
            "solve_arguments": {
                "solver": "gurobi",
                "slack": "TRANSMISSION_LIMITS",
                "kwargs":{
                        "mipgap": 0.01,
                        "solver_tee": True,
                        "timelimit": 300,
                        }
            }
        }
em = EnergyMarket(EgretProvider, config=emconfig)


market_timing = {
        "states": {
            "idle": {
                "start_time": 0,
                "duration": 0,
                "unit": "hour"
            },
            "bidding": {
                "start_time": 0,
                "duration": 0,
                "unit": "hour"
            },
            "clearing": {
                "start_time": 0,
                "duration": em.config["time"]["window"], ## note: this should be automatic
                "unit": "hour"
            },
        },
        "initial_offset": 0,
        "initial_state": "idle",
        "market_interval": 6
    }

start_time = "2025-12-10 00:00:00"
end_time = "2025-12-10 23:00:00"
market = Market("test_market", market_timing, start_time, end_time, em, local_save=True)
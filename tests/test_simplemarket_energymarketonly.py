import pytest
import os
import pandas as pd
from pyenergymarket import EnergyMarket
from pyenergymarket.parsers.egretparser import EgretProvider
from egret.data.model_data import ModelData

THIS_DIR = os.path.split(__file__)[0]

def test_simple_iteration():
    
    datapath = os.path.join(THIS_DIR, "tiny_uc_2.json")

    egretprovider = EgretProvider(datapath)

    ## initialize Market Engine
    ## This should run 4 instances of the market sequentially.
    emconfig = {"time": {"window": 6, "min_freq": 60, "lookahead": 3},
                "solve_arguments": {
                    "solver": "cbc",
                    "slack": "TRANSMISSION_LIMITS",
                    "kwargs":{
                            "mipgap": 0.01,
                            "solver_tee": False,
                            "timelimit": 300,
                            }
                },
                # "logging": {
                #     "file": "test_simplemarket.log"
                # }
            }
    em = EnergyMarket(egretprovider, config=emconfig)


    start_time = "2025-12-10 00:00:00"
    end_time = "2025-12-10 23:00:00"


    ### Main loop
    ts = pd.Timestamp(start_time)
    te = pd.Timestamp(end_time)
    while True:
        print(f"Running starting at time {ts}")
        ## get the model
        em.get_model(ts)

        ## update initial conditions
        em.update_initial_conditions()
        
        ## solve
        em.solve_model()
        
        ## save
        em.save_model(os.path.join(THIS_DIR, f'test_market_results_{ts.strftime("%Y-%m-%dT%H")}.json'))

        ## step time
        ts += pd.Timedelta(minutes=em.configuration["time"]["window"]*em.configuration["time"]["min_freq"])
        if ts > te:
            break

    t = pd.date_range(start_time, end_time, freq="1h")
    for i in range(3):
        md = ModelData(os.path.join(THIS_DIR, f'test_market_results_{t[i*6].strftime("%Y-%m-%dT%H")}.json'))
        assert md.data["system"]["time_keys"] == [f"{s}" for s in t[(i*6):(i*6 + 9)]]

    ## last one has a limited range
    md = ModelData(os.path.join(THIS_DIR, f'test_market_results_{t[3*6].strftime("%Y-%m-%dT%H")}.json'))
    assert md.data["system"]["time_keys"] == [f"{s}" for s in t[18:]]

    #remove files
    for i in range(4):
        os.remove(os.path.join(THIS_DIR, f'test_market_results_{t[i*6].strftime("%Y-%m-%dT%H")}.json'))

# ## solve single shot model
# em.configuration["time"]["window"] = 24
# em.configuration["time"]["lookahead"] = 0

# em.get_model(start_time)
# em.solve_model()
# em.save_model(f"test_market_result_singleshot.json")
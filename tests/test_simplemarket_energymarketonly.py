import os

import pandas as pd
from egret.data.model_data import ModelData
from utilities import find_solver

from pyso import EnergyMarket
from pyso.parsers.egretparser import EgretProvider

THIS_DIR = os.path.split(__file__)[0]


def test_simple_iteration():
    datapath = os.path.join(THIS_DIR, "testdata", "tiny_uc_2.json")

    egretprovider = EgretProvider(datapath)
    solver = find_solver()

    ## initialize Market Engine
    ## This should run 4 instances of the market sequentially.
    emconfig = {
        "time": {"window": 6, "min_freq": 60, "lookahead": 3},
        "solve_arguments": {
            "solver": solver,
            "slack": "TRANSMISSION_LIMITS",
            "kwargs": {
                "mipgap": 0.01,
                "solver_tee": False,
                "timelimit": 300,
            },
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
        # Format timestamp for filename
        timestamp = ts.strftime("%Y-%m-%dT%H")
        save_path = os.path.join(THIS_DIR, f"test_market_results_{timestamp}.json")
        em.save_model(save_path)

        ## step time
        # Calculate time step based on window and frequency
        minutes = em.configuration["time"]["window"] * em.configuration["time"]["min_freq"]
        ts += pd.Timedelta(minutes=minutes)
        if ts > te:
            break

    t = pd.date_range(start_time, end_time, freq="1h")
    for i in range(3):
        # Format timestamp for model data loading
        timestamp = t[i * 6].strftime("%Y-%m-%dT%H")
        model_path = os.path.join(THIS_DIR, f"test_market_results_{timestamp}.json")
        md = ModelData(model_path)
        assert md.data["system"]["time_keys"] == [f"{s}" for s in t[(i * 6) : (i * 6 + 9)]]

    ## last one has a limited range
    # Load the last model data
    timestamp = t[3 * 6].strftime("%Y-%m-%dT%H")
    model_path = os.path.join(THIS_DIR, f"test_market_results_{timestamp}.json")
    md = ModelData(model_path)
    assert md.data["system"]["time_keys"] == [f"{s}" for s in t[18:]]

    # remove files
    for i in range(4):
        # Clean up test file
        timestamp = t[i * 6].strftime("%Y-%m-%dT%H")
        file_path = os.path.join(THIS_DIR, f"test_market_results_{timestamp}.json")
        os.remove(file_path)


# ## solve single shot model
# em.configuration["time"]["window"] = 24
# em.configuration["time"]["lookahead"] = 0

# em.get_model(start_time)
# em.solve_model()
# em.save_model(f"test_market_result_singleshot.json")

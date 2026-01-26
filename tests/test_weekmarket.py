import os

import numpy as np
from egret.data.model_data import ModelData
from utilities import find_solver

from pyenergymarket import EnergyMarket
from pyenergymarket.marketmodels.market import BasicMarket
from pyenergymarket.parsers.egretparser import EgretProvider
from pyenergymarket.utils.timeutils import count_onoff

THIS_DIR = os.path.split(__file__)[0]


def setup_market():
    """Market configuration including reference model, solver arguments, and timing"""
    datapath = os.path.join(THIS_DIR, "testdata", "week_uc_2.json")

    egretprovider = EgretProvider(datapath)
    solver = find_solver()

    ## initialize Market Engine
    emconfig = {
        "time": {"window": 24, "min_freq": 60, "lookahead": 24},
        "solve_arguments": {
            "solver": solver,
            "slack": "TRANSMISSION_LIMITS",
            "kwargs": {
                "mipgap": 0.01,
                "solver_tee": True,
                "timelimit": 300,
            },
        },
    }
    em = EnergyMarket(egretprovider, config=emconfig)

    market_timing = {"market_interval": em.configuration["time"]["window"],
                     "time_unit": "hour",
                     "timing":[
                          {"name": "bidding", "start_time": 0},
                          {"name": "clearing", "start_time": 1},
                          {"name": "idle", "start_time": 2}
                     ]
                     }

    start_time = "2025-12-10 00:00:00"
    end_time = "2025-12-17 23:00:00"
    market = BasicMarket("test_week_market", market_timing, start_time, end_time, em,
                         local_save={"save": True, "path": THIS_DIR, "ext": ".json"})
    return market


def sequential_pass_testing(fstart, ndays=6):
    """Loops through a week and verifies that the starting conditions for each day
    (except the first) are derived from the ending of the previous day
    """
    for day in range(ndays):
        # Open the given day
        # with open(os.path.join(THIS_DIR, f"{fstart}_{day}.json")) as f:
        #     first_solution = json.load(f)
        first_solution = ModelData(os.path.join(THIS_DIR, f"{fstart}_{day}.json"))
        # Open the next day
        # with open(os.path.join(THIS_DIR, f"{fstart}_{day + 1}.json")) as f:
        #     second_solution = json.load(f)
        second_solution = ModelData(os.path.join(THIS_DIR, f"{fstart}_{day + 1}.json"))
        # Check that initial power from day 2 come from the end of day1
        tstart = second_solution.data["system"]["time_keys"][0]
        tend = int(np.argmin(np.array(first_solution.data["system"]["time_keys"]) < tstart)) - 1
        # for g in second_solution["elements"]["generator"]:
        for g, gdict in second_solution.elements("generator"):
            # Check power
            # p_init = second_solution["elements"]["generator"][g]["initial_p_output"]
            p_init = gdict["initial_p_output"]
            p_end = first_solution.data["elements"]["generator"][g]["pg"]["values"][tend]
            assert p_init == p_end, (
                f"Initial power on day {day + 1} does not match final power from day {day} "
                f"for generator {g}."
            )
            # Check status
            # s_init = second_solution["elements"]["generator"][g]["initial_status"]
            s_init = gdict["initial_status"]
            s_end = count_onoff(first_solution.data["elements"]["generator"][g], 23)
            assert s_init == s_end, (
                f"Initial status on day {day + 1} does not match final status on day {day} "
                f"for generator {g}."
            )

    files = os.listdir(THIS_DIR)
    for file in files:
        if file.endswith(".json") and file.startswith(fstart):
            os.remove(os.path.join(THIS_DIR, file))


def test_weekmarket():
    market = setup_market()
    # Set up a loop to run through a day and check results
    for t in market.market_loop():
        market.current_time = t
    # simulate(market)
    # This checks that data is passed between results, then deletes the files
    sequential_pass_testing("test_week_market_results")


if __name__ == "__main__":
    test_weekmarket()

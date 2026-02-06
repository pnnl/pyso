import os

import pandas as pd
import pytest
from egret.data.model_data import ModelData
from utilities import dictionary_testing, find_solver

from pyso import EnergyMarket
from pyso.marketmodels.market import BasicMarket
from pyso.parsers.egretparser import EgretProvider

THIS_DIR = os.path.split(__file__)[0]


@pytest.fixture
def market(request):
    """Market configuration including reference model, solver arguments, and timing"""

    name = request.param

    datapath = os.path.join(THIS_DIR, "testdata", "tiny_uc_2.json")

    egretprovider = EgretProvider(datapath)
    solver = find_solver()

    ## This should run 4 instances of the market sequentially.

    ## initialize Market Engine
    emconfig = {
        "time": {"window": 6, "min_freq": 60, "lookahead": 3},
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
    if name == "tz":
        ## add timezone
        emconfig["time"]["tz"] = "US/Eastern"

    em = EnergyMarket(egretprovider, config=emconfig)

    ## the most important thing about the the timing is that bidding is a 0,
    ## which is where the model is built. Therefore, as setup, the current solution
    ## should start at the provided start time.
    market_timing = {
        "market_interval": em.configuration["time"]["window"],
        "time_unit": "hour",
        "timing": [
            {"name": "bidding", "start_time": 0},
            {"name": "clearing", "start_time": 1},
            {"name": "idle", "start_time": 2},
        ],
    }

    if name == "normal":
        start_time = "2025-12-10 00:00:00"
        end_time = "2025-12-11 00:00:00"
    elif name == "tz":
        start_time = "2025-12-09 19:00"
        end_time = "2025-12-10 19:00"
    market = BasicMarket(
        "test_market",
        market_timing,
        start_time,
        end_time,
        em,
        local_save={"save": True, "path": THIS_DIR, "ext": ".json"},
    )
    return market


@pytest.mark.parametrize("market", ["normal", "tz"], indirect=True)
def test_simplemarket(market):
    # market = setup_market()
    # # Set up a loop to run through a day and check results
    # simulate(market, save_testdata=save_testdata)
    for t in market.market_loop():
        market.current_time = t
    # We set this up with 4 tests so we should see these results
    for cnt in range(4):
        # with open(os.path.join(THIS_DIR, "testdata", f"test_market_results_{cnt}.json")) as f:
        testdata = ModelData(os.path.join(THIS_DIR, "testdata", f"test_market_results_{cnt}.json"))
        # with open(os.path.join(THIS_DIR, f"test_market_results_{cnt}.json.gz")) as f:
        localdata = ModelData(os.path.join(THIS_DIR, f"test_market_results_{cnt}.json"))

        expected_time_keys = pd.date_range(
            start=pd.Timestamp("2025-12-10 00:00:00") + cnt * pd.Timedelta(hours=6),
            end=min(
                pd.Timestamp("2025-12-11 00:00:00"),
                pd.Timestamp("2025-12-10 00:00:00")
                + cnt * pd.Timedelta(hours=6)
                + pd.Timedelta(hours=9),
            ),
            freq="1h",
            inclusive="left",
        )

        ## test that the time keys are correct
        assert localdata.data["system"]["time_keys"] == [
            f"{s}" for s in expected_time_keys
        ], f"model {cnt} doesn't match {expected_time_keys}"
        # Compare reference files (testdata) to locally generated files (localdata)
        dictionary_testing(testdata.data, localdata.data)
        # Remove local results
        os.remove(os.path.join(THIS_DIR, f"test_market_results_{cnt}.json"))


if __name__ == "__main__":
    # Can run as python script to generate new results
    test_simplemarket(save_testdata=True)

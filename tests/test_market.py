import os

import pandas as pd
import pytest
from utilities import find_solver

from pyso import EnergyMarket
from pyso.marketmodels.market import AbstractMarket
from pyso.parsers.egretparser import EgretProvider

THIS_DIR = os.path.split(__file__)[0]


class NoActionMarket(AbstractMarket):
    def __init__(
        self,
        market_name,
        market_timing,
        start_date,
        end_date,
        market,
        logging=None,
        history_maxlen=10,
        **kwargs,
    ):
        if logging is None:
            logging = {"level": "DEBUG"}
        super().__init__(
            market_name,
            market_timing,
            start_date,
            end_date,
            market,
            logging,
            history_maxlen,
            **kwargs,
        )

    def do_initialization(self, *args, **kwargs):
        self.logger.debug(f"[do_initialization] callback at time {self.current_time}")

    def do_finalization(self, *args, **kwargs):
        self.logger.debug(f"[do_finalization] callback at time {self.current_time}")

    def collect_bids(self, event):
        self.logger.debug(f"[collect_bids] callback at time {self.current_time}")

    def publish_results(self, event):
        self.logger.debug(f"[publish_results] callback at time {self.current_time}")

    def clear_market(self, event):
        self.logger.debug(f"[clear_market] callback at time {self.current_time}")


def setup_market():
    """Market configuration including reference model, solver arguments, and timing"""
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
    em = EnergyMarket(egretprovider, config=emconfig)

    market_timing = {
        "market_interval": emconfig["time"]["window"],
        "time_unit": "hour",
        "timing": [
            {"name": "bidding", "start_time": 0},
            {"name": "clearing", "start_time": 2},
            {"name": "idle", "start_time": 4},
        ],
        # "timing": [
        #     {"name": "clearing",
        #     "start_time": 0 },
        #     {"name": "idle",
        #     "start_time": 2},
        #     {"name": "bidding",
        #     "start_time": 4}
        # ]
    }

    start_time = "2025-12-10 00:00:00"
    end_time = "2025-12-11 00:00:00"
    market = NoActionMarket(
        "test_market", market_timing, start_time, end_time, em, history_maxlen=20
    )

    output = [
        {"time": pd.Timestamp(start_time), "source": "initialization", "dest": "bidding"},
        {
            "time": pd.Timestamp(start_time) + pd.Timedelta(hours=2),
            "source": "bidding",
            "dest": "clearing",
        },
        {
            "time": pd.Timestamp(start_time) + pd.Timedelta(hours=4),
            "source": "clearing",
            "dest": "idle",
        },
        {
            "time": pd.Timestamp(start_time) + pd.Timedelta(hours=6),
            "source": "idle",
            "dest": "bidding",
        },
        {
            "time": pd.Timestamp(start_time) + pd.Timedelta(hours=8),
            "source": "bidding",
            "dest": "clearing",
        },
        {
            "time": pd.Timestamp(start_time) + pd.Timedelta(hours=10),
            "source": "clearing",
            "dest": "idle",
        },
        {
            "time": pd.Timestamp(start_time) + pd.Timedelta(hours=12),
            "source": "idle",
            "dest": "bidding",
        },
        {
            "time": pd.Timestamp(start_time) + pd.Timedelta(hours=14),
            "source": "bidding",
            "dest": "clearing",
        },
        {
            "time": pd.Timestamp(start_time) + pd.Timedelta(hours=16),
            "source": "clearing",
            "dest": "idle",
        },
        {
            "time": pd.Timestamp(start_time) + pd.Timedelta(hours=18),
            "source": "idle",
            "dest": "bidding",
        },
        {
            "time": pd.Timestamp(start_time) + pd.Timedelta(hours=20),
            "source": "bidding",
            "dest": "clearing",
        },
        {
            "time": pd.Timestamp(start_time) + pd.Timedelta(hours=22),
            "source": "clearing",
            "dest": "idle",
        },
        {
            "time": pd.Timestamp(start_time) + pd.Timedelta(hours=24),
            "source": "idle",
            "dest": "finalization",
        },
    ]

    return market, list(reversed(output))


@pytest.mark.parametrize("res", [None, pd.Timedelta(hours=1)])
def test_simplemarket(res):
    market, output = setup_market()
    # for t in pd.date_range(market.start_time, market.end_time, freq="1h"):
    for t in market.market_loop(res=res):
        market.current_time = t
    assert list(market.history) == output


if __name__ == "__main__":
    # Can run as python script to generate new results
    history, output = test_simplemarket(save_testdata=True)

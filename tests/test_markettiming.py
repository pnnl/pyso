from pyenergymarket.marketmodels.market import MarketTiming
import pandas as pd


def test_market_timing_int():
    market_timing = {
        "market_interval": 24,
        "timing": [
            {"name": "clearing",
            "start_time": 0 },
            {"name": "idle",
            "start_time": 3},
            {"name": "bidding",
             "start_time": 21}
        ]
    }
    mt = MarketTiming(**market_timing)
    assert mt.state_list == ["clearing", "idle", "bidding"]
    assert mt["clearing"]["duration"] == 3
    assert mt["idle"]["duration"] == 18
    assert mt["bidding"]["duration"] == 3

def test_market_timing_timedelta():
    market_timing = {
        "market_interval": pd.Timedelta(24, unit="h"),
        "timing": [
            {"name": "clearing",
            "start_time": pd.Timedelta(0, unit="h") },
            {"name": "idle",
            "start_time": pd.Timedelta(3, unit="h")},
            {"name": "bidding",
             "start_time": pd.Timedelta(21, unit="h")}
        ]
    }
    mt = MarketTiming(**market_timing)
    assert mt.state_list == ["clearing", "idle", "bidding"]
    assert mt["clearing"]["duration"] == pd.Timedelta(3, unit="h")
    assert mt["idle"]["duration"] == pd.Timedelta(18, unit="h")
    assert mt["bidding"]["duration"] == pd.Timedelta(3, unit="h")
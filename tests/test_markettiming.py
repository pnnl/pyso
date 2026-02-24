import pandas as pd
import pytest

from pyso.marketmodels.market import MarketTiming


@pytest.fixture
def market_timing(request):
    name = request.param
    # build different data depending on name
    if name == "int":
        mt = {
            "market_interval": 24,
            # "start_time": "2024-01-01",
            # "end_time": "2025-01-01",
            "timing": [
                {"name": "clearing", "start_time": 0},
                {"name": "idle", "start_time": 3},
                {"name": "bidding", "start_time": 21},
            ],
        }
    elif name == "timedelta":
        mt = {
            "market_interval": pd.Timedelta(24, unit="h"),
            # "start_time": "2024-01-01",
            # "end_time": "2025-01-01",
            "timing": [
                {"name": "clearing", "start_time": pd.Timedelta(0, unit="h")},
                {"name": "idle", "start_time": pd.Timedelta(3, unit="h")},
                {"name": "bidding", "start_time": pd.Timedelta(21, unit="h")},
            ],
        }
    return mt


@pytest.mark.parametrize("market_timing", ["int", "timedelta"], indirect=True)
def test_market_timing(market_timing):
    mt = MarketTiming(**market_timing)
    assert mt.state_list == ["clearing", "idle", "bidding"]
    assert mt["clearing"]["duration"] == pd.Timedelta(3, unit="h")
    assert mt["idle"]["duration"] == pd.Timedelta(18, unit="h")
    assert mt["bidding"]["duration"] == pd.Timedelta(3, unit="h")
    # assert mt.market_iterations == 366 # leap year

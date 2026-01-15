import os, json
from pyenergymarket.marketmodels.market import Market
from pyenergymarket import EnergyMarket
from pyenergymarket.parsers.egretparser import EgretProvider
from utilities import dictionary_testing, find_solver

THIS_DIR = os.path.split(__file__)[0]

def setup_market():
    """ Market configuration including reference model, solver arguments, and timing """
    datapath = os.path.join(THIS_DIR, "testdata", "tiny_uc_2_ET.json")

    egretprovider = EgretProvider(datapath)
    solver = find_solver()

    ## This should run 4 instances of the market sequentially.

    ## initialize Market Engine
    emconfig = {"time": {"window": 6, "min_freq": 60, "lookahead": 3, "tz": "US/Eastern"},
                "solve_arguments": {
                    "solver": solver,
                    "slack": "TRANSMISSION_LIMITS",
                    "kwargs":{
                            "mipgap": 0.01,
                            "solver_tee": True,
                            "timelimit": 300,
                            }
                }
            }
    em = EnergyMarket(egretprovider, config=emconfig)

    market_timing = {
            "states": {
                "clearing": {
                    "start_time": 0,
                    "duration": 1,
                    "unit": "hour"
                },
                "idle": {
                    "start_time": 1,
                    "duration": 4,
                    "unit": "hour"
                },
                "bidding": {
                    "start_time": 5,
                    "duration": 1,
                    "unit": "hour"
                },
            },
            "initial_offset": 0,
            "initial_state": "idle",
            "market_interval": em.configuration["time"]["window"]
        }

    start_time = "2025-12-10 00:00:00"
    end_time = "2025-12-10 23:00:00"
    market = Market("test_market", market_timing, start_time, end_time, em)
    return market

def simulate(market, save_testdata=False):
    """ Runs a test simulation with options specified """
    horizon_reached = False
    # Run the simulation until the market end horizon is reached
    cnt = 0
    simulation_time = 0
    while not horizon_reached:
        market_cleared = run_market(market, simulation_time)
        if market_cleared:
            if save_testdata:
                market.em.save_model(os.path.join(THIS_DIR, 'testdata', f'test_market_results_{cnt}.json'))
            market.em.save_model(os.path.join(THIS_DIR, f'test_market_results_{cnt}.json'))
            cnt += 1
        # Increment time by one hour
        simulation_time += 1
        if simulation_time >= 24:
            horizon_reached = True

def run_market(market, simulation_time):
    """ Uses the market transition methods to clear the market
    Returns:
        market_cleared (bool): True if a market was run, otherwise False
    """
    # Selects the market object from the saved dictionary
    market_cleared = False
    # First check if we have hit a transition point (simulation time == next state time)
    if simulation_time == market.next_state_time:
        # Advance the market state
        market.move_to_next_state()
        # If we are in clearing, adjust return boolean
        if market.current_state == 'clearing':
            market_cleared = True
        # Updates the market.next_state_time
        market.update_market()
    return market_cleared

def test_simplemarket(save_testdata=False):
    market = setup_market()
    # Set up a loop to run through a day and check results
    simulate(market, save_testdata=save_testdata)
    # We set this up with 4 tests so we should see these results
    for cnt in range(4):
        with open(os.path.join(THIS_DIR, 'testdata', f'test_market_results_{cnt}.json')) as f:
            testdata = json.load(f)
        with open(os.path.join(THIS_DIR, f'test_market_results_{cnt}.json')) as f:
            localdata = json.load(f)
        # Compare reference files (testdata) to locally generated files (localdata)
        # comparing only elements output since the time keys were saved in UTC.
        dictionary_testing(testdata["elements"], localdata["elements"])
        # Remove local results
        os.remove(os.path.join(THIS_DIR, f'test_market_results_{cnt}.json'))

if __name__ == '__main__':
    # Can run as python script to generate new results
    test_simplemarket(save_testdata=True)
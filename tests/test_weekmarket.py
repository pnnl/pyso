import os, json
import numpy as np
from pyenergymarket.marketmodels.market import Market
from pyenergymarket import EnergyMarket
from pyenergymarket.parsers.egretparser import EgretProvider
from pyenergymarket.utils.timeutils import count_onoff
from utilities import dictionary_testing, find_solver

THIS_DIR = os.path.split(__file__)[0]

def setup_market():
    """ Market configuration including reference model, solver arguments, and timing """
    datapath = os.path.join(THIS_DIR, "testdata", "week_uc_2.json")

    egretprovider = EgretProvider(datapath)
    solver = find_solver()

    ## This should run 4 instances of the market sequentially.

    ## initialize Market Engine
    emconfig = {"time": {"window": 24, "min_freq": 60, "lookahead": 24},
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
                    "duration": 3,
                    "unit": "hour"
                },
                "idle": {
                    "start_time": 3,
                    "duration": 18,
                    "unit": "hour"
                },
                "bidding": {
                    "start_time": 21,
                    "duration": 3,
                    "unit": "hour"
                },

            },
            "initial_offset": 0,
            "initial_state": "idle",
            "market_interval": em.configuration["time"]["window"]
        }

    start_time = "2025-12-10 00:00:00"
    end_time = "2025-12-17 23:00:00"
    market = Market("test_week_market", market_timing, start_time, end_time, em)
    return market

def simulate(market):
    """ Runs a test simulation with options specified """
    horizon_reached = False
    # Run the simulation until the market end horizon is reached
    cnt = 0
    simulation_time = 0
    while not horizon_reached:
        market_cleared = run_market(market, simulation_time)
        if market_cleared:
            market.em.save_model(os.path.join(THIS_DIR, f'test_week_market_results_{cnt}.json'))
            cnt += 1
        # Increment time by one hour
        simulation_time += 1
        if simulation_time >= 24*7:
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

def sequential_pass_testing(fstart, ndays=6):
    """ Loops through a week and verifies that the starting conditions for each day
        (except the first) are derived from the ending of the previous day
    """
    for day in range(ndays):
        # Open the given day
        with open(f'{fstart}_{day}.json', 'r') as f:
            first_solution = json.load(f)
        # Open the next day
        with open(f'{fstart}_{day+1}.json', 'r') as f:
            second_solution = json.load(f)
        # Check that initial power from day 2 come from the end of day1
        tstart = second_solution['system']['time_keys'][0]
        tend = int(np.argmin(np.array(first_solution['system']['time_keys']) < tstart)) - 1
        for g in second_solution['elements']['generator']:
            # Check power
            p_init = second_solution['elements']['generator'][g]['initial_p_output']
            p_end = first_solution['elements']['generator'][g]['pg']['values'][tend]
            assert p_init == p_end, (f"Initial power on day {day+1} does not match final power from day {day} "
                                     f"for generator {g}.")
            # Check status
            s_init = second_solution['elements']['generator'][g]['initial_status']
            s_end = count_onoff(first_solution['elements']['generator'][g], 23)
            assert s_init == s_end, (f"Initial status on day {day+1} does not match final status on day {day} "
                                     f"for generator {g}.")

    files = os.listdir(THIS_DIR)
    for file in files:
        if file.endswith('.json') and file.startswith(fstart):
            os.remove(os.path.join(THIS_DIR, file))

def test_weekmarket():
    market = setup_market()
    # Set up a loop to run through a day and check results
    simulate(market)
    # This checks that data is passed between results, then deletes the files
    sequential_pass_testing('test_week_market_results')

if __name__ == '__main__':
    test_weekmarket()
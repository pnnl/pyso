# Dictionary of Egret/optimization solver options
solve_args_dict = {"solver": "gurobi_persistent",
                   "kwargs": {
                       "solver_options": {
                            "ConcurrentMethod": 0,
                            "Method": 3,
                            "MIPFocus": 1,
                            "CutPasses": 2
                       },
                       "ptdf_options": {
                           "rel_ptdf_tol": 0.0,
                           "abs_ptdf_tol": 1e-07,
                           "abs_flow_tol": 0.001,
                           "rel_flow_tol": 0.0,
                           "branch_kv_threshold": 100.0,
                           "kv_threshold_type": "both",
                           "max_violations_per_iteration": 20
                       }
                   }}

# Dictionary with market information needed to construct market_timing and em_config
market_info = {"daily": {"interval": 24, "lookahead": 24, "time_resolution": 1, "time_unit": "hour",
                           "state_starts": {"clearing": 0,
                                            "idle": 3,
                                            "bidding": 21,},
                           "initial_offset": 0,
                           "initial_state": "idle",
                           },
                 "weekly": {"interval": 168, "lookahead": 24, "time_resolution": 4, "time_unit": "hour",
                           "state_starts": {"clearing": 0,
                                            "idle": 4,
                                            "bidding": 160,},
                           "initial_offset": 0,
                           "initial_state": "idle",
                           }
                 }

# Order in which markets will be executed if they share a common start time
market_order = ["weekly", "daily"]

def build_market_timing(market_options):
    """ Builds a market_timing dictionary compatible with market.py """
    # Add initial keys
    market_timing = {"states":{},
                     "initial_offset": market_options["initial_offset"],
                     "initial_state": market_options["initial_state"],
                     "market_interval": market_options["interval"],}
    # Find min/max state start times (to be used in setting duration for the final state
    min_start_time = min(market_options["state_starts"].values())
    max_start_time = max(market_options["state_starts"].values())
    # Loop through all states and add start_time/duration to state dict
    for state, start_time in market_options["state_starts"].items():
        # Last state duration is time to end of interval, plus wrap time to the min_start_time
        if start_time == max_start_time:
            duration = market_options["interval"] - start_time + min_start_time
        else:
            # Next start time is smallest time greater than the current start time
            next_start_time = min([st for st in market_options["state_starts"].values() if st > start_time])
            duration = next_start_time - start_time
        market_timing["states"][state] = {"start_time": start_time, "duration": duration}

    return market_timing

def build_em_config(market_options):
    """ Builds an em_config dictionary compatible with engine.py EnergyMarket object """
    # Build em timing dictionary
    # Note that window/lookahead are in units of INTERVALS (not time)
    scaling_options = {'second': 1/60, 'minute': 1, 'hour': 60, 'day': 1440, 'year': 525600}
    time_dict = {"min_freq": int(market_options["time_resolution"] * scaling_options[market_options["time_unit"]]),
                 "window": int(market_options["interval"] / market_options["time_resolution"]),
                 "lookahead": int(market_options["lookahead"] / market_options["time_resolution"]),
                 }
    # Config is the time dictionary and the solve arguments dictionary
    em_config = {"time": time_dict,
                 "solve_arguments": solve_args_dict,}

    return em_config

def get_defaults():
    """ Returns a default configuration based on the dictionaries defined above """
    default_options = { "start_time": "", # Start time in YYYYmmddHHMM format (e.g. 202401010000)
                        "end_time": "", # End time in YYYYmmddHHMM format (e.g. 202401080000)
                        "filename": "", # Path to Egret date
                        "case": None, # Optional name to append to save directory
                        "time_resolution": 1,
                        "time_unit": "hour",
                        "save": True,
                        "market_order": market_order,}
    # Loop through the markets and add timing/configuration info for each
    market_dict = {}
    for market in market_order:
        market_timing = build_market_timing(market_info[market])
        em_config = build_em_config(market_info[market])
        market_dict[market] = {"market_timing": market_timing, "em_config": em_config}
    default_options["markets"] = market_dict

    return default_options
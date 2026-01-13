# Dictionary of Egret/optimization solver options
solve_args_dict = { "solve_arguments": {
                        "solver": "gurobi_persistent",
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
                    }

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
    market_timing = {}

    return market_timing

def build_em_config(market_options):
    """ Builds an em_config dictionary compatible with engine.py EnergyMarket object """
    em_config = {}

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

{
    "start_time": "202401010000",
    "end_time": "202401080000",
    "filename": "../../../../pcm-data-pipeline/output",
    "case": null,
    "time_resolution": 1,
    "time_unit": "hour",
    "save": true,
    "market_order": [
        "weekly",
        "daily"
    ],
    "markets": {
        "daily": {
            "market_timing": {
                "states": {
                    "clearing": {
                        "start_time": 0,
                        "duration": 3
                    },
                    "idle": {
                        "start_time": 3,
                        "duration": 18
                    },
                    "bidding": {
                        "start_time": 21,
                        "duration": 3
                    }
                },
                "initial_offset": 0,
                "initial_state": "idle",
                "market_interval": 24
            },
            "em_config": {
                "time": {
                    "min_freq": 60,
                    "window": 24,
                    "lookahead": 24
                },
                "solve_arguments": {
                    "solver": "gurobi_persistent",
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
                    }
                }
            }
        },
        "weekly": {
            "market_timing": {
                "states": {
                    "clearing": {
                        "start_time": 0,
                        "duration": 4
                    },
                    "idle": {
                        "start_time": 4,
                        "duration": 184
                    },
                    "bidding": {
                        "start_time": 188,
                        "duration": 4
                    }
                },
                "initial_offset": 0,
                "initial_state": "idle",
                "market_interval": 192
            },
            "em_config": {
                "time": {
                    "min_freq": 240,
                    "window": 42,
                    "lookahead": 6
                },

                }
            }
        }
    }
}
energymarket_defaults = {
    "time": {
        "datefrom": None,
        "dateto": None,
        "min_freq": 60, # period length in minutes
        "window": 24, # solution window
        "lookahead": 0 # solution lookahead
    },
    "simulation": {
        "price_model": "lmp", # can be "lmp" (fix commitment), 
                                      #"achp" (approximate convex hull, relax binary),
                                      # None (don't calculate prices)
    },
    "solve_arguments": {
        "solver": "gurobi",
        "slack": "TRANSMISSION_LIMITS",
        "kwargs":{
            "mipgap": 0.01,
            "solver_tee": True,
            "timelimit": 300,
        }
    },
    "logging": {
        "name": "pyenergy",
        "level": "INFO",
        "msg_format": "{message}",
        "file": None
    }
}
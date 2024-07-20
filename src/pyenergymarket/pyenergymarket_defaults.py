energymarket_defaults = {
    "time": {
        "datefrom": None,
        "dateto": None,
        "window": None, # solution window, if non the datefrom-dateto will be used
        "lookahead": 0 # solution lookahead
    },
    "simulation": {
        "price_model": "lmp", # can be "lmp" (fix commitment), 
                                      #"achp" (approximate convex hull, relax binary),
                                      # "none" (don't calculate prices)
    },
    "solve_arguments": {
        "solver": "gurobi",
        "slack": "TRANSMISSION_LIMITS",
        "kwargs":{
            "mipgap": 0.01,
            "solver_tee": True,
            "timelimit": 300,
        }
    }
}
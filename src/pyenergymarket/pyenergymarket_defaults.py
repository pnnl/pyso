energymarket_defaults = {    
    "time": {
        "datefrom": None,
        "dateto": None,
        "min_freq": 60, # period length in minutes
        "window": 24, # solution window
        "lookahead": 0, # solution lookahead
        "datefrom": "2032-01-01"
    },
    "interpolate": {
        "method": 'zero' # options in scipy.interpolate
    },
    "simulation": {
        "price_model": "lmp", # can be "lmp" (fix commitment), 
                                      #"achp" (approximate convex hull, relax binary),
                                      # None (don't calculate prices)
        "thermal_model": "cost" # this is the default
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
    },
    "elements": {
        "branch":{
            "rating_long_term": "A",
            "rating_short_term": "A",
            "rating_emergency": "B"
        },
        "generator": {
            "generator_type_map":{
                "storage": [3, 10]
            },
            "renewable_type_override": {3: "Solar"},
            "ignore_non_fuel_startup": False,
            "scale_fuel_cost": 1.0
        }
    }
}
gvdefaults = {
    "time": {
        "datefrom": None,
        "dateto": None,
        "min_freq": 60,
        "periods": 24
    },
    "simulation": {
        "thermal_model": "cost", # can be "cost" or "fuel". if cost, will convert fuel.
    },
    "reactive_power": {
        "include": False, # if true parse reactive data
        "default_pf": {# default reactive capability (hopefully overwritten by PF model data)
            "thermal": 0.95,
            "renewable": 1.0,
            "other": 0.95
        },
        "renewable2thermal_fixed": True #True means q limits are with respect to name plate NOT with respect to variable p max
    },
    "elements": {
        "bus": {
            "v_min": 0.95,
            "v_max": 1.05
        },
        "branch": {
            "angle_diff_min": -360,
            "angle_diff_max": 360,
            "rating_long_term": "A",
            "rating_short_term": "A",
            "rating_emergency": "B"
        },
        "generator": {
            "generator_type_map":{
                "thermal": [1],
                "hydro": [2],
                "storage": [3],
                "renewable": [4]
            },
            ### parameters mainly for debugging purposes
            "renewable_type_override": {},
            "ignore_non_fuel_startup": False,
            "scale_fuel_cost": 1
        }
    }
}
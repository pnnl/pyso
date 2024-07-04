gvdefaults = {
    "time": {
        "datefrom": None,
        "dateto": None
    },
    "simulation": {
        "thermal_model": "cost" # can be "cost" or "fuel". if cost, will convert fuel.
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
            }
        }
    }
}
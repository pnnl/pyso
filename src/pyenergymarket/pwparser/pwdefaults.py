pwdefaults = {
    "shunts":{
        "remove_existing": True,
        "shunt_type_map": {
            "Bus Shunt": "fixed",
            "SVC": "variable",
            "Discrete": "variable",
            "Continuous": "variable",
            "Fixed": "fixed",
            "Line Shunt": "fixed"
        },
        "make_variable": {
            "Bus Shunt": True,
            "Fixed": True,
            "Line Shunt": True
        },
    },
    "logging": {
        "name": "pwparser",
        "level": "INFO",
        "msg_format": "{message}",
        "file": None
    },
    "generation": {
        "include_qg": True # True includes reactive power setpoint
    },
    "bus": {
        "update_voltage": True, # update vm and va set points from power flow case
        "min_acceptable_voltage": 0.7,
        "max_acceptable_voltage": 1.3
    }
}
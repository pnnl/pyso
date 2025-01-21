import pyenergymarket as pyen
import numpy as np
from egret.data.model_data import ModelData
from utilities import dictionary_testing


def run_energymarket():

    h5path = r"\\PNL\Projects\ECOMP\Shared Data\H5Files\WECC240_20240807.h5"
    loglevel = "INFO"
    
    ### setup gridview parsing
    gvconfig = {
        "simulation": {
            "thermal_model": "cost", # this is the default
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
                "ignore_non_fuel_startup": False
            }
        }
    }

    gv = pyen.GVParse(h5path, default=gvconfig, logger_options={"level": loglevel})
    
    
    ### setup PyEnergyMarket
    pyenconfig = {
        "time": {
            "datefrom": None,
            "dateto": None,
            "min_freq": 15, # period length in minutes
            "window": 1, # solution window
            "lookahead": 1 # solution lookahead
        },
        "solve_arguments": {
            "kwargs":{
                "solver_tee": True # change to False to remove some
            }
        }
    }
    
    em =pyen.EnergyMarket(gv, config=pyenconfig)
    
    # ### get model for the specified time range
    em.get_model("2032-01-31 23:00:00")
    
    return em


def save_energymarket():
    em = run_energymarket()
    # sol = ModelData.read()
    em.save_model("test_fuelcurve_solution.json")



def test_energymarket():

    em = run_energymarket()
    solpath = r"\\PNL\Projects\ECOMP\Shared Data\PyEnergyMarketTestData\test_fuelcurve_solution.json"
    sol = ModelData.read(solpath)

    # assert em.mdl.data == sol.data

    # assert em.mdl.data["elements"]["generator"]["FULTON_3531_CE"] == approx(sol.data["elements"]["generator"]["FULTON_3531_CE"])
    dictionary_testing(em.mdl.data["elements"]["generator"]["FULTON_3531_CE"]["p_cost"],
                       sol.data["elements"]["generator"]["FULTON_3531_CE"]["p_cost"])
    # assert em.mdl.data["elements"]["generator"]["FULTON_3531_CE"]["p_cost"]["values"] == approx(sol.data["elements"]["generator"]["FULTON_3531_CE"]["p_cost"]["values"])

if __name__ == "__main__":
    save_energymarket()
import pyenergymarket as pyen
import numpy as np
from egret.data.model_data import ModelData
from utilities import os_safe_networkpath

def run_energymarket():

    h5path = os_safe_networkpath(r"\\PNL\Projects\ECOMP\Shared Data\H5Files\WECC240_20240807.h5")
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
            "datefrom": "2032-02-01",
            "dateto": "2032-02-01"
        },
        "solve_arguments": {
            "kwargs":{
                "solver_tee": True # change to False to remove some
            }
        }
    }
    
    em =pyen.EnergyMarket(gv, config=pyenconfig)
    
    ### get model for the specified time range
    em.get_model(pyenconfig["time"]["datefrom"])

    ### solve model
    em.solve_model()
    
    return em


def save_energymarket():
    em = run_energymarket()
    # sol = ModelData.read()
    em.save_model("test_energymarket_solution.json")

def test_energymarket():

    em = run_energymarket()
    solpath = os_safe_networkpath(r"\\PNL\Projects\ECOMP\Shared Data\PyEnergyMarketTestData\test_energymarket_solution.json")
    sol = ModelData.read(solpath)

    cost1 = em.mdl_sol.data["system"]["total_cost"]
    mipgap = em.configuration["solve_arguments"]["kwargs"]["mipgap"]
    cost2 = sol.data["system"]["total_cost"]

    ### assert that solution is less than mipgap compared to saved solution
    assert np.abs(cost1 - cost2)/cost2 <= mipgap

if __name__ == "__main__":
    save_energymarket()
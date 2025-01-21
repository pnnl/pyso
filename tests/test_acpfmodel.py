import pyenergymarket as pyen
import pandas as pd
import sys
from egret.data.model_data import ModelData
from utilities import dictionary_testing

def main():
    # logfile = "wecc_test_parsing.log"
    # h5path = r"C:\Users\schw197\OneDrive - PNNL\Documents\02Projects\ECOMP\data\s1_r10_bnd_pcm_0302_2024_fixed_dupli.h5"
    h5path = r"\\PNL\Projects\ECOMP\Shared Data\H5Files\WECC240_20240807.h5"

    ## setup model to include reactive power
    gvconfig = {
        "simulation": {
            "thermal_model": "cost", # this is the default
            "include_solution_vars": True
        },
        "reactive_power":{"include": True},
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
            },
            "dc_branch": {
                "include_dispatch": True
            }
        }
    }

    gv = pyen.GVParse(h5path, default=gvconfig) #Data Provider

    ## setup PyEnergyMarket to take just a single hour
    pyenconfig = {
            "time": {
                "min_freq": 60, # period length in minutes
                "window": 1, # solution window
                "lookahead": 0 # solution lookahead
            }
        }
    em =pyen.EnergyMarket(gv, config=pyenconfig) #PyEnergyMarket

    em.get_model("2032-02-01 10:00") # Get a single hour model

    ### flatten distributed generators (if any)
    pyen.utils.egretutils.flatten_distributed_generators(em.mdl)

    ### Setup PowerWorld Parsing
    pwbpath = r"\\PNL\Projects\ECOMP\Shared Data\PyEnergyMarketTestData\240busWECC_2018_PSS.pwb"
    pw = pyen.PWParse(pwbpath, config={"logging": {"level": "INFO"}})
    
    pw.logger.info("\nPower World Parsing\n===========================\n")
    pw.update_model(em.mdl)
    return em

def save_model():
    em = main()
    em.save_model("test_acpfmodel_solution.json")

def test_acpfmodel():
    em = main()
    solpath = r"\\PNL\Projects\ECOMP\Shared Data\PyEnergyMarketTestData\test_acpfmodel_solution.json"
    sol = ModelData.read(solpath)

    dictionary_testing(em.mdl.data, sol.data)

if __name__ == "__main__":
    save_model()


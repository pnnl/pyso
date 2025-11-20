import pyenergymarket as pyen
import pandas as pd
import sys, os
from egret.data.model_data import ModelData
from utilities import dictionary_testing
import platform
import pytest

def get_h5path():
    h5path = os.path.join(os.path.dirname(__file__), "localdata", "WECC240_20240807.h5")
    return h5path

def get_pwdpath():
    h5path = os.path.join(os.path.dirname(__file__), "localdata", "240busWECC_2018_PSS.pwb")
    return h5path

def get_solpath():
    solpath = os.path.join(os.path.dirname(__file__), "localdata", "test_acpfmodel_solution.json")
    return solpath


def main():
    h5path = get_h5path()

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
    pwbpath = get_pwdpath()
    pw = pyen.PWParse(pwbpath, config={"logging": {"level": "INFO"}})
    
    pw.logger.info("\nPower World Parsing\n===========================\n")
    pw.update_model(em.mdl)
    pw.sa.close()
    pw.logger.info("Finished Power World Parsing.")
    return em

@pytest.fixture
def get_data():
    if platform.system() == 'Windows': 
        return main()
    else:
        return None

def save_model():
    em = main()
    em.save_model("test_acpfmodel_solution.json")

def test_acpfmodel(get_data):
    if platform.system() == 'Windows':
        em = get_data
        em.logger.info("Finished Parsing Model.")
        solpath = get_solpath()
        sol = ModelData.read(solpath)

        em.logger.info("Starting Comparison")
        dictionary_testing(em.mdl.data, sol.data)

if __name__ == "__main__":
    save_model()


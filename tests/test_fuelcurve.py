import pyenergymarket as pyen
import os
from egret.data.model_data import ModelData
from utilities import dictionary_testing
from gridtune.pcm import H5
import pytest

def get_h5path():
    h5path = os.path.join(os.path.dirname(__file__), "localdata", "WECC240_20240807.h5")
    return h5path

def get_solpath():
    solpath = os.path.join(os.path.dirname(__file__), "localdata", "test_fuelcurve_solution.json")
    return solpath

@pytest.mark.local
class TestPySO:

    def run_energymarket(self):

        h5path = get_h5path()
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

        gv = pyen.GVParse(h5path, default=gvconfig)

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
        em.get_model("2032-01-31 23:45:00")

        return em

    def save_energymarket(self):
        em = self.run_energymarket()
        # sol = ModelData.read()
        os.makedirs('localdata', exist_ok=True)
        em.save_model(os.path.join("localdata","test_fuelcurve_solution.json"))

    def test_energymarket(self):

        em = self.run_energymarket()
        solpath = get_solpath()
        sol = ModelData.read(solpath)

        # assert em.mdl.data == sol.data

        # assert em.mdl.data["elements"]["generator"]["FULTON_3531_CE"] == approx(sol.data["elements"]["generator"]["FULTON_3531_CE"])
        dictionary_testing(em.mdl.data["elements"]["generator"]["FULTON_3531_CE"]["p_cost"],
                           sol.data["elements"]["generator"]["FULTON_3531_CE"]["p_cost"])
        # assert em.mdl.data["elements"]["generator"]["FULTON_3531_CE"]["p_cost"]["values"] == approx(sol.data["elements"]["generator"]["FULTON_3531_CE"]["p_cost"]["values"])

if __name__ == "__main__":
    obj = TestPySO()
    obj.save_energymarket()
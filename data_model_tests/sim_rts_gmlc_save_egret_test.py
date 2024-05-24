from prescient.simulator import Prescient
import argparse
from types import ModuleType
from egret.data.model_data import ModelData
from prescient.simulator.data_manager import RucPlan
import os
# from pyomo.common.config import ConfigDict


def save_ruc_data(prescient_options, simulator, deterministic_ruc_instance:ModelData, ruc_date, ruc_hour):
    # Try going into debug mode here to find the right way to get modelData out of the ruc instance
    i = 0
    fname = f"ruc_modeldata{i}.json"
    while os.path.exists(fname):
        i += 1
        fname = f"ruc_modeldata{i}.json"
    deterministic_ruc_instance.write(fname)

def save_ruc_sol(prescient_options, simulator, ruc_plan:RucPlan, ruc_date, ruc_hour):
    """save data moel after solution"""
    i = 0
    fname = f"ruc_solved_modeldata{i}.json"
    while os.path.exists(fname):
        i +=1
        fname = f"ruc_solved_modeldata{i}.json"
    ruc_plan.deterministic_ruc_instance.write(fname)

def save_sced_data(prescient_options, simulator, deterministic_sced_instance:ModelData):
    # Try going into debug mode here to find the right way to get modelData out of the sced instance
    i = 0
    fname = f"sced_modeldata{i}.json"
    while os.path.exists(fname):
        i += 1
        fname = f"sced_modeldata{i}.json"

    deterministic_sced_instance.write(fname)

def save_sced_sol(prescient_options, simulator, deterministic_sced_instance:ModelData, deterministic_pricing_model:ModelData):
    # Try going into debug mode here to find the right way to get modelData out of the sced instance
    i = 0
    fname = f"sced_solved_modeldata{i}.json"
    fname2 = f"sced_pricing_modeldata{i}.json"
    while os.path.exists(fname):
        i += 1
        fname = f"sced_solved_modeldata{i}.json"
        fname2 = f"sced_pricing_modeldata{i}.json"

    deterministic_sced_instance.write(fname)
    deterministic_pricing_model.write(fname2)

def get_configuration(key:str):
    return None

def register_plugins(context, options, plugin_config):
    context.register_before_ruc_solve_callback(save_ruc_data)
    context.register_after_ruc_generation_callback(save_ruc_sol)
    context.register_before_operations_solve_callback(save_sced_data)
    context.register_after_operations_callback(save_sced_sol)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="test prescient")
    parser.add_argument("solver", nargs="?", choices=["gurobi", "cbc", "scip"], help="solver to use", default="gurobi")
    parser.add_argument("--data-path", help="data path to RTS-GMLC/RTS_Data/SourceData/", default="../../Prescient/downloads/rts_gmlc/RTS-GMLC/RTS_Data/SourceData/")
    args = parser.parse_args()
    # set some options
    prescient_options = {
            "data_path":args.data_path,
            "input_format":"rts-gmlc",
            "simulate_out_of_sample":True,
            "run_sced_with_persistent_forecast_errors":True,
            "output_directory":"rts_gmlc_output",
            "start_date":"07-10-2020",
            "num_days":1,
            "sced_horizon":1,
            "ruc_mipgap":0.01,
            "reserve_factor":0.1,
            "deterministic_ruc_solver":"gurobi",
            "deterministic_ruc_solver_options":{"feas":"off", "DivingF":"on",},
            "sced_solver":"gurobi",
            "sced_frequency_minutes":60,
            "ruc_horizon":36,
            "compute_market_settlements":True,
            "monitor_all_contingencies":False,
            "output_solver_logs":False,
            "price_threshold":1000,
            "contingency_price_threshold":100,
            "reserve_price_threshold":5,
            }
    # run the simulator
    # try:
    module = ModuleType("PrintEgret")
    module.register_plugins = register_plugins
    module.get_configuration = get_configuration

    prescient_options["deterministic_ruc_solver"] = args.solver
    prescient_options["sced_solver"] = args.solver
    prescient_options["plugin"] = {
        "PrintEgret":{
            "module": module
        }
    }
    p = Prescient()
    p.simulate(**prescient_options)
    # except RuntimeError:
    #     prescient_options["deterministic_ruc_solver"] = "cbc"
    #     prescient_options["sced_solver"] = "cbc"
    #     Prescient().simulate(**prescient_options)

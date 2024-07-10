
import os, sys
import argparse
import numpy as np
import pandas as pd

from egret.data.model_data import ModelData
from egret.viz.generate_graphs import generate_stack_graph

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="look at egret solution")
    parser.add_argument("--json", help="path solved json", default="gv2egret_test_solution.json")
    args = parser.parse_args()
    
    this_module_path = os.path.dirname(os.path.abspath(__file__))
    
    print(f"loading {args.json}")
    
    md = ModelData.read(os.path.join(this_module_path, args.json))

    print("Non Zero Thermal Generators")
    for n, g in md.elements("generator", generator_type="thermal"):
        if np.any(np.array(g["pg"]["values"]) > 0):
            print(f'Generator {n} of type {g["unit_type"]} and fuel {g["fuel"]}')


    #### energy balance
    gen_total = 0
    for n, g in md.elements("generator"):
        gen_total += np.array(g["pg"]["values"])
    
    load_total = 0
    for n, l in md.elements("load"):
        load_total += np.array(l["p_load"]["values"])

    load_total_bus = 0
    p_balance_violation = 0
    for n, b in md.elements("bus"):
        load_total_bus += np.array(b["pl"]["values"])
        p_balance_violation += np.array(b["p_balance_violation"]["values"])
        if np.any(np.abs(np.array(b["p_balance_violation"]["values"])) > 1e-3):
            print(f"Bus {n} has non negligible p_balance_violation")


    df = pd.DataFrame({"gen_total": gen_total, "load_total": load_total, "load_total_bus": load_total_bus, "p_balance_violation": p_balance_violation})

    print(df)

    generate_stack_graph(md, save_fig="investigate_solution.png")


    #### branches
    flows = {}
    for n, b in md.elements("branch"):
        flows[n] = b["pf"]["values"]
    
    flows = pd.DataFrame(flows)
    print(flows)

    ##### renewables
    curtailment = {"Wind": 0, "Solar": 0, "Hydro": 0} 
    for n, g in md.elements("generator", generator_type="renewable"): 
        if isinstance(g["p_max"], dict):
            curt = np.array(g["p_max"]["values"]) - np.array(g["pg"]["values"])
        else:
            print(f"Generator {n} doesn't have p_max as dictionary")
            curt = g["p_max"] - np.array(g["pg"]["values"])
        if np.abs(curt).max() > 1e-3:
            print(f"Generator {n} has non negligible curtailment.")
        curtailment[g["fuel"]] += curt
    curtailment = pd.DataFrame(curtailment)
    print("Curtailment")
    print(curtailment)

    



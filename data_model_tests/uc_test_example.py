
## Copy of uc_test_example modified to point at the generated output from parsing 
## GridView
import os, argparse

from egret.data.model_data import ModelData
from egret.models.unit_commitment import solve_unit_commitment, SlackType

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="solve model")
    # parser.add_argument("--json", help="path solved json", default="gv2egret_test_fuelmode.json")
    parser.add_argument("--json", help="path solved json", default="rts_gmlc_output/prescient_egret_json/ruc_modeldata0.json")
    parser.add_argument("--solver", help="choice of solver", choices=["gurobi", "cbc"], default="gurobi")
    args = parser.parse_args()
    
    jsonfilebase, ext = os.path.splitext(args.json)
    this_module_path = os.path.dirname(os.path.abspath(__file__))
    ## Create an Egret "ModelData" object, which is just a lightweight
    ## wrapper around a python dictionary, from an Egret json test instance
    print(f'Creating and Solving {args.json}')
    md = ModelData.read(os.path.join(this_module_path, args.json))

    ## solve the unit commitment instance using solver gurobi
    md_sol = solve_unit_commitment(md, args.solver, slack_type=SlackType.TRANSMISSION_LIMITS,
                                   mipgap=0.01,
                                   timelimit=300, solver_tee=True)
    print('Solved!')

    ## print the objective value to the screen
    print('Objective value:', md_sol.data['system']['total_cost'])

    ## write the solution to an Egret *.json file
    md_sol.write(os.path.join(this_module_path, f'{jsonfilebase}_solution.json'))
    print(f'Wrote solution to {jsonfilebase}_solution.json')

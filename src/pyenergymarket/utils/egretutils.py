"""Utilities related to handling egret models
"""
from egret.data.model_data import ModelData
from copy import deepcopy

def get_bus_id(md:ModelData, bus:str, field="id") -> int:
    """Under the ASSUMPTION that a field was added to the Egret
    model that stores an integer reference to the bus, this function
    extracts that integer given the bus key in the elements["bus"]
    dictionary

    Args:
        md (ModelData): Egret model
        bus (str): bus key in elements["bus"]
        field (str, optional): fields where integer is stored. Defaults to "id".

    Returns:
        int: bus integer identifier
    """
    return md.data["elements"]["bus"][bus][field]

def flatten_distributed_generators(md:ModelData):
    """Convert all distributed generators to individual generators
    There is an assumption that an id field exists that stores generator unit IDs

    Args:
        md (ModelData): Egret model to convert
    """
    #################################
    #### SETUP 
    #################################
    #### helper functions
    def scale_time_series(ts:dict, scale:float):
        tmp = {"data_type": "time_series"}
        if isinstance(ts["values"], dict):
            tmp["values"] = {k: scale*v for k,v in ts["values"].items()}
        elif isinstance(ts["values"], list):
            tmp["values"] = [scale*v for v in ts["values"]]
        else:
            raise ValueError(f"scale_time_series: expected values key of time series to be either dict or str but got {type(ts['values'])}")
    
    def scale_cost_curve(cc:dict, scale:float):
        tmp = {"data_type": "cost_curve", "cost_curve_type": cc["cost_curve_type"]}
        if cc["cost_curve_type"] == "piecewise":
            ## scale both output and cost
            tmp["values"] = [(scale*gen, scale*cost) for gen, cost in cc["values"]]
        elif cc["cost_curve_type"] == "polynomial":
            ## scale coefficients
            tmp["values"] = {k: scale*v for k,v in cc["values"].items()}
    def scale_fuel_curve(fc:dict, scale:float):
        tmp = {"data_type": "fuel_curve"}
        ## scale both output and fuel
        tmp["values"] = [(scale*gen, scale*fuel) for gen, fuel in fc["values"]]
    
    ## Do not scale these
    exclude_keys = ["power_factor", "in_service", 
                    "min_up_time", "min_down_time", 
                    "initial_status", "fuel_cost"
                    "agc_marginal_cost", "spinning_cost", "non_spinning_cost",
                    "supplemental_cost",
                    "regulation_provider",
                    "fixed_commitment", "fixed_regulation", "commitment",
                    "fuel_supply", "aux_fuel_supply", "aux_fuel_cost",
                    "aux_fuel_status",
                    "unit_type", "gv_generatorkey"
                    ]
    
    ############################################
    ###### Main loop
    ############################################
    new_gen = {}
    remove_gens = []
    for g, g_dict in md.elements("generator"):
        if not isinstance(g_dict["bus"], dict):
            # not a distributed generator
            continue
        remove_gens.append(g)
        for bus, frac in g_dict["bus"]:
            ### copy parameter dictionary
            tmp = deepcopy(g_dict)
            ### update bus and generator ID
            tmp["bus"] = bus
            id = g_dict["id"][bus] ## NOTE: Not standard EGRET!!
            tmp["id"] = id

            ### scale parameteres
            for k, v in g_dict.items():
                if isinstance(v, str) or isinstance(v, bool):
                    ## nothing to split
                    continue
                if k in exclude_keys:
                    continue
                if isinstance(v,dict):
                    if v["data_type"] == "time_series":
                        tmp[k] = scale_time_series(v, frac)
                    elif v["data_type"] == "cost_curve":
                        tmp[k] = scale_cost_curve(v, frac)
                    elif v["data_type"] == "fuel_curve":
                        tmp[k] = scale_fuel_curve(v, frac)
                    else:
                        raise KeyError(f"flatten_distributed_generators: unknown data type for generator {g} key {k}")
            ### collect generator
            new_gen[f"{g}_{bus}_{id}"] = tmp
    
    ##### remove generators
    for g in remove_gens:
        md.data["elements"]["generator"].pop(g)
    
    ##### add new generators
    md.data["elements"]["generator"].update(new_gen)



            
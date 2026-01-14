"""Utilities related to handling egret models
"""
from egret.data.model_data import ModelData
from copy import deepcopy
import json
import numpy as np
import networkx as nx
import pandas as pd
from typing import Union

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

def get_bus_from_id(md:ModelData, busid:int, field="id") -> str:
    """Reverse to get_bus_id. Under the ASSUMPTION that a field was added
    to the Egret model that stores an integer reference to the bus, this function
    returns the bus key that is associated with this integer

    Args:
        md (ModelData): Egret model
        busid (int): integer bus number
        field (str, optional): field where integer bus number is stored. Defaults to "id".

    Returns:
        str: the bus key in the Egret model
    """
    for bus, b_dict in md.elements("bus"):
        if b_dict[field] == busid:
            return bus

##TODO: when there are two generators distributing to a single unit (CC 2 on 1 for example)
## this generates multiple units, that should be combined in some manner
def flatten_distributed_generators(md:ModelData, key="generator"):
    """Convert all distributed generators to individual generators
    There is an assumption that an id field exists that stores generator unit IDs

    Args:
        md (ModelData): Egret model to convert
    """
    #################################
    #### SETUP 
    #################################
    #### helper functions
    def scale_time_series(ts:dict, scale:float) -> dict:
        tmp = {"data_type": "time_series"}
        if isinstance(ts["values"], dict):
            tmp["values"] = {k: scale*v for k,v in ts["values"].items()}
        elif isinstance(ts["values"], list):
            tmp["values"] = [scale*v for v in ts["values"]]
        else:
            raise ValueError(f"scale_time_series: expected values key of time series to be either dict or str but got {type(ts['values'])}")
        return tmp
    
    def scale_cost_curve(cc:dict, scale:float) -> dict:
        tmp = {"data_type": "cost_curve", "cost_curve_type": cc["cost_curve_type"]}
        if cc["cost_curve_type"] == "piecewise":
            ## scale both output and cost
            tmp["values"] = [(scale*gen, scale*cost) for gen, cost in cc["values"]]
        elif cc["cost_curve_type"] == "polynomial":
            ## scale coefficients
            tmp["values"] = {k: scale*v for k,v in cc["values"].items()}
        return tmp
    def scale_fuel_curve(fc:dict, scale:float) -> dict:
        tmp = {"data_type": "fuel_curve"}
        ## scale both output and fuel
        tmp["values"] = [(scale*gen, scale*fuel) for gen, fuel in fc["values"]]
        return tmp
    ## Do not scale these
    exclude_keys = ["power_factor", "in_service", "zone", "area",
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
    for g, g_dict in md.elements(key):
        if not isinstance(g_dict["bus"], dict):
            # not a distributed generator
            continue
        remove_gens.append(g)
        dist_key = "bus_id" if "bus_id" in g_dict else "bus"
        for buskey, frac in g_dict[dist_key].items():
            ### copy parameter dictionary
            tmp = deepcopy(g_dict)
            ### update bus and generator ID
            if dist_key == "bus_id":
                ## split the last _ by reversing the string
                id,bus = buskey[::-1].split("_", maxsplit=1)
                ## undo the reverse
                bus = bus[::-1]
                id = id[::-1]
            else:
                bus = buskey
                id = g_dict["id"][bus] ## NOTE: Not standard EGRET!!
            tmp["bus"] = bus
            tmp["id"] = id

            ### scale parameteres
            for k, v in g_dict.items():
                if isinstance(v, str) or isinstance(v, bool):
                    ## nothing to split
                    continue
                if k in exclude_keys + ["bus", "id", "bus_id"]:
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
                elif isinstance(v, list):
                    if ("startup_cost" in k) or ("startup_fuel" in k):
                        tmp[k] = [(hr, val*frac) for (hr, val) in v]
                    else:
                        raise TypeError(f"flatten_distributed_generators: unknown data type {type(v)} for property {k}: {v}.")
                elif isinstance(v, (float, np.floating, int, np.integer)):
                    tmp[k] = frac*v
                else:
                    raise TypeError(f"flatten_distributed_generators: unknown data type {type(v)} for property {k}: {v}.")
            ### collect generator
            new_gen[f"{g}_{bus}_{id}"] = tmp
    
    ##### remove generators
    for g in remove_gens:
        md.data["elements"][key].pop(g)
    
    ##### add new generators
    md.data["elements"][key].update(new_gen)


def sum_properties(a:Union[float, dict], b:Union[float,dict]):

    if not isinstance(a, type(b)):
        raise TypeError("sum_properities: the two properties should be of the same type")
    
    if isinstance(a,dict):
        return {"data_type": "time_series", "values": [i+j for i,j in zip(a["values"],b["values"])]}
    else:
        return a + b

def get_total_load(md:ModelData):
    out = None
    for l, l_dict in md.elements("load"):
        if out is None:
            out = l_dict["p_load"]
        else:
            out = sum_properties(out, l_dict["p_load"])
    return out

def get_total_gen(md:ModelData):
    out = None
    for g, g_dict in md.elements("generator"):
        if out is None:
            out = g_dict["pg"]
        else:
            out = sum_properties(out, g_dict["pg"])
    return out

def merge_model_data(md1:ModelData, md2:ModelData, ts_keep='md2'):
    """ Merges all time series elements within two model data objects and returns the result
        Non-time series elements will be drawn from md1

    Args:
        md1 (ModelData): The first model data object
        md2 (ModelData): The second model data object
        ts_keep (str, optional): If md1 and md2 have common time keys, specifies which time series to keep.
    Returns:
        md_merge (ModelData): The merged model data object
    """

    def find_common_times(md1:dict, md2:dict, ts_keep:str):
        times1 = md1['system']['time_keys']
        times2 = md2['system']['time_keys']
        common_times, i1, i2 = np.intersect1d(times1, times2, return_indices=True)
        # If no overlap, return None
        if len(common_times) == 0:
            return None
        if ts_keep == 'md1':
            idx_pivot = i2[-1] # If keeping md1, we will omit all i2 up to the last overlap
        else:
            idx_pivot = i1[0] # If keeping md2, we will omit all i1 after the first overlap
        return idx_pivot

    def index_merge(list1:list, list2:list, idx:Union[int, None], ts_keep:str):
        """ If idx is not None, use ts_keep to determine which values to use for common times"""
        if idx is not None:
            if ts_keep == 'md1':
                list2 = list2[idx:]
            else:
                list1 = list1[:idx]
        return list1, list2

    def merge_elements(md1:dict, md2:dict, idx:Union[int,None], ts_keep:str):
        """ Loops through all elements and merges any time series """
        for element in md1['elements'].keys():
            for elem_name in md1['elements'][element].keys():
                for elem_char, elem_dict in md1['elements'][element][elem_name].items():
                    # Check if this is an Egret-formatted time series
                    if isinstance(elem_dict, dict):
                        if 'data_type' in elem_dict.keys() and elem_dict['data_type'] == "time_series":
                            md1_values = deepcopy(elem_dict['values'])
                            md2_values = deepcopy(md2['elements'][element][elem_name][elem_char]['values'])
                            # Handle any overlapping time
                            md1_values, md2_values = index_merge(md1_values, md2_values, idx, ts_keep)
                            # Add md2 values and assign to the dictionary
                            md1_values.extend(md2_values)
                            elem_dict['values'] = md1_values
        return md1

    def merge_system(md1:dict, md2:dict, idx:Union[int, None], ts_keep:str):
        """ Loops through all system keys and merges any time series """
        # First, merge time_keys itself
        md1_times, md2_times = deepcopy(md1['system']['time_keys']), deepcopy(md2['system']['time_keys'])
        # Handle any overlapping time
        md1_times, md2_times = index_merge(md1_times, md2_times, idx, ts_keep)
        md1_times.extend(md2_times)
        md1['system']['time_keys'] = md1_times
        for sys_key, sys_value in md1['system'].items():
            if isinstance(sys_value, dict):
                if 'data_type' in sys_value.keys() and sys_value['data_type'] == "time_series":
                    md1_values = deepcopy(sys_value['values'])
                    md2_values = deepcopy(md2['system'][sys_key]['values'])
                    # Handle any overlapping time
                    md1_values, md2_values = index_merge(md1_values, md2_values, idx, ts_keep)
                    # Add md2 values and re-assign
                    md1_values.extend(md2_values)
                    sys_value['values'] = md1_values
        return md1

    md1_data, md2_data = md1.data, md2.data
    # We require md1 to come before md2 in the time series. Check this and if false, switch order
    t01 = md1_data['system']['time_keys'][0]
    t02 = md2_data['system']['time_keys'][0]
    if t02 < t01:
        md1_data, md2_data = md2.data, md1.data
    md_merged_data = deepcopy(md1_data)

    # Check if there are any shared times. Depending on ts_keep, this will select the start/end index
    # of the list that won't be kept
    idx_pivot = find_common_times(md1_data, md2_data, ts_keep)
    md_merged_data = merge_elements(md_merged_data, md2_data, idx_pivot, ts_keep)
    md_merged_data = merge_system(md_merged_data, md2_data, idx_pivot, ts_keep)

    md_merged = ModelData(md_merged_data)
    return md_merged


class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, np.bool_):
            return bool(obj)
        else:
            return super(NumpyEncoder, self).default(obj) 


def get_networkx_graph(md:ModelData) -> nx.Graph:
    """Create network x graph model of the model data.
    
    Note: 
        there is a version of this in Egret but it is more restrictive
    and raises an error when there are parallel lines. Also, this version
    includes dc_branch components

    Args:
        md (ModelData): egret model

    Returns:
        nx.Graph: Graph representation
    """
    ### AC branch attributes
    branch_attrs = md.attributes(element_type='branch')
    idx = branch_attrs.pop("names")
    df = pd.DataFrame(branch_attrs, index=idx)
    G : nx.Graph = nx.from_pandas_edgelist(df, source="from_bus", target="to_bus", 
                                    edge_attr=True)
    ### DC branch attributes
    if "dc_branch" in md.data["elements"].keys():
        dc_attributes = md.attributes(element_type="dc_branch")
        dc_idx = dc_attributes.pop("names")
        dfdc = pd.DataFrame(dc_attributes, index=dc_idx)
        ## update Graph
        G.update(nx.from_pandas_edgelist(dfdc, source="from_bus", target="to_bus", edge_attr=True))
    
    return G
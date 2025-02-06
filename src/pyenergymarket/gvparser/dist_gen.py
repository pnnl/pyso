from __future__ import annotations
import pandas as pd
import numpy as np
import copy

### This is for type checking and syntax highlighting
### see: https://www.youtube.com/watch?v=UnKa_t-M_kM
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .__init__ import GVParse

def is_distgen(self:GVParse, genkey:int) -> str:
    """Check if generator is a distributed generator.
    Returns empty string if it is not, otherwise, returns type
    "BUS", "AREA", or "BTM".

    Args:
        genkey (int): generator key

    Returns:
        str: type of distributed generator ("" is none)
    """
    

    ### GenerationDistribution Table
    try:
        disttab = self.h5("/mdb/GenerationDistribution")
        tmp = disttab.loc[lambda x: (x["GeneratorKey"] == genkey) & (x["Type"] == "AREA")]
        if not tmp.empty:
            ## generation distributed to area load
            return "AREA"
        tmp = disttab.loc[lambda x: (x["GeneratorKey"] == genkey) & (x["Type"] == "BUS")]
        if not tmp.empty:
            ## generation distributed to several buses
            return "BUS"
    except KeyError:
        pass
    
    ### BTMGenLoadMapping Table
    try:
        disttab = self.h5("/mdb/BTMGenLoadMapping")
        tmp = disttab.loc[lambda x: x["GeneratorKey"] == genkey]
        if not tmp.empty:
            return "BTM"
    except KeyError:
        pass
    
    ### genkey no non of the distribution tables
    return ""

def bus_distgen(self:GVParse, genkey:int, tmp:dict):
    """Update generator parameters for distributed generators.
    the bus fields needs to be a dictionary bus->fraction
    the id field (not used by egret directly) is a dictionary bus->generator ID

    Args:
        genkey (int): generator key
        tmp (dict): parameter dictionary
    """

    ### distributed generator table
    disttab = self.h5("/mdb/GenerationDistribution").loc[lambda x: x["GeneratorKey"] == genkey]
    ### create a dictionary with keys=bus names, values=fraction
    tmp["bus"] = dict()
    tmp["id"] = dict()
    tmp["bus_id"]  = dict() #key by bus And ID for potential flattening
    for b, i, v in zip(disttab["Name"].astype(int), disttab["GeneratorID"], disttab["Percentage"]):
        if self.include_bus(b):
            bus_str = self.mk_bus_str(b)
            tmp["bus_id"][f"{bus_str}_{i}"] = v
            if bus_str in tmp["bus"]:
                tmp["bus"][bus_str] += v
            else:
                tmp["bus"][bus_str] = v
                tmp["id"][bus_str]  = i
    if len(tmp["bus"]) == 0:
        raise ValueError(f"bus_distgen: distributed generator with genkey {genkey} is not distributed to any of the included buses!")
    s = sum(tmp["bus"].values())
    if np.abs(s - 1.0) > self.dist_gen_tol:
        self.logger.warning(f"WARNING: components of distributed generator with genkey {genkey} don't sum to 1 ({s:.2e}, tol={self.dist_gen_tol:.2e}). Adjusting weights.")
        ## re-normalize
        for k,v in tmp["bus"].items():
            tmp["bus"][k] = v/s
        for k,v in tmp["bus_id"].items():
            tmp["bus_id"][k] = v/s
### IMPORTANT ############################################
# Distributed generation is subtracted from load!

def update_load(self:GVParse, key:str, pgen:np.ndarray):
    """Update load values from distribued generation by subtracting pgen

    Args:
        key (str): Load key (BusID_LoadID)
        pgen (np.ndarray): generation from distributed generator
    """

    ## subtract dispatch allocation from load
    self.mdl.data["elements"]["load"][key]["p_load"]["values"] -= pgen
    
    if self.get_reactive:
        ### update q_load
        qp = self.mdl.data["elements"]["load"][key]["qp"]
        p_load = self.mdl.data["elements"]["load"][key]["p_load"]["values"]
        self.mdl.data["elements"]["load"][key]["q_load"]["values"] = p_load * qp

def area_distgen(self:GVParse):
    """Include distributed generation from /mdb/GenerationDistribution
    that is distributed by Area.
    Generation is distributed to loads and subtracted from the load values.

    NOTE: add_load method must be run before this, as it generates the load dictionary!
    """
    try:
        disttab = self.h5("/mdb/GenerationDistribution").loc[lambda x: x["Type"] == "AREA"]
    except KeyError:
        ## in case there is no Generation Distribution table
        self.logger.warning(f"WARNING: no Generation Distribution Table Found!")
        return
    for idx in disttab.index:
        ## get distribution entry
        dist : pd.Series = disttab.loc[idx]
        ## get generator entry
        gen : pd.Series = self.h5("/mdb/Generator").loc[lambda x: x["GeneratorKey"] == dist.GeneratorKey].squeeze()
        ## get dispatch
        try:
            disp : pd.Series = self.h5("/generator/GENERATION").loc[self.daterange, gen.GeneratorName]
            disp = self.interpolate_time(disp)
        except KeyError:
            ### skip if no output data. warn if the generator should be online.
            if self._gen_inservice(gen):
                self.logger.warning(f"WARINING: Generator {gen.GeneratorKey} {gen.GeneratorName} is in service but not in the GridView output. Skipping.")
            continue
        ## get conforming load
        cl = self.h5.get_cl(dist.Name)
        for idx2 in cl.index:
            ld : pd.Series = cl.loc[idx2]
            if not self.include_bus(ld.BusID):
                ### this load is not in the graph, skip.
                continue
            ## get dispatch allocation to this load
            p : np.ndarray = disp.to_numpy()*dist.Percentage*ld.alpha_k

            ## keep track of generators impacting this load
            self.mdl.data["elements"]["load"][idx2]["distgen"].append(dist.GeneratorKey)

            self.update_load(idx2, p)
            
            

def btm_distgen(self:GVParse):
    """Include distributed generation from /mdb/BTMGenLoadMapping
    that is distributed by Area.
    Generation is distributed to loads and subtracted from the load values.

    NOTE: add_load method must be run before this, as it generates the load dictionary!
    """
    try:
        disttab = self.h5("/mdb/BTMGenLoadMapping")
    except KeyError:
        ## No BTMGenLoadMapping Table
        self.logger.warning(f"WARNING: no BTM Gen Load Mapping Table Found!")
        return
    for idx in disttab.index:
        ## get distribution entry
        dist : pd.Series = disttab.loc[idx]
        if not self.include_bus(dist.LoadBusID):
            ### this load is not in the graph, skip.
            continue
        ## get generator entry
        gen : pd.Series = self.h5("/mdb/Generator").loc[lambda x: x["GeneratorKey"] == dist.GeneratorKey].squeeze()
        ## get dispatch
        disp : pd.Series = self.h5("/generator/GENERATION").loc[self.daterange, gen.GeneratorName]
        disp = self.interpolate_time(disp)
        ## get load key
        key = f"{dist.LoadBusID}_{dist.LoadID}"
        
        ## keep track of generators impacting this load
        self.mdl.data["elements"]["load"][key]["distgen"].append(dist.GeneratorKey)

        ## get dispatch allocation to this load
        p : np.ndarray = disp.to_numpy()*dist.Ratio

        self.update_load(key, p)


        


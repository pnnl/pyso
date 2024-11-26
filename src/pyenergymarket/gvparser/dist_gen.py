from __future__ import annotations
import pandas as pd
import numpy as np
import copy

### This is for type checking and syntax highlighting
### see: https://www.youtube.com/watch?v=UnKa_t-M_kM
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .__init__ import GVParse

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
        disp : pd.Series = self.h5("/generator/GENERATION").loc[self.daterange, gen.GeneratorName]
        ## get conforming load
        cl = self.h5.get_cl(dist.Name)
        for idx2 in cl.index:
            ld : pd.Series = cl.loc[idx2]
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
        ## get generator entry
        gen : pd.Series = self.h5("/mdb/Generator").loc[lambda x: x["GeneratorKey"] == dist.GeneratorKey].squeeze()
        ## get dispatch
        disp : pd.Series = self.h5("/generator/GENERATION").loc[self.daterange, gen.GeneratorName]
        ## get load key
        key = f"{dist.LoadBusID}_{dist.LoadID}"
        
        ## keep track of generators impacting this load
        self.mdl.data["elements"]["load"][key]["distgen"].append(dist.GeneratorKey)

        ## get dispatch allocation to this load
        p : np.ndarray = disp.to_numpy()*dist.Ratio

        self.update_load(key, p)


        


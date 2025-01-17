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
# not implemented generators are modeld as fixed pmin=pmax,
# no ancillaries.
#

def _other_gen(self:GVParse, gen:pd.Series, tmp:dict):
    """Processing for generator types that have not been implemented.
    positive dispatch is modeled as generation to make q limits can be
    added.
    negative dispatch is modeled as load.

    Args:
        gen (pd.Series): row of /mdb/Generator Table
        tmp (dict): parameter dictionary for the specific generator
    """
    
    dispatch = self.get_other_dispatch(gen.GeneratorName)
    if dispatch is None:
        return
    
    pos_dispatch = np.abs((dispatch >= 0) * dispatch)
    neg_dispatch = np.abs((dispatch < 0) * dispatch)

    epsilon = self.defaults["elements"]["generator"]["type_other_pos_neg_epsilon"]
    if pos_dispatch.sum() > epsilon:
        ### positive generation, add generator
        self.other_pos_gen(gen, tmp, pos_dispatch)
    if neg_dispatch.sum() > epsilon:
        ### negative generation, add load
        self.other_neg_gen(gen, tmp, neg_dispatch)

def other_pos_gen(self:GVParse, gen:pd.Series, tmp:dict, dispatch:np.ndarray):
    """Process not-implemented generators with positive injection as
    a fixed generator.

    Args:
        gen (pd.Series): row of /mdb/Generator Table
        tmp (dict): parameter dictionary for the specific generator
        dispatch (np.ndarray): positive valued dispatch
    """

    tmp["generator_type"] = "renewable"
    
    tmp["p_max"] = {"data_type": "time_series", 
                    "values": dispatch}
    
    tmp["p_min"] = copy.deepcopy(tmp["p_max"])
    
    if self.add_solution:
        tmp["pg"] = {"data_type": "time_series",
                     "values": dispatch}
        
    if self.get_reactive:
        self.set_qlims(tmp, typ="other", fixedpmax=gen.PSSEMaxCap)
    
    ### needed but shouldn't make a difference
    tmp["p_cost"] = self.defaults["elements"]["generator"]["type_other_cost"]
    
    tmp["fuel"] = "other"

    ### ancillary services like a renewable resource
    # NOTE: since the dispatch is fixed, fixing the commitment (in conversion to thermal)
    # is not an issue
    self.renewable_ancillary_sevices(gen, tmp)
    if self.is_distgen(gen.GeneratorKey) == "BUS":
        ## this is a distributed generator
        self.bus_distgen(gen.GeneratorKey, tmp)
    
    self.mdl.data["elements"]["generator"][gen.GeneratorName] = tmp

def other_neg_gen(self:GVParse, gen:pd.Series, tmp:dict, dispatch:np.ndarray):
    """Process not-implemented generators with negative injection as
    a load.

    Args:
        gen (pd.Series): row of /mdb/Generator Table
        tmp (dict): parameter dictionary for the specific generator
        dispatch (np.ndarray): positive valued dispatch
    """

    tmp["p_load"] = {"data_type": "time_series", "values": dispatch}
    if self.get_reactive:
        pf = self.get_default_pf(typ="other")
        s = dispatch/pf
        sine_theta = np.sin(np.arccos(pf))
        tmp["q_load"] = {"data_type": "time_series", "values":s*sine_theta}
    
    self.mdl.data["elements"]["load"][gen.GeneratorName] = tmp

def get_other_dispatch(self:GVParse, genname:str) -> np.ndarray:
    """Return the dispatched generation for self.daterange

    Args:
        genname (str): Generator name

    Returns:
        np.ndarray: array of MW values
    """
    
    generation_key = "/generator/GENERATION"
    try:
        out = self.h5(generation_key).loc[self.daterange, genname]
        out = self.interpolate_time(out)
        return out.values
    except KeyError:
        self.logger.warning(f"WARINING: Generator {genname} is in service but not in the GridView output. Skipping.")
        return None
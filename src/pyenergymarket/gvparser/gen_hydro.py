from __future__ import annotations
import pandas as pd
import numpy as np
import copy
from ..utils.timeutils import mk_daterange

### This is for type checking and syntax highlighting
### see: https://www.youtube.com/watch?v=UnKa_t-M_kM
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .__init__ import GVParse

### IMPORTANT ############################################
# hydro is currently modeled as a renewable (pmin=0 and pmax)

def _hydro_gen(self:GVParse, gen:pd.Series, tmp:dict):
    """Hydro Generator Processing

    Args:
        gen (pd.Series): row of /mdb/Generator Table
        tmp (dict): parameter dictionary for the specific generator
    """

    genkey = tmp["gv_generatorkey"]
    tmp["generator_type"] = "renewable"

    tmp["p_max"] = {"data_type": "time_series", 
                    "values": self.get_hydro_dispatch(gen.GeneratorName)}
    tmp["p_min"] = 0 #copy.deepcopy(tmp["p_max"])
    
    tmp["p_cost"] = self.get_renewable_dispach_cost(genkey)
    
    tmp["fuel"] = "Hydro"

    ### Ancillary Services
    self.renewable_ancillary_sevices(gen, tmp)
    
    self.mdl.data["elements"]["generator"][gen.GeneratorName] = tmp


def get_hydro_dispatch(self:GVParse, genname:str) -> np.ndarray:
    """Return the dispatched hydro for self.daterange

    Args:
        genname (str): Generator name

    Returns:
        np.ndarray: array of MW values
    """
    
    generation_key = "/generator/GENERATION"
    out = self.h5(generation_key).loc[self.daterange, genname]
    out = self.interpolate_time(out)

    return out.values
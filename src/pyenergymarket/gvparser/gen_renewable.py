from __future__ import annotations
import pandas as pd
import numpy as np

### This is for type checking and syntax highlighting
### see: https://www.youtube.com/watch?v=UnKa_t-M_kM
from typing import TYPE_CHECKING, Union
if TYPE_CHECKING:
    from .__init__ import GVParse

def _renewable_gen(self:GVParse, gen:pd.Series, tmp:dict):
    """Renewable Generator Processing

    Args:
        gen (pd.Series): row of /mdb/Generator Table
        tmp (dict): parameter dictionary for the specific generator
    """

    genkey = tmp["gv_generatorkey"]
    tmp["generator_type"] = "renewable"

    
    tmp["p_min"] = 0
    tmp["p_max"] = self.get_renewable_shape(gen.GeneratorName)
    tmp["p_cost"] = self.get_renewable_dispach_cost(genkey)
    hrsource = self.h5("/mdb/HourlyResource").loc[lambda x: x["GeneratorKey"] == genkey].squeeze()
    tmp["fuel"] = self.h5("/mdb/HourlyResourceType").loc[lambda x: x["TypeID"] == hrsource.Type, "Comments"].squeeze()

    self.mdl.data["elements"]["generator"][gen.GeneratorName] = tmp


def get_renewable_shape(self:GVParse, genname:str) -> np.ndarray:
    """Return the renewable shape at for the time span of self.daterange

    Args:
        genname (str): Generator name

    Returns:
        np.ndarray: array of MW values
    """
    
    ### TODO: this should be changed once the input profiles are more readily available
    ### For now, combine dispatched and curtailed MW to get input profile
    generation_key = "/generator/GENERATION"
    curtailment_key = "/generator/PRICE_MARKUP_RATIO"
    out = self.h5(generation_key).loc[self.daterange, genname] + self.h5(curtailment_key).loc[self.daterange, genname]
    return out.values
    
def get_renewable_dispach_cost(self:GVParse, genkey:int) -> Union[float, dict]:
    """Return the dispatch cost $/MWh for the renewable resource as a single number if constant
    or as a time-series. Taken from the MonthlyVariableSchedule (DataTypeID=9) table.

    Args:
        genkey (int): generator key

    Returns:
        Union[float, dict]: dispatch cost
    """

    def filter_fun(x, year:int):
        """Function to filter the mdb/MonthlyVariableSchedule key"""
        return (x["GeneratorKey"] == genkey) & (x["DataTypeID"] == 9) & (x["Year"] == year)
    
    key = "/mdb/MonthlyVariableSchedule"
    return self.get_ts_param(key, filter_fun)
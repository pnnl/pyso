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

    
    tmp["p_min"] = 0.0
    tmp["p_max"] = {"data_type": "time_series", 
                    "values": self.get_renewable_shape(gen.GeneratorName)}
    tmp["p_cost"] = self.get_renewable_dispach_cost(genkey)
    hrsource = self.h5("/mdb/HourlyResource").loc[lambda x: x["GeneratorKey"] == genkey].squeeze()
    if hrsource.Type in self.defaults["elements"]["generator"]["renewable_type_override"]:
        tmp["fuel"] = self.defaults["elements"]["generator"]["renewable_type_override"][hrsource.Type]
    else:
        tmp["fuel"] = self.h5("/mdb/HourlyResourceType").loc[lambda x: x["TypeID"] == hrsource.Type, "Comments"].squeeze()

    self.renewable_ancillary_sevices(gen, tmp)
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

def renewable_ancillary_sevices(self:GVParse, gen:pd.Series, tmp:dict):
    """Add anscillary services to renewable generators.
    Since EGRET only allows thermal generators to provide ancillary services
    Any renewable that should provide ancillary services is converted to a thermal
    generator

    Currently Implemnted:
    Regulation, Load Following, Spinning

    Args:
        gen (pd.Series): row of /mdb/Generator Table
        tmp (dict): parameter dictionary for the specific generator
    """
    #### Regulation (AGC)
    as_cap, as_frac = self.regulation_params(gen)
    if as_cap:
        ### convert to thermal so reserves is possible
        self.renewable2thermal(tmp)
        tmp["agc_capable"] = True
        tmp["ramp_agc"] = tmp["p_max"]["values"].max()
        tmp["p_min_agc"] = tmp["p_min"]
        tmp["p_max_agc"] = {"data_type": "time_series",
                            "values": tmp["p_max"]["values"] * as_frac}
    
    #### Flexible Ramping
    as_cap, as_frac = self.flexible_params(gen)
    if as_cap:
        ### convert to thermal so it can provide reserves
        self.renewable2thermal(tmp)

    #### Spinning
    as_cap, as_frac = self.spinning_params(gen)
    if as_cap:
        ### convert to thermal so it can provide reserves
        self.renewable2thermal(tmp)
        tmp["spinning_capacity"] = {"data_type": "time_series",
                                    "values": tmp["p_max"]["values"] * as_frac}
        
def renewable2thermal(self:GVParse, tmp:dict):
    """Convert a renewable generator to a thermal one

    Args:
        tmp (dict): parameter dictionary
    """
    if tmp["generator_type"] == "thermal":
        ### already converted
        return
    tmp["generator_type"] = "thermal"
    
    ### get the maximum and minimum capacity over the time horizon:
    if isinstance(tmp["p_max"], dict):
        p_max = tmp["p_max"]["values"].max()
    else:
        p_max = tmp["p_max"]
    
    if isinstance(tmp["p_min"], dict):
        p_min = tmp["p_min"]["values"].min()
    else:
        p_min = tmp["p_min"]

    ### set up a cost curve
    p_cost = tmp["p_cost"]
    if isinstance(tmp["p_cost"], dict):
        tmp["p_cost"] = {"data_type": "time_series", "cost_curve_type": "piecewise",
                         "values": [[[p_min, p], [p_max, p]] for p in p_cost["values"]]}
    elif isinstance(tmp["p_cost"], float):
        tmp["p_cost"] = {"data_type": "cost_curve", "cost_curve_type": "piecewise",
                         "values": [[p_min, p_cost], [p_max, p_cost]]}
    else:
        raise ValueError("Expected type for p_cost is float or dict.")

    ### initially on and no min up/down
    tmp["initial_status"] = 1
    tmp["initial_p_output"] = 0
    tmp["minimum_up_time"] = 0
    tmp["minimum_down_time"] = 0

    ### Ramp rate is equal to maximum power over the time horizon/min
    tmp["ramp_up_60min"] = p_max*60
    tmp["ramp_down_60min"] = p_max*60

    ### Force on (shouldn't matter since pmin=0)
    tmp["fixed_commitment"] = 1 
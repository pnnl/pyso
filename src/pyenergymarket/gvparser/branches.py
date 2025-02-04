from __future__ import annotations
import pandas as pd
import numpy as np
from typing import Union, Iterable

### This is for type checking and syntax highlighting
### see: https://www.youtube.com/watch?v=UnKa_t-M_kM
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .__init__ import GVParse

def mk_br_str(self:GVParse, br:pd.Series, check:Union[Iterable, None]=None) -> str:
    """Create a unique branch name string.
    Since From_To_CKT is not necessarily unique in GridView a check can be made
    for existing names and an additional _i where i is a number will be appended.

    Args:
        br (pd.Series): row from branch table
        check (Union[Iterable, None], optional): Iterable of existing branch names. Defaults to None.

    Returns:
        str: branch name
    """

    s = f"{br.FromBus}_{br.ToBus}_{br.CKT}"
    if (check is not None):
        i=2
        while s in check:
            s = f"{br.FromBus}_{br.ToBus}_{br.CKT}_{i}"
            i += 1
    return s

def _collect_line(self:GVParse, data:pd.Series):
        tmp = {}
        tmp["branch_type"] = "line"
        tmp["from_bus"] = self.mk_bus_str(data["FromBus"])
        tmp["to_bus"] = self.mk_bus_str(data["ToBus"])
        tmp["circuit"] = data["CKT"]
        tmp["in_service"] = data["Status"]
        tmp["resistance"] = data["R"]
        tmp["reactance"] = data["X"] if data["X"] != 0 else self.defaults["elements"]["branch"]["min_reactance"]
        tmp["charging_susceptance"] = data["B"]
        for k in ["long_term", "short_term", "emergency"]:
            tmp[f"rating_{k}"] = data[self.season + self.defaults["elements"]["branch"][f"rating_{k}"]]
        tmp["violation_penalty"] = data["Penalty"]
        tmp["angle_diff_min"] = self.defaults["elements"]["branch"]["angle_diff_min"]
        tmp["angle_diff_max"] = self.defaults["elements"]["branch"]["angle_diff_max"]
        ## saving for future use
        for i in ["Winter", "Summer"]:
            for j in ["A", "B", "C"]:
                tmp[str.lower(i+"_"+j)] = data[i+j]
        return tmp

def _collect_xfrm(self:GVParse, data:pd.Series):
        tmp = self._collect_line(data)
        tmp["branch_type"] = "transformer" #change branch type
        
        ## add transformer specific data
        tmp["transformer_tap_ratio"] = data["Ratio"] if data["Ratio"] != 0 else 1.0
        tmp["transformer_phase_shift"] = data["Angle"]
        return tmp

def _collect_par(self:GVParse, data:pd.Series):
        tmp = self._collect_xfrm(data)

        ## add PAR specific (not currently implemented)
        tmp["par_angle_min"] = data["PhaseShiftLB"]
        tmp["par_angle_max"] = data["PhaseShiftUB"]
        tmp["par_mw_min"] = data["PhaseShiftMWLB"]
        tmp["par_mw_max"] = data["PhaseShiftMWUB"]
        return tmp

def _collect_dcline_brtab(self:GVParse, data:pd.Series):
        tmp = {}
        tmp["from_bus"] = self.mk_bus_str(data["FromBus"])
        tmp["to_bus"] = self.mk_bus_str(data["ToBus"])
        tmp["circuit"] = data["CKT"]
        tmp["in_service"] = data["Status"]
        for k in ["short_term", "long_term", "emergency"]:
            tmp["rating_"+k] = data["DCLineMWLevel"]
        tmp["loss_factor"] =  data["X"]
        if self.defaults["elements"]["dc_branch"]["include_dispatch"]:
             ## Note: only populating flow at the from end!
             brflow = self.get_branch_flow(data)
             if brflow is not None:
                tmp["pf"] = {"data_type": "time_series",
                             "values": brflow}
        return tmp
    
#TODO: this is INCOMPLETE!!!
def _collect_dcline_dctab(self:GVParse, data:pd.Series):
    tmp = {}
    tmp["from_bus"] = data["FromBus"]
    tmp["to_bus"] = data["ToBus"]
    tmp["circuit"] = data["CKT"]
    tmp["in_service"] = data["Status"]
    for k in ["short_term", "long_term", "emergency"]:
        tmp["rating_"+k] = data["DCLineMWLevel"]
    tmp["loss_factor"] =  data["X"]
    return tmp

def get_branch_flow(self:GVParse, br:pd.Series, flow_key="/branch/FLOW", branchkey=None) -> np.ndarray:
    """Return the flow for the dc branch for self.daterange

    Args:
        branchkey (str): branchkey (from_to_ckt)

    Returns:
        np.ndarray: array of MW values
    """
    
    if branchkey is None:
         branchkey = self.mk_br_str(br) # Note: without check because need actual key in output table
    try:
        out = self.h5(flow_key).loc[self.daterange, branchkey]
        return out.values
    except KeyError:
        if (flow_key == "/branch/FLOW") and (br.DCLineNumber > 0):
            ## in the case of DC branches in the main branch table, try dcline/FLOW
            flow_key = "/dcline/FLOW"
            branchkey = f'{br.BranchID}_-1_{br.CKT}'
            return self.get_branch_flow(br, flow_key=flow_key, branchkey=branchkey)
        else:
            self.logger.warning(f"WARINING: Branch {branchkey} does not have flow values in GridView output. Skipping.")
            return None
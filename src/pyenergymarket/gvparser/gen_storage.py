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
# hydro is currently modeled as a fixed input (pmin=pmax)

def _storage_gen(self:GVParse, gen:pd.Series, tmp:dict):
    """Storage Generator Processing

    Args:
        gen (pd.Series): row of /mdb/Generator Table
        tmp (dict): parameter dictionary for the specific generator
    """

    genkey = tmp["gv_generatorkey"]
    # store for info since there different generator types
    tmp["gv_generatortype"] = gen.GeneratorType 

    if gen.GeneratorType == 10:
        self._storage_type10(genkey, tmp)
    # elif gen.GeneratorType == 3:
    #     self._storage_typ3(tmp)
    else:
        raise ValueError(f"Storage of type {gen.GeneratorType} is not implemented.")

    if "storage" not in self.mdl.data["elements"]:
        self.mdl.data["elements"]["storage"] = dict()
    self.mdl.data["elements"]["storage"][gen.GeneratorName] = tmp

def _storage_type10(self:GVParse, genkey:int, tmp:dict):
    
    # get row of Battery table
    bat = self.h5("/mdb/Battery").loc[lambda x: x["GeneratorKey"] == genkey, :].squeeze()
    tmp["energy_capacity"] = bat.MaxEnergy # Storage capacity in MWh
    tmp["initial_state_of_charge"] = bat.InitialEnergy/bat.MaxEnergy
    tmp["minimum_state_of_charge"] = 1. - bat.MaxDepthOfDischarge/100.
    ## TODO: May need to check that this is not cycle efficiency and convert.
    tmp["charge_efficiency"] = bat.Efficiency
    tmp["discharge_efficiency"] = bat.Efficiency
    
    ## self discharge
    # There is a yearly max energy deterioration rate
    # convert this to an hour (assumption is that hti s)
    tmp["retention_rate_60min"] = 1.0 - bat.YearlyMaxEnergyDeteriorateRate/8760

    ## charge/discharge rates
    tmp["max_discharge_rate"] = bat.MaxDischarge
    tmp["min_discharge_rate"] = 0.
    tmp["max_charge_rate"] = bat.MaxChargeLoad
    tmp["min_charge_rage"] = 0.

    ## ramp rates (rates are MW/min in GridView)
    for i in ["up", "down"]:
        tmp[f"ramp_{i}_input_60min"] = bat.ChargeRampRate*60
        tmp[f"ramp_{i}_output_60min"] = bat.DischargeRampRate*60

    ## costs
    # O&M cost in MonthlyVariableSchedule but no time variance is currently possible in EGRET
    # so pulling average cost
    vom = self.get_storage_vom(genkey)
    tmp["charge_cost"] = bat.DisChargeCost + vom
    tmp["discharge_cost"] = bat.DisChargeCost + vom


def _storage_type3(self:GVParse, genkey:int, tmp:dict):
    pass

def get_storage_vom(self:GVParse, genkey:int):

    def filter_fun(x, year:int):
        """function to filter the mdb/MonthlyVariableSchedule key"""
        return (x["GeneratorKey"] == genkey) & (x["DataTypeID"] == 1) & (x["Year"] ==  year)
    
    key = "/mdb/MonthlyVariableSchedule"
    return self.get_ts_param(key, filter_fun, typ="avg")
from pnnlpcm import h5fun
import pandas as pd
import numpy as np
from egret.data.model_data import ModelData
from .gvdefaults import gvdefaults

def merge_configs(defaults:dict, user:dict, level=0):
    """update the default options with user inputs"""
    for k, v in user.items():
        if k not in defaults:
            if level == 0:
                # if this is a top level configuration key, raise warning
                print(f"WARNING: configuration parameter {k} is unknown. Check spelling and capitalization perhaps?")
            defaults[k] = v
        else:
            if isinstance(v, dict):
                merge_configs(defaults[k], v, level=level+1)
            else:
                defaults[k] = v
class GVParse():
    def __init__(self, h5path:str, default:dict=None, **kwargs):
        """
        Inputs:
            h5path (str) path to h5 file exported from GridView
            defaults (dict) override to default value dictionary
        """
        ## load the h5 file
        self.h5 = h5fun.H5(h5path, **kwargs)
        self.mdl = ModelData() # create an empty model data object with keys "elements", "system"

        self.defaults = gvdefaults.copy()
        if default is not None:
            merge_configs(self.defaults, default)
    
    def data_convert(self, d=None):
        if d is None:
            d = self.mdl.data
        for k, v in d.items():
            if isinstance(v, dict):
                self.data_convert(d=v)
            else:
                ### modified from here: https://stackoverflow.com/questions/50916422/python-typeerror-object-of-type-int64-is-not-json-serializable
                ### modifying data instead of passing decoder to Egret
                if isinstance(v, np.integer):
                    d[k] = int(v)
                elif isinstance(v, np.floating):
                    d[k] = float(v)
                elif isinstance(v, np.ndarray):
                    d[k] = v.tolist()
                elif isinstance(v, np.bool_):
                    d[k] = bool(v)

    def mk_bus_str(self,busid:int):
        name, kv = self.h5("/mdb/Bus").loc[lambda x: x["BusID"] == busid, ["Name", "BaseKV"]].squeeze()
        return f'{busid}_{name}_{kv:.0f}'
    
    def get_zone(self, busid:int):
        return self.h5("/mdb/Bus").loc[lambda x: x["BusID"] == busid, "PSSEZoneID"].squeeze()

    def add_sys_info(self):
        """add system info"""
        sys = self.mdl.data["system"]
        sys["baseMVA"] = float(self.h5("/sys/SimulationControl_dic").loc["BaseMVA", 0])
        refbus = self.h5("/mdb/Bus").loc[lambda x: x["Type"] == 3, "BusID"].squeeze()
        sys["reference_bus"] = self.mk_bus_str(refbus)
        sys["reference_bus_angle"] = 0
    
    def add_buses(self):
        """Add buses to Egret Model"""

        bustype = {1: "PQ", 2: "PV", 3: "ref", 4: "isolated"}
        buses = dict()
        ### add load area name rather than id
        h5fun.add_load_area(self.h5("/mdb/Bus"), self.h5("/mdb/Bus"), self.h5("/mdb/LoadArea"))
        bustab = self.h5("/mdb/Bus") ## alias for less typing
        for i in bustab.index:
            tmp = {}
            tmp["id"] = bustab.loc[i, "BusID"]
            tmp["name"] = bustab.loc[i, "Name"]
            tmp["base_kv"] = bustab.loc[i, "BaseKV"]
            tmp["matpower_bustype"] =  bustype[bustab.loc[i, "Type"]]
            tmp["vm"] = bustab.loc[i, "VM"]
            tmp["va"] = bustab.loc[i, "VA"]
            tmp["area"] = bustab.loc[i, "LoadArea"] #use the load area from GridView
            tmp["zone"] = bustab.loc[i, "PSSEZoneID"]
            tmp["owner"] = bustab.loc[i, "Owner"]
            tmp["v_min"] = self.defaults["elements"]["bus"]["v_min"]
            tmp["v_max"] = self.defaults["elements"]["bus"]["v_max"]
            ### append to dictionary
            buses[self.mk_bus_str(tmp["id"])] = tmp
        
        ### add to model
        self.mdl.data["elements"]["bus"] = buses

    def add_branches(self):
        """Add branches to Egret model"""
        
        branch = dict()
        btab = h5fun.branchtab_with_bus_names(self.h5("/mdb/Branch"), self.h5("/mdb/Bus"))
        for i in btab.index:
            # Note: i is frombus_tobus_ckt
            if btab.loc[i, "DCLineNumber"] > 0:
                ## dc line
                tmp = self._collect_dcline(btab.loc[i, :])
                continue #TODO add to dc_line 
            elif (btab.loc[i, "PhaseShiftLB"] != 0) and (btab.loc[i, "PhaseShiftUB"] != 0):
                ## PAR
                tmp = self._collect_par(btab.loc[i,:])
            elif btab.loc[i, "FromBuskV"] != btab.loc[i, "ToBuskV"]:
                ## Transformer
                tmp = self._collect_xfrm(btab.loc[i, :])
            else:
                ## just a line
                tmp = self._collect_line(btab.loc[i, :])
            ### append to dictionary
            branch[i] = tmp
        ### add to model
        self.mdl.data["elements"]["branch"] = branch

          
        # note, will want to distinguish between lines and transformers, PARS, and dclines
    def _collect_line(self, data:pd.Series):
        tmp = {}
        tmp["branch_type"] = "line"
        tmp["from_bus"] = data["FromBus"]
        tmp["to_bus"] = data["ToBus"]
        tmp["circuit"] = data["CKT"]
        tmp["in_service"] = data["Status"]
        tmp["resistance"] = data["R"]
        tmp["reactance"] = data["X"]
        tmp["charging_susceptance"] = data["B"]
        for k in ["long_term", "short_term", "emergency"]:
            tmp[f"rating_{k}"] = data[self.defaults["elements"]["branch"][f"rating_{k}"]]
        tmp["angle_diff_min"] = self.defaults["elements"]["branch"]["angle_diff_min"]
        tmp["angle_diff_max"] = self.defaults["elements"]["branch"]["angle_diff_max"]
        ## saving for future use
        for i in ["Winter", "Summer"]:
            for j in ["A", "B", "C"]:
                tmp[str.lower(i+"_"+j)] = data[i+j]
        return tmp
    
    def _collect_xfrm(self, data:pd.Series):
        tmp = self._collect_line(data)
        tmp["branch_type"] = "transformer" #change branch type
        
        ## add transformer specific data
        tmp["transformer_tap_ratio"] = data["Ratio"]
        tmp["transformer_phase_shift"] = data["Angle"]
        return tmp
    
    def _collect_par(self, data:pd.Series):
        tmp = self._collect_xfrm(data)

        ## add PAR specific (not currently implemented)
        tmp["par_angle_min"] = data["PhaseShiftLB"]
        tmp["par_angle_max"] = data["PhaseShiftUB"]
        tmp["par_mw_min"] = data["PhaseShiftMWLB"]
        tmp["par_mw_max"] = data["PhaseShiftMWUB"]
        return tmp
    
    def _collect_dcline_brtab(self, data:pd.Series):
        tmp = {}
        tmp["from_bus"] = data["FromBus"]
        tmp["to_bus"] = data["to_bus"]
        tmp["circuit"] = data["CKT"]
        tmp["in_service"] = data["Status"]
        for k in ["short_term", "long_term", "emergency"]:
            tmp["rating_"+k] = data["DCLineMWLevel"]
        tmp["loss_factor"] =  data["X"]
        return tmp
    
    def _collect_dcline_dctab(self, data:pd.Series):
        tmp = {}
        tmp["from_bus"] = data["FromBus"]
        tmp["to_bus"] = data["to_bus"]
        tmp["circuit"] = data["CKT"]
        tmp["in_service"] = data["Status"]
        for k in ["short_term", "long_term", "emergency"]:
            tmp["rating_"+k] = data["DCLineMWLevel"]
        tmp["loss_factor"] =  data["X"]
        return tmp
    
    def add_generators(self):
        pass

    def add_load(self):
        load = dict()
        
        datefrom=self.defaults["elements"]["load"]["datefrom"]
        dateto  =self.defaults["elements"]["load"]["dateto"]
        dtrange = h5fun.mk_daterange(datefrom=datefrom, dateto=dateto)
        ### Conforming Load
        # loop over areas
        for area in self.h5("/area/LOAD").keys():
            tmp = self.h5.area_ts_to_bus(area=area, dtrange=dtrange)
            for k, v in tmp.items():
                busid = int(k.split("_")[0])
                load[k] = {
                    "bus" : self.mk_bus_str(busid),
                    "in_service": True,
                    "area": area,
                    "zone": self.get_zone(busid),
                    "ncl": False,
                    "p_load": {
                        "data_type": "time_series",
                        "values": v.values
                    }
                }

        ### Non-Conforming Load
        ncl = self.h5.get_ncl()
        for i in ncl.index:
            busid = ncl.loc[i,"BusID"]
            k = f'{busid}_{ncl.loc[i, "LoadID"]}'
            load[k] = {
                "bus": self.mk_bus_str(busid),
                "in_service": True,
                "area": ncl.loc[i, "LoadArea"],
                "zone": self.get_zone(busid),
                "ncl": True,
                "p_load": {
                    "data_type": "time_series",
                    "values": ncl.loc[i, "PL"]*np.ones(len(dtrange))
                }
            }

        ### add to model
        self.mdl.data["elements"]["load"] = load
        
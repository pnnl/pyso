from pnnlpcm import h5fun
import pandas as pd
import numpy as np
from egret.data.model_data import ModelData
from .gvdefaults import gvdefaults
from typing import Union

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

        self._daterange = None
    
    @property
    def daterange(self) -> pd.DatetimeIndex:
        """Get date range based on the values in self.defaults["time"]
        """
        
        if self._daterange is None:
            datefrom=self.defaults["time"]["datefrom"]
            dateto  =self.defaults["time"]["dateto"]
            self._daterange = h5fun.mk_daterange(dfts=self.h5("/area/LOAD"), datefrom=datefrom, dateto=dateto)
        
        return self._daterange

    def set_daterange(self, datefrom:Union[None,str] = None, dateto:Union[None,str]=None):
        """Update the desired daterange (in parameter self.daterange)
        If only one (datefrom OR dateto) is given the date range will be just that date.
        If both datefrom and dateto are None, then the full daterange of the underlying database will be used.

        Note:
            This function updates the values in self.defaults["time"]
        Args:
            datefrom (Union[None,str], optional): Start date for the range (inclusive). Defaults to None.
            dateto (Union[None,str], optional): End date for the range (inclusive). Defaults to None.
        """

        self.defaults["time"]["datefrom"] = datefrom
        self.defaults["time"]["dateto"] = dateto
        
        # force recalculation of daterange
        self._daterange = None 
        return self.daterange
        
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
        
        gentab = self.h5("/mdb/Generator")
        generator = dict()
        for i in gentab.index:
            ## loop over generators and dispatch based on generator type
            if not self._gen_inservice(i):
                ## for now, don't copy any generators that are not in service
                continue

            tmp = {
                "bus": self.mk_bus_str(gentab.loc[i, "BusID"]),
                "gv_generatorkey": gentab.loc[i, "GeneratorKey"],
                "in_service": True,
                "unit_type": gentab.loc(gentab.loc[i, "SubType"]),
                "area": gentab.loc[i, "LoadArea"],
                "zone": self.get_zone(gentab.loc[i, "BusID"])
            }

            ## dispatch based on GeneratorType
            for t, v in self.defaults["elements"]["generator"]["generator_type_map"].items():
                if gentab.loc[i, "GeneratorType"] in v:
                    getattr(self, f"_{t}_gen")(i, generator, tmp)
                    break
            
    
    def _gen_inservice(self, i:int) -> bool:
        """Test whether a generator at index i in the Generator table is in service.
        To be in service, a generator must have:
          - the ServiceStatus flag True
          - Commission date earlier (<=) to the beginning of the date range considered
          - Retirement date later (>=) to the end of the date range considered

        Args:
            i (int): index in self.h5("/mdb/Generator")

        Returns:
            bool: whether generator is operable
        """
        status = self.h5("/mdb/Generator").loc[i, "ServiceStatus"]
        commission = self.h5("/mdb/Generator").loc[i, "CommissionDate"]
        retire = self.h5("/mdb/Generator").loc[i, "RetirementDate"]

        return status and (commission <= self.daterange[0]) and (retire >= self.daterange[-1])



    def _thermal_gen(self, i:int, generator:dict, tmp:dict):
        genkey = tmp["gv_generatorkey"]
        fuelid = self.h5("/mdb/ThermalGeneral").loc[lambda x: x["GeneratorKey"] == genkey, "FuelID"]
        tmp["generator_type"] = "thermal"
        tmp["p_fuel"] = {"data_type": "fuel_curve", "values": self.thermal_iocurve(genkey)}
        ## get max and min values directly from the fuel curve
        tmp["p_min"] = tmp["p_fuel"]["values"][0][0]
        tmp["p_max"] = tmp["p_fuel"]["values"][-1][0]

    def thermal_iocurve(self, genkey:int) -> list[tuple]:
        """Generatate the p_fuel curve which needs to have output value (MW), and fuel consumed MMBTU

        Pulls from tables:
            - ThermalIOCurve
            - ThermalGenericIOCurve
            - ThermalGenericHeatPoints

        Cases:
            - Everything defined in ThermalIOCurve (IfUseGenericIOCurve is False)
            - Everything defined in ThermalGenericIOCurve (IfUseGenericIOCurve is True and all other curve values are -1)
            - Mix (IfUseGenericIOCurve is True but some values are non negative) specifically, the Pmin and full load avg HR can be varied.
        
        Args:
            genkey (int): gridview generator key

        Returns:
            fuel_curve (list[tuple]): list of (MW, MMBtu) points
        """
        iocurve = self.h5("/mdb/ThermalIOCurve").loc[lambda x: x["GeneratorKey"] == genkey].squeeze()
        
        pmax = self.h5("/mdb/ThermalGeneral").loc[lambda x: x["GeneratorKey"] == genkey, "InstalledCapacity"]
        if iocurve.IfUseGenericIOCurve:
            generic_io = self.h5("/mdb/ThermalGenericIOCurve").loc[lambda x: x["GenericIOCurveName"] == iocurve.GenericIOCurveName].squeeze()
            # use generic Pmin if IOMinCap is < 0
            pmin = pmax*generic_io.GenericMin if iocurve.IOMinCap < 0 else iocurve.IOMinCap
            
            # Use generic full load heat rate if FullLoadAverageHeatRate is < 0
            avghr = generic_io.GenericHR if iocurve.FullLoadAverageHeatRate < 0 else iocurve.FullLoadAverageHeatRate
            coeffs = [getattr(generic_io, f"X{i}") for i in reversed(range(5))]
            duct_fire_test = iocurve.CCDBExist and (iocurve.CCDBIncrCap > 0)
            if duct_fire_test:
                ## if there is duct firing remove from pmax and then add back afterwards
                pmax -= iocurve.CCDBIncrCap
            ## get fuel curve
            fuel_curve = self._from_generic_io_curve(pmin, pmax, avghr, coeffs)
            if duct_fire_test:
                ## if there is duct firig:
                #   1. convert to incremental heat rate
                #   2. Add duct firing block
                #   3. convert back to fuel burn
                inc_hr = self.fuelburn2inchr(fuel_curve)
                inc_hr.append((iocurve.CCDBIncrCap, iocurve.CCDBIncrHR))
                fuel_curve = self.inchr2fuelburn(inc_hr)
            return fuel_curve
        else:
            return self._from_inchr(iocurve)
        

    def _from_generic_io_curve(self, pmin:float, pmax:float, avghr:float, coeffs:list[float]) -> list[tuple]:
        """Calculte the fuel burn curve (MW, MMBTU) based on the generic unitized coefficients

        Args:
            pmin (float): minimum output [MW]
            pmax (float): maximum output [MW]
            avghr (float): full load average heat rate [MMBtu/MWh]
            coeffs (list[float]): polynomial coefficients of unitized IO curve [pu fuel/pu output]
                                should be in decreasing order, i.e. last entry is the constant

        Returns:
            fuel_curve (list[tuple]): list of (MW, MMBtu) points
        """
        
        ## calculate range
        prange = pmax - pmin 

        ## get heat points based on range
        npts   = self.h5("/mdb/ThermalGenericHeatPoints").loc[lambda x: x["DispatchRange"] <= prange, "NumHPBlock"].max()
        heatpoints = self.h5("/mdb/ThermalGenericHeatPoints").loc[lambda x: x["NumHPBlock"] == npts].squeeze()
        
        ## Normalized fuel burn curve
        pu_pmin = pmin/pmax    # normalized pmin
        pu_range = 1 - pu_pmin # normalized range

        # points are labeled starting at 2 since 1 is the minimum
        pu_pts = [pu_pmin] + [pu_pmin + pu_range*getattr(heatpoints, f"HP{i+2}") for i in range(npts-1)]
        pu_fuel = np.polyval(coeffs, pu_pts) # evaluate the polynomial to get fuel burn
        pu_fuel /= pu_fuel.max() #normalize so maximum is 1 pu

        ## Calculate fuel burn curve with units
        maxfuel = avghr*pmax
        return [(pu_pts[i]*pmax, pu_fuel[i]*maxfuel) for i in range(npts)]

    def fuelburn2inchr(self, fuel_curve:list[tuple]) -> list[tuple]:
        """Convert fuel burn curve with (MW, MMBtu) entries to incremental heat rate:
        (min MW, min MMBtu), (increment 2 MW, increment HR MMBtu/MWh), ... 

        Args:
            fuel_curve (list[tuple]): fuel burn curve with entries (MMW, MMBtu)

        Returns:
            inc_hr (list[tuple]): incremental heat rate curve with entries (min MW, min MMBtu), (increment 2 MW, increment HR MMBtu/MWh), ... 
        """

        mw = [fuel_curve[0][0]] + [fuel_curve[i][0] - fuel_curve[i-1][0] for i in range(1, len(fuel_curve))]
        incfuel = [fuel_curve[0][1]] + [(fuel_curve[i][1] - fuel_curve[i-1][1])/mw[i] for i in range(1, len(fuel_curve))]
    
        return list(zip(mw, incfuel))
    
    def inchr2fuelburn(self, inc_hr:list[tuple]) -> list[tuple]:
        """Convert incremental heat rate in the form (min MW, min MMBtu), (increment 2 MW, increment HR MMBtu/MWh), ...
        to fuel burn curve with (MW, MMBtu) entries.
        This is the inverse of fuelburn2inchr   

        Args:
            inc_hr (list[tuple]): incremental heat rate curve with entries (min MW, min MMBtu), (increment 2 MW, increment HR MMBtu/MWh), ... 

        Returns:
            fuel_curve (list[tuple]): fuel burn curve with entries (MMW, MMBtu)
        """

        mw   = np.cumsum([inc_hr[i][0] for i in range(len(inc_hr))])
        fuel = np.cumsum([inc_hr[0][1]] +  [inc_hr[i][1]*inc_hr[i][0] for i in range(1, len(inc_hr))])

        return list(zip(mw, fuel))
    
    def _from_inchr(self, iocurve:pd.Series) -> list[tuple]:
        """Calculte the fuel burn curve (MW, MMBTU) based on entries in the thermal io curve table

        Args:
            iocurve (pd.Series): row from the ThermaIOCurve table

        Returns:
            fuel_curve (list[tuple]): list of (MW, MMBtu) points
        """
        
        ## Gather the incremental curve
        mw = [iocurve.IOMinCap] + [getattr(iocurve, f"IncCap{i+2}") for i in range(iocurve.IONumBlock-1)]
        incfuel = [iocurve.MinInput] + [getattr(iocurve, f"IncHR{i+2}") for i in range(iocurve.IONumBlock-1)]
        inc_hr = list(zip(mw, incfuel))

        ## convert to fuel burn
        return self.inchr2fuelburn(inc_hr)
    
    def _hydro_gen(self, i:int, generator:dict, tmp:dict):
        pass

    def _storage_gen(self, i:int, generator:dict, tmp:dict):
        pass

    def _renewable_gen(self, i:int, generator:dict, tmp:dict):
        pass
    
    def add_load(self):
        load = dict()
        
        ### Conforming Load
        # loop over areas
        for area in self.h5("/area/LOAD").keys():
            tmp = self.h5.area_ts_to_bus(area=area, dtrange=self.daterange)
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
                    "values": ncl.loc[i, "PL"]*np.ones(len(self.daterange))
                }
            }

        ### add to modele in
        self.mdl.data["elements"]["load"] = load
        
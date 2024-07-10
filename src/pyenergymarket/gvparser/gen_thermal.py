from __future__ import annotations
import pandas as pd
import numpy as np

### This is for type checking and syntax highlighting
### see: https://www.youtube.com/watch?v=UnKa_t-M_kM
from typing import TYPE_CHECKING, Union
if TYPE_CHECKING:
    from .__init__ import GVParse

def _thermal_gen(self:GVParse, gen:pd.Series, tmp:dict):
    """Thermal Generator Processing

    Args:
        gen (pd.Series): row of /mdb/Generator Table 
        tmp (dict): parameter dictionary for the specific generator
    """
    genkey = tmp["gv_generatorkey"]
    thermalgeneral = self.h5("/mdb/ThermalGeneral").loc[lambda x: x["GeneratorKey"] == genkey].squeeze()
    tmp["generator_type"] = "thermal"

    ### ignore generators with zero capacity
    if thermalgeneral.InstalledCapacity <= 0:
        self.logger.warning(f"WARNING: Installed capacity for generator {genkey} is 0. Skipping.")
        return
    
    ## min up/down times
    genericnamecol = "GenericMinUpDnName"
    generickey = "/mdb/ThermalGenericMinUpDownMaxUpTime"
    tmp["min_up_time"] = self.get_value_or_generic(genkey, "MiniUpTime", genericnamecol, generickey, genericvalcol="MinimumUpTime")
    tmp["min_down_time"] = self.get_value_or_generic(genkey, "MinimumDownTime", genericnamecol, generickey)

    ## get the fuel burn data
    tmp["p_fuel"] = {"data_type": "fuel_curve", "values": self.thermal_iocurve(genkey)}
    ## get max and min values directly from the fuel curve
    tmp["p_min"] = tmp["p_fuel"]["values"][0][0]
    tmp["p_max"] = tmp["p_fuel"]["values"][-1][0]

    fuelid = thermalgeneral.FuelID
    tmp["fuel"]   = self.h5("/mdb/Fuel").loc[lambda x: x["FuelID"] == fuelid, "FuelName"].squeeze()
    ## get start fuel, this is not an Egret value but we should keep track of this.
    startfuelid = thermalgeneral.StartupFuelID
    tmp["start_fuel"] = self.h5("/mdb/Fuel").loc[lambda x: x["FuelID"] == startfuelid, "FuelName"].squeeze()
    tmp["fuel_cost"] = self.get_fuel_cost(fuelid, scale_factor=self.defaults["elements"]["generator"]["scale_fuel_cost"])
    ## Note: starting fuel cannot accommodate time varying values in Egret at present.
    tmp["start_fuel_cost"] = self.get_fuel_cost(startfuelid, typ="avg", scale_factor=self.defaults["elements"]["generator"]["scale_fuel_cost"])

    ## Get starting fuel/costs
    genericnamecol = "GenericStartupName"
    generickey = "/mdb/ThermalGenericStartupCost"
    start_fuel = self.get_value_or_generic(genkey, "StartFuel", genericnamecol, generickey, genericvalcol="GenericStartFuel", scale_generic=tmp["p_max"])
    start_cost = self.get_value_or_generic(genkey, "StartupCost", genericnamecol, generickey, genericvalcol="GenericStartCost", scale_generic=tmp["p_max"])
    start_time = self.get_value_or_generic(genkey, "StartupTime", genericnamecol, generickey)
    
    
    tmp["non_fuel_startup_cost"] = 0 if self.defaults["elements"]["generator"]["ignore_non_fuel_startup"] else start_cost
    # first entry of startup_fuel needs to be (min_down_time, start_fuel)
    # see start lag validation rule see validate_startup_lags_rule https://github.com/breldridge/Egret/blob/03f1f01866c315661ba858e04d330528d200cb32/egret/model_library/unit_commitment/params.py#L900-L903
    tmp["startup_fuel"] = np.array([(tmp["min_down_time"], start_fuel)])
    ###### convert to cost curve
    ## Get VOM cost (NOTE: ignoring option in MonthlyVariableSchedule)
    vom = self.get_value_or_generic(genkey, "VOMCost", "GenericVOMName", "/mdb/ThermalGenericVOMCost")
    
    if self.defaults["simulation"]["thermal_model"] == "cost":
        self.fuel2cost(tmp, vom=vom)
    else:
        self.logger.warning("WARNING: simulation thermal_mode set not set to 'cost', VOM costs will be neglected")

    ## Ramping (ramping in GridView is MW/min)
    genericnamecol = "GenericRampRateName"
    generickey = "/mdb/ThermalGenericRampUpDown"
    genericnamekey = "GenericRampName"
    tmp["ramp_up_60min"] = 60*self.get_value_or_generic(genkey, "RampUpRate", genericnamecol, generickey, genericnamekey=genericnamekey, default=tmp["p_max"])
    tmp["ramp_down_60min"] = 60*self.get_value_or_generic(genkey, "RampDnRate", genericnamecol, generickey, genericnamekey=genericnamekey, genericvalcol="RampDownRate", default=tmp["p_max"])

    ## startup/shutdown capacity
    ## According to Hitachi generator can start up at an point
    ## Assume generator can shutdown from any point.
    tmp["startup_capacity"] = tmp["p_max"] #min(tmp["p_min"] + tmp["ramp_up_60min"], tmp["p_max"])
    tmp["shutdown_capcity"] = tmp["p_max"]

    ## must run
    if thermalgeneral.MustRun:
        tmp["fixed_commitment"] = 1

    ### initialization
    ## copying default from rts_gmlc parser: https://github.com/breldridge/Egret/blob/03f1f01866c315661ba858e04d330528d200cb32/egret/parsers/rts_gmlc/parser.py#L948-L953
    ## all units set on at their minimum output
    tmp["initial_status"] = tmp["min_up_time"] + 1
    tmp["initial_p_output"] = tmp["p_min"]
    tmp["initial_q_output"] = 0.0

    ### ANCILLIARY SERVICES: TODO!!!
    ## some of these are standin
    tmp["fast_start"] = thermalgeneral.QuickStart
    
    ## AGC
    tmp["agc_capable"] = 1
    # use minimum of ramp_up/ramp_down 
    tmp["ramp_agc"] = min(tmp["ramp_up_60min"]/60, tmp["ramp_down_60min"]/60)
    tmp["p_min_agc"] = tmp["p_min"]
    tmp["p_max_agc"] = tmp["p_max"]

    ## TODO: generation distribution table from Brent's update!!!

    ### Add to model data
    self.mdl.data["elements"]["generator"][gen.GeneratorName] = tmp

def fuel2cost(self:GVParse, tmp:dict, vom:float=0):
    """Convert fuel values to cost values

    Args:
        tmp (dict): parameter dictionary
        vom (float): optional vom cost in $/MWh to add to cost
    """

    def mmbtu2dollar(p_fuel, fc, vom):
        # inchr = self.fuelburn2inchr(p_fuel)
        # _tmp = [(inchr[0][0], inchr[0][1])]
        _tmp = []
        # for delta_mw, hr in inchr[1:]:
        for (mw, mmbtu) in p_fuel:
            _tmp.append((mw, mmbtu*fc + mw*vom))
            # _tmp.append((delta_mw, hr*fc + vom))
        return _tmp
    
    ###### FUEL BURN
    p_fuel = tmp.pop("p_fuel") # Fuel Burn curve (MW, MMBTU)
    fuel_cost = tmp.pop("fuel_cost") # Fuel Cost in ($/MMBTU)
    tmp["org_p_fuel"] = p_fuel
    tmp["org_fuel_cost"] = fuel_cost
    ## Convert to cost curve with entries (MW, $/MWh)
    if isinstance(fuel_cost, dict):
        ### fuel cost is time series
        tmp["p_cost"] = {"data_type": "time_series", "cost_curve_type": "piecwise",
                        "values": []}
        for fc in fuel_cost["values"]:
            tmp["p_cost"]["values"].append(mmbtu2dollar(p_fuel["values"], fc, vom))
    else:
        ### single value fuel cost
        tmp["p_cost"] = {
            "data_type": "cost_curve",
            "cost_curve_type": "piecewise",
            "values": mmbtu2dollar(p_fuel["values"], fuel_cost, vom)
        }

    ##### START FUEL
    start_fuel = tmp.pop("startup_fuel")
    start_fuel_cost = tmp.pop("start_fuel_cost")
    tmp["org_start_fuel"] = start_fuel
    tmp["org_start_fuel_cost"] = start_fuel_cost
    tmp["startup_cost"] = [(hr, mmbtu*start_fuel_cost) for (hr, mmbtu) in start_fuel]
    
def get_fuel_cost(self:GVParse, fuelid:int, **kwargs) -> Union[float, dict]:
    """Return Fuel Cost in $/MMBTU for the given fuel id.
    If the price over the entire time horizon is constant, just a single number is returned.
    Otherwise, a time series is returned. Prices are taken from mdb/FuelCostSchedule

    Args:
        fuelid (int): the fuel id to key in
        kwargs: options passed to get_ts_param

    Returns:
        Union[float, dict]: fuel cost in $/MMBTU
    """

    def filter_fun(x, year:int):
        """Function to filter the mdb/FuelCostSchedule key"""
        return (x["FuelID"] == fuelid) & (x["Year"] == year)
    
    key = "/mdb/FuelCostSchedule"
    return self.get_ts_param(key, filter_fun, scale_key="PriceScaler", **kwargs)

# def get_fuel_cost(self:GVParse, fuelid:int, typ:str="time_series") -> float:
#     """Return a fuel cost in $/MMBTU.
#     if typ = "time_series" the fuel cost is returned as time series for each simulation time.
#     if typ = "avg" this will pull the average of the fuel costs for the date range of the simulation.
#     For each year in the daterange the code attempts to find fuel cost at that year.
#     If that is not available then year 0 is tried.

#     Args:
#         fuelid (int): the fuel id
#         typ (str, optional): 
#             - time_series: returns a time series of fuel costs
#             - avg: returns a average value of the the date range for the model
#     """
    
#     def get_fuel_cost_series(year:int) -> pd.Series:
#         """Return row of table corresponding to provided year, or year=0
#         """
#         v = self.h5("/mdb/FuelCostSchedule").loc[lambda x: (x["FuelID"] == fuelid) & (x["Year"] == year)].squeeze()
#         if v.empty:
#             v = self.h5("/mdb/FuelCostSchedule").loc[lambda x: (x["FuelID"] == fuelid) & (x["Year"] == 0)].squeeze()
#             if v.empty:
#                 raise ValueError(f"No Fuel cost found for fuel id {fuelid} for the year {year} OR with year=0.")
#         return v
    
#     if typ == "time_series":
#         tmp = {"data_type": "time_series", "values": []}
#         for t in self.daterange:
#             year = t.year
#             month = t.month
#             v = get_fuel_cost_series(year)
#             tmp["values"].append(getattr(v, f"V{month}")*v.PriceScaler)
#         return tmp
#     elif typ == "avg":
#         years = self.daterange.year.unique()
#         # months = self.daterange.month.unique()
#         tmp = []
#         for year in years:
#             ## loop over years
#             v = get_fuel_cost_series(year)
#             ## append all months that are in range
#             for month in self.daterange[self.daterange.year == year].month.unique():
#                 tmp.append(getattr(v, f"V{month}")*v.PriceScaler)
        
#         return np.mean(tmp)
#     else:
#         raise ValueError(f'typ can be either avg or time_series but {typ} was given.')

def get_value_or_generic(self:GVParse, genkey:int, valcol:str, genericnamecol:str, 
                            generickey:str, genericnamekey:str=None, genericvalcol:str=None, 
                            scale_generic:float=1, default:float=0) -> float:
    """Return a value form the ThermalGeneral Table or get the generic value if the found value is -1.

    Args:
        genkey (int): Generator Key
        valcol (str): column name where value should be extracted
        genericnamecol (str): column for the generic table name (if needed)
        generickey (str): key for the generic table e.g. "/mdb/ThermalGenericMinUpDownMaxUpTime"
        genericnamekey (str, optional): column name to key on in generic table. Default is genericnamecol
        genericvalcol (str, optional): column name where generic value should be extracted. Defaults to valcol.
        scale_generic (float, optional): scale to apply to generic value if used. Defaults to 1.
        default (float, optional): value to return if valcol return -1 and no generic is found (this should not happen). Defaults to 0.

    Returns:
        float: property value
    """
    
    if genericvalcol is None:
        genericvalcol = valcol

    if genericnamekey is None:
        genericnamekey = genericnamecol

    gen = self.h5("/mdb/ThermalGeneral").loc[lambda x: x["GeneratorKey"] == genkey].squeeze()
    v = getattr(gen, valcol)
    if  v < 0:
        ## use generic
        v = self.h5(generickey).loc[lambda x: x[genericnamekey] == getattr(gen, genericnamecol), genericvalcol]
        if v.empty:
            self.logger.warning(f"WARNING: No generic value found for generator {genkey} for {valcol}. Generic Name is {getattr(gen, genericnamecol)}.")
            return default
        else:
            v = v.squeeze()
            if isinstance(v, pd.Series):
                # see if there are accidentally duplicate entries
                v = v.drop_duplicates().squeeze()
                if isinstance(v, pd.Series):
                    # just pick the first
                    self.logger.warning(f"WARNING: multiple, non-duplicate entries {genericvalcol} for generic curve {getattr(gen, genericnamecol)}. Picking the first one.")
                    v = v.iloc[0]
            return v*scale_generic
    else:
        return v

def thermal_iocurve(self:GVParse, genkey:int) -> list[tuple]:
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
    
    pmax = self.h5("/mdb/ThermalGeneral").loc[lambda x: x["GeneratorKey"] == genkey, "InstalledCapacity"].squeeze()
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
        if pmin == pmax:
            self.logger.warning(f"WARNING: for generator {genkey} pmin = pmax")
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
    

def _from_generic_io_curve(self:GVParse, pmin:float, pmax:float, avghr:float, coeffs:list[float]) -> list[tuple]:
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
    if np.isnan(npts):
        self.logger.warning(f"WARNING: Operation range {prange} is outside the scope of ThermalGenericHeatPoints, setting to 2 points.")
        npts = 2
        
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

def fuelburn2inchr(self:GVParse, fuel_curve:list[tuple]) -> list[tuple]:
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

def inchr2fuelburn(self:GVParse, inc_hr:list[tuple]) -> list[tuple]:
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

def _from_inchr(self:GVParse, iocurve:pd.Series) -> list[tuple]:
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
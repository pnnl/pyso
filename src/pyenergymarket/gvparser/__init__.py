from pnnlpcm import h5fun
import pandas as pd
import numpy as np
from egret.data.model_data import ModelData
from .gvdefaults import gvdefaults
from typing import Union, Callable, Iterable
from ..utils.ioutils import merge_configs
from ..utils.timeutils import mk_daterange
from ..engine import DataProvider
import copy

class GVParse(DataProvider):
    def __init__(self, h5path:str, default:dict=None, **kwargs):
        """
        Inputs:
            h5path (str) path to h5 file exported from GridView
            defaults (dict) override to default value dictionary
        """
        ## load the h5 file
        self.h5 = h5fun.H5(h5path, **kwargs)
        self.mdl = ModelData() # create an empty model data object with keys "elements", "system"

        self.defaults = copy.deepcopy(gvdefaults)
        if default is not None:
            merge_configs(self.defaults, default)

        self._daterange = None
        self._actual_res_daterange = None
        self.logger = self.h5.logger

        self._summer_time = None
        self._season = None

        ## TODO: not sure what ends up being the label for 5: non spin, and 7: frequency
        self.astype2gvkey = {1: "REGULATION DOWN",
                             2: "FLEXIBLE DOWN",
                             3: "REGULATION UP",
                             4: "SPINNING RESERVE",
                             6: "FLEXIBLE UP"}
        ## Note: mapping both regulation and load following (Flexible) to regulation
        self.astype2egret = {1: "regulation_down",
                             2: "flexible_ramp_down",
                             3: "regulation_up",
                             4: "spinning_reserve",
                             5: "non_spinning_reserve",
                             6: "flexible_ramp_up"}
    
    def __call__(self, savename:str):
        """Parse gridview and write the EGRET model
        
        Args:
            savename (str): name to save to (.json)
        """
        
        self.parse()
        self.write(savename)

    def get_model(self, daterange:Union[pd.DatetimeIndex,None]) -> ModelData:
        """Data provider callback for EnergyMarket.
        See also utils.timeutils.mk_daterange

        Args:
            daterange(Union[pd.DatetimeIndex,None], optional): the actual datetime index. Defaults to None

        Returns:
            ModelData: Egret model for specified date range
        """
        
        ### set the date
        self.set_daterange(dt = daterange)
        ### parse
        self.parse()
        ### return model
        return self.mdl
    

    def parse(self):
        """Parse the gridview model for the given date range into an EGRET Model
        """
        if not self.h5.is_open:
            self.h5.open()
        self.logger.info("Adding system info...", end="")
        self.add_sys_info()
        self.logger.info("complete")
        self.logger.info("Adding buses...", end="")
        self.add_buses()
        self.logger.info("complete")
        self.logger.info("Adding branches...", end="")
        self.add_branches()
        self.logger.info("complete")
        self.logger.info("Adding load...", end="")
        self.add_load()
        self.logger.info("complete")
        self.logger.info("Adding generators...", end="")
        self.add_generators()
        self.logger.info("complete")
        self.logger.info("Adding ancillary service requirements...", end="")
        self.as_requirements()
        self.logger.info("complete")
        self.logger.info("Converting data for saving...", end="")
        self.data_convert()
        self.logger.info("complete")
        self.h5.close()
    
    def write(self, savename:str):
        """Write the EGRET model to a json file

        Args:
            savename (str): name to save to (.json)
        """
        self.mdl.write(savename)

    @property
    def daterange(self) -> pd.DatetimeIndex:
        """Get date range based on the values in self.defaults["time"]
        floors the result to hourly resolution since this is what is in the GV database
        """
        
        if self._daterange is None:
            datefrom = self.defaults["time"]["datefrom"]
            dateto   = self.defaults["time"]["dateto"]
            min_freq = self.defaults["time"]["min_freq"]
            periods  = self.defaults["time"]["periods"]
            self._actual_res_daterange = mk_daterange(start = datefrom, end=dateto, min_freq=min_freq, periods=periods)
            self._daterange = self._actual_res_daterange.floor('h').union(self._actual_res_daterange.ceil('h')).drop_duplicates()#self._actual_res_daterange.floor("h")
            # self._daterange = h5fun.mk_daterange(dfts=self.h5("/area/LOAD"), datefrom=datefrom, dateto=dateto)
        
        return self._daterange
    
    @property
    def actual_res_daterange(self) -> pd.DatetimeIndex:
        """Get the actual daterange (might be at resolution less than hour)
        """
        
        _ = self.daterange # force calculation if necessary
        return self._actual_res_daterange

    def is_summer(self, t:pd.Timestamp) -> bool:
        """Test whether a time instance is summer or winter

        Args:
            t (pd.Timestamp): time to test

        Returns:
            bool: True if summer, False if Winter
        """
        if self._summer_time is None:
            self._summer_time = {}
            for k in ["Start", "End"]:
                tmp = self.h5("/mdb/SimulationControl").loc[lambda x: x["Name"] == f"Summer {k}", "Value"].squeeze()
                if len(tmp) == 3:
                    tmp = "0" + tmp
                ## save start and end times as (month, day)
                self._summer_time[k.lower()] = [int(tmp[:2]), int(tmp[:2])]
        start_test = (t.month >= self._summer_time["start"][0]) and (t.day >= self._summer_time["start"][1])
        end_test = (t.month <= self._summer_time["end"][0]) and (t.day <= self._summer_time["end"][1])

        return start_test and end_test
    
    @property
    def season(self) -> str:
        """Since Egret Currently doesn't support time varying ratings pick
        the rating that matches the most hours of self.daterange.

        Returns:
            str: "Winter" or "Summer"
        """
        if self._season is None:
            summer = 0
            winter = 0
            for t in self.daterange:
                if self.is_summer(t):
                    summer += 1
                else:
                    winter += 1

            ## in case of a tie use winter since it is the traditional "default"
            if summer >= winter:
                self._season = "Summer"
            else:
                self._season = "Winter"
        return self._season
    
    def update_daterange(self, dt:pd.DatetimeIndex):
        """Update the daterange incase a datetime index is provided directly

        Args:
            dt (pd.DatetimeIndex): externally provided datetime index
        """
        self.defaults["time"]["datefrom"] = dt[0].strftime("%Y-%m-%d %H:%M")
        self.defaults["time"]["dateto"]   = dt[-1].strftime("%Y-%m-%d %H:%M")
        self.defaults["time"]["periods"]  = len(dt)
        if self.defaults['time']['periods'] == 1:
            if self.defaults["time"]["min_freq"] is not None:
                pass
            else:
                # if only one time interval, then we must require
                # the user to provide the min_freq
                raise ValueError(f"min_freq must be set in energy market configuration")
        else:
            self.defaults["time"]["min_freq"] = round(dt.diff()[-1].total_seconds()/60)
        

        # force recalculation of daterange
        self._daterange = None
        return self.daterange
    
    def set_daterange(self, dt:Union[pd.DatetimeIndex,None]=None,
                      datefrom:Union[None,str] = None, dateto:Union[None,str]=None,
                      min_freq:Union[None,int] = None, periods:Union[None,int]=None,
                      force_update=False):
        """Update the desired daterange (in parameter self.daterange)
        Updates the time values for any input that is not None.
        If force_update is True all inputs will be updated, allowing to set previously set inputs to None.
        Note that exactly 3 inputs must be defined at any time to create a daterange.

        Note 1: By default (see gvdefaults.py) min_freq is populated with 60, and periods with 24. 
        This means that if only datefrom is provided, the resulting daterange will be one day, starting at that time.
        If only dateto is provided, the resulting daterange will be one day ending at that time.
        If both are provided, the behavior is that this range takes precedence.

        Note 2:
            This function updates the values in self.defaults["time"]
        Args:
            datefrom (Union[None,str], optional): Start date for the range (inclusive). Defaults to None.
            dateto (Union[None,str], optional): End date for the range (inclusive). Defaults to None.
        """
        ### If datetime index is provided it takes precedence.
        if dt is not None:
            return self.update_daterange(dt)
        
        ### if 3 of the inputs are specified, set force update
        ### since this is a fully specified time range
        cnt_not_none = 0
        for i in [datefrom, dateto, min_freq, periods]:
            if i is not None:
                cnt_not_none += 1
        if cnt_not_none >= 3:
            force_update = True

        if force_update or (datefrom is not None):
            self.defaults["time"]["datefrom"] = datefrom
        if force_update or (dateto is not None):
            self.defaults["time"]["dateto"] = dateto
        if force_update or (min_freq is not None):
            self.defaults["time"]["min_freq"] = min_freq
        if force_update or (periods is not None):
            self.defaults["time"]["periods"] = periods

        
        # force recalculation of daterange
        self._daterange = None 
        return self.daterange
        
    def data_convert(self, d=None, l=None):
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
                    ## TODO recurse down arrays
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
        sys["baseMVA"] = float(self.h5("/mdb/SimulationControl").loc[lambda x: x["Name"] == "BaseMVA", "Value"].squeeze())
        refbus = self.h5("/mdb/Bus").loc[lambda x: x["Type"] == 3, "BusID"].squeeze()
        sys["reference_bus"] = self.mk_bus_str(refbus)
        sys["reference_bus_angle"] = 0
        sys["load_mismatch_cost"] = float(self.h5("/mdb/SimulationControl").loc[lambda x: x["Name"] == "Load Shedding Penalty", "Value"].squeeze())
        sys["time_keys"] = self.actual_res_daterange.strftime("%Y-%m-%d %H:%M").to_list()
        sys["time_period_length_minutes"] =  round(self.actual_res_daterange.diff()[-1].total_seconds()/60)
    
    def add_buses(self):
        """Add buses to Egret Model"""

        bustype = {1: "PQ", 2: "PV", 3: "ref", 4: "isolated"}
        buses = dict()
        ### add load area name rather than id
        if 'LoadArea' not in self.h5('/mdb/Bus'):
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

    ###### Branches ################
    from .branches import _collect_line
    from .branches import _collect_xfrm
    from .branches import _collect_par
    from .branches import _collect_dcline_brtab
    from .branches import _collect_dcline_dctab
    from .branches import mk_br_str

    def add_branches(self):
        """Add branches to Egret model"""
        
        branch = dict()
        btab = h5fun.branchtab_with_bus_names(self.h5("/mdb/Branch"), self.h5("/mdb/Bus"))
        for i in range(btab.shape[0]):
            br = btab.iloc[i,:]
            if br.DCLineNumber > 0:
                ## dc line
                tmp = self._collect_dcline_brtab(br)
                if "dc_branch" not in self.mdl.data["elements"]:
                    self.mdl.data["elements"]["dc_branch"] = dict()
                self.mdl.data["elements"]["dc_branch"][self.mk_br_str(br, self.mdl.data["elements"]["dc_branch"].keys())] = tmp
                continue # don't add to branch set!!!
            elif (br.PhaseShiftLB != 0) and (br.PhaseShiftUB != 0):
                ## PAR
                tmp = self._collect_par(br)
            elif br.FromBuskV != br.ToBuskV:
                ## Transformer
                tmp = self._collect_xfrm(br)
            else:
                ## just a line
                tmp = self._collect_line(br)
            ### append to dictionary
            branch[self.mk_br_str(br, check=branch.keys())] = tmp
        ### add to model
        self.mdl.data["elements"]["branch"] = branch

          
        # note, will want to distinguish between lines and transformers, PARS, and dclines
    
    ###### Generators ################
    def add_generators(self):
        
        gentab = self.h5("/mdb/Generator")
        self.mdl.data["elements"]["generator"] = dict()
        for i in gentab.index:
            ## loop over generators and dispatch based on generator type
            gen = gentab.loc[i] # pd.Series 
            if not self._gen_inservice(gen):
                ## for now, don't copy any generators that are not in service
                continue
            self.h5.logger.debug(f"Processing Generator {gen.GeneratorKey} {gen.GeneratorName}")
            ## Add general data
            tmp = {
                "bus": self.mk_bus_str(gen.BusID),
                "gv_generatorkey": gen.GeneratorKey,
                "in_service": gen.ServiceStatus,
                "unit_type": gen.SubType,
                "area": gen.LoadArea,
                "zone": self.get_zone(gen.BusID)
            }

            ## dispatch based on GeneratorType
            for t, v in self.defaults["elements"]["generator"]["generator_type_map"].items():
                if gen.GeneratorType in v:
                    getattr(self, f"_{t}_gen")(gen, tmp)
                    break

    def _gen_inservice(self, gen:pd.Series) -> bool:
        """Test whether a generator (pandas series that is a row of the Generator table) is in service.
        To be in service, a generator must have:
          - the ServiceStatus flag True
          - Commission date earlier (<=) to the beginning of the date range considered
          - Retirement date later (>=) to the end of the date range considered

        Args:
            gen (pd.Series): row of self.h5("/mdb/Generator")

        Returns:
            bool: whether generator is operable
        """

        return gen.ServiceStatus and (gen.CommissionDate <= self.daterange[0]) and (gen.RetirementDate >= self.daterange[-1])

    ###### THERMAL GENERATION ################
    from .gen_thermal import _thermal_gen
    from .gen_thermal import fuel2cost
    from .gen_thermal import get_fuel_cost
    from .gen_thermal import get_value_or_generic
    from .gen_thermal import thermal_iocurve
    from .gen_thermal import _from_generic_io_curve
    from .gen_thermal import fuelburn2inchr
    from .gen_thermal import inchr2fuelburn
    from .gen_thermal import _from_inchr
    from .gen_thermal import get_as_capability
    from .gen_thermal import regulation_params
    from .gen_thermal import spinning_params
    from .gen_thermal import flexible_params
    
    ##### RENEWABLE GENERATION ################
    from .gen_renewable import _renewable_gen
    from .gen_renewable import get_renewable_shape
    from .gen_renewable import get_renewable_dispach_cost
    from .gen_renewable import renewable_ancillary_sevices
    from .gen_renewable import renewable2thermal

    ##### Hydro ###############################
    from .gen_hydro import _hydro_gen
    from .gen_hydro import get_hydro_dispatch

    ##### Storage #############################
    from .gen_storage import _storage_gen
    from .gen_storage import _storage_type10
    from .gen_storage import get_storage_vom

    def interpolate_time(self, df:Union[pd.DataFrame, pd.Series]) -> Union[pd.DataFrame,pd.Series]: #, #dtinterp:pd.DatetimeIndex,
                        #  method:Union[str,None]=None) -> Union[pd.DataFrame,pd.Series]:
        """interpolate the data in the input dataframe/series (indexed on self.daterange)
        to indices of self.actual_res_daterange.
        Interpolation method is defined in configuration: self.defaults["interpolate"]["method"]

        Args:
            df (Union[pd.DataFrame, pd.Series]): Input data at original resolution
            # dtinterp (pd.DatetimeIndex): the time index for the interpolated data 
            method (str, optional): interpolation method. Defaults to "zero". must be one of the
                                    methods received by scipy.interpolate()

        Returns:
            Union[pd.DataFrame,pd.Series]: interpolated data on the new time index.
        """

        # create time index to be interpolated on (resolution equal to actual_res_daterange)
        dtinterp = mk_daterange(start=self.daterange[0],end=self.daterange[-1],min_freq=self.defaults["time"]["min_freq"])
        # reindex dataframe at resolution of interest and interpolate
        df = df.reindex(dtinterp).interpolate(method=self.defaults['interpolate']['method'])

        # return samples at the actual time slices of interest
        return df.loc[self.actual_res_daterange]
    
    def add_load(self):
        load = dict()

        ### Conforming Load
        # loop over areas
        for area in self.h5("/area/LOAD").keys():
            tmp = self.h5.area_ts_to_bus(area=area, dtrange=self.daterange) # unique to load
            tmp = self.interpolate_time(tmp)

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
    
    def get_ts_param(self, key:str, filter_fun:Callable[[pd.DataFrame, int], pd.Series], 
                     typ:str="time_series", scale_key:Union[str,None]=None, scale_factor:float=1, 
                     force_time_series:bool=False) -> Union[float, dict]:
        """Return a time dependent parameter such as fuel cost or renewable dispatch cost
        
        if typ = "time_series" the fuel cost is returned as time series for each simulation time.
        If all the values are the same in the time series, just a scalar is returned unless force_time_series is True.

        if typ = "avg" this will pull the average of the fuel costs for the date range of the simulation.
        
        For each year in the daterange the code attempts to find fuel cost at that year.
        If that is not available then year 0 is tried.

        Args:
            key (str): mdb key e.g. /mdb/FuelCostSchedule
            typ (str, optional): 
                - time_series: returns a time series of fuel costs
                - avg: returns a average value of the the date range for the model
            scale_key (str, optional): column name in mdb key that contains a scaler for the data. Default is None.
            scale_factor (float, optional): scale factor (will multiply scale_key is provided). Default is 1. 
            force_time_series (bool, optional): If True and typ = "time_series" a time series will be returned
                even if it consists of all identical values.
        """
        
        def get_series(year:int) -> pd.Series:
            """Return row of table corresponding to provided year, or year=0
            """
            v = self.h5(key).loc[lambda x: filter_fun(x, year)].squeeze()
            if v.empty:
                v = self.h5(key).loc[lambda x: filter_fun(x, 0)].squeeze()
                if v.empty:
                    raise ValueError(f"No row found with provided filter_fun for year {year} OR with year=0.")
            return v
        
        # if typ == "time_series":
        #     tmp = {"data_type": "time_series", "values": []}
        tmp = []
        ## collect data for each time interval
        for t in self.daterange:
            _scale_factor = scale_factor # copy for this time instant of any additional/external scale factor
            year = t.year
            month = t.month
            v = get_series(year)
            if scale_key is not None:
                self.logger.debug(f"get_ts_param: scale_factor = {scale_factor} (type={type(scale_factor)}), v = {getattr(v, scale_key)} (type={type(getattr(v, scale_key))})")
                _scale_factor *= getattr(v, scale_key)
            tmp.append(getattr(v, f"V{month}")*_scale_factor)
            
        ## check if all values are the same, if so, return just one scalar
        unique_vals = np.unique(tmp)
        if len(unique_vals) == 1:
            return unique_vals[0]
        
        if typ == "time_series":
            return {"data_type": "time_series", "values": tmp}
        elif typ == "avg":
            return np.mean(tmp)
        else:
            raise ValueError(f'typ can be either avg or time_series but {typ} was given.')

    ############## Ancilliary Services ######################
    from .ancilliary_services import as_requirements
    from .ancilliary_services import get_as_requirement
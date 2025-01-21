from simauto import SimAuto
from egret.data.model_data import ModelData
import pandas as pd
from ..utils.ioutils import merge_configs, Logger
from ..utils.egretutils import get_bus_id, get_networkx_graph, get_bus_from_id
from .pwdefaults import pwdefaults
import numpy as np
from typing import Union
import networkx as nx

class PWParse():
    def __init__(self, pwbpath:str, config:dict=None, **kwargs):
        """Power World parser for adding reactive power information to
        Egret models.

        Args:
            pwbpath (str): path to power world case (.pwb file)
            config (dict, optional): Overrides to default configurations. Defaults to None.
        """
        
        self.defaults = pwdefaults.copy()
        if config is not None:
            merge_configs(self.defaults, config)

        ### set up logger
        self.logger = Logger(**self.defaults["logging"])
        if self.defaults["logging"]["file"] is not None:
            self.logger.set_logfile(self.defaults["logging"]["file"])

        self.sa = SimAuto(logger_settings="")
        self.sa()
        self.sa.open_case(pwbpath)

        self._tables = {}

        self._G = None

        self._md = None

    @property
    def include_qg(self) -> bool:
        """include qg results in model
        """
        return self.defaults["generation"]["include_qg"]
    
    @property
    def update_voltage(self) -> bool:
        """update voltage setpoints vm/va from power flow case
        """
        return self.defaults["bus"]["update_voltage"]
    
    @property
    def md(self) -> ModelData:
        """Return currently attached Egret Model
        """
        return self._md

    @property
    def G(self) -> nx.Graph:
        """Return a network X representation of the Egret Model
        """
        if self._G is None:
            if self.md is None:
                raise AttributeError("Graph property can only be used if a an Egret Model has been set.")
            self._G = get_networkx_graph(self._md)
        return self._G
    
    def set_md(self, md:ModelData):
        self._md = md
    
    def unset_md(self):
        self._md = None
        self._G = None

    def get_table(self, key:str, parameterkeynames:list=[], parameterkeytypes:list=[], force=False) -> pd.DataFrame:
        """get data table form the power world model

        Args:
            key (str): desired table
            parameterkeynames (list, optional): desired columns. Defaults to [].
            parameterkeytypes (list, optional): data type for columns. Defaults to [].

        Returns:
            pd.DataFrame: returned data
        """
        if (key not in self._tables) or force:
            self._tables[key] = self.sa.extract_object_table(key, parameterkeynames=parameterkeynames, parameterkeytypes=parameterkeytypes)
        return self._tables[key]
        
    def update_model(self, md:ModelData):
        """Update the egret model with reactive power information

        Args:
            md (ModelData): Egret model
        """
        self.set_md(md)
        if self.update_voltage:
            self.update_buses()
        self.update_generator_qlims()
        self.add_shunts()
        self.add_line_shunts(remove_existing_shunts=False)
        self.unset_md()

    def get_bus_voltage(self, b:str) -> tuple[float,float]:
        """extract the voltage and angle for bus b

        Args:
            b (str): bus name (key in Egret dictionary)

        Returns:
            tuple[float,float]: vm [p.u.], va [deg]
        """
        buses = self.get_table("Bus")
        busid = self.md.data["elements"]["bus"][b]["id"] # note: this is not there by default in Egret
        bus : pd.Series = buses.loc[lambda x: x["Number"] == busid].squeeze()
        if bus.empty:
            return None, None
        return bus.Vpu, bus.VangleRad*180/np.pi
    
    def get_nearest_bus_with_voltage(self, bus:str) -> tuple[float,float,int, str]:
        """Get the voltage at the nearest bus to b with valid values.
        The function returns 4 values:
        - vm: the found voltage magnitude [p.u.]
        - va: the found voltage angle [deg]
        - i : the distance (in hops) between busid and the bus supplying voltage values
        - b : the name of the bus supplying values

        Args:
            bus (str): the bus around which to search

        Returns:
            tuple[float,float,int, str]: vm, va, i, b
        """
        i = 0
        vm = None
        va = None
        while vm is None:
            i += 1 # increment distance
            for b in nx.descendants_at_distance(self.G, bus, i):
                # iterate over buses at distance i from busid
                vm, va = self.get_bus_voltage(b) # get voltage
                if self.test_voltage_limits(vm, b, log=False):
                    break
                else:
                    # make sure we keep iterating
                    vm = None
                
        return vm, va, i, b

    def test_voltage_limits(self, vm:Union[float,None], b:str, log=True) -> bool:
        """Check whether the voltage magnitude found is reasonable.
        acceptable min/max values are supplied in the configuration
        under bus->min_acceptable_voltage and bus->max_acceptable_voltage

        Args:
            vm (float): found voltage magnitude
            b (str): bus with vm
            log (bool, optional): whether to print a warning if the test fails. Defaults to True.

        Returns:
            bool: True=voltages are reasonable, False=voltages are not reasonable
        """
        
        out = True
        if vm is None:
            out = False
        elif vm < self.defaults["bus"]["min_acceptable_voltage"]:
            out = False
            if log:
                self.logger.warning(f'\tWARNING: voltage for bus {b} ({vm:0.3f}) is below threshold ({self.defaults["bus"]["min_acceptable_voltage"]})')
        elif vm > self.defaults["bus"]["max_acceptable_voltage"]:
            out = False
            if log:
                self.logger.warning(f'\tWARNING: voltage for bus {b} ({vm:0.3f}) is above threshold ({self.defaults["bus"]["max_acceptable_voltage"]})')
        return out
    
    def update_buses(self):
        """Update the voltage setpoints of buses based on the power flow

        Args:
            md (ModelData): Egret model
        """

        self.logger.info("Updating bus voltages...", end="")
        
        for b, b_dict in self.md.elements(element_type="bus"):
            self.logger.debug(f"DEBUG: processing bus {b}")
            vm, va = self.get_bus_voltage(b)
            # bus : pd.Series = buses.loc[lambda x: x["Number"] == busid].squeeze()
            if vm is None:
                self.logger.warning(f"\tWARNING: Bus {b} not found in PW Bus Table. Skipping. Voltage setpoint from PCM will remain.")
                continue
            
            if not self.test_voltage_limits(vm, b, log=True):
                vm, va, dist, b_neighbor = self.get_nearest_bus_with_voltage(b)
                self.logger.info(f"\tUsing voltage ({vm:0.3f}) from bus {b_neighbor} at distance {dist} hops")
                
            ## get voltage magnitude and angle
            b_dict["vm"] = vm
            b_dict["va"] = va
        
        self.logger.info("Completed bus initial voltages.")


    def update_generator_qlims(self):
        """Update generator reactive limits

        Args:
            md (ModelData): Egret model
        """
        
        self.logger.info("Updating generator reactive limits...", end="")
        ### get the pw generator table
        gens = self.get_table("Gen")
        ### loop over generators
        for g, g_dict in self.md.elements(element_type='generator'):
            bus = get_bus_id(self.md, g_dict["bus"]) ## note: this is not there by default in Egret
            id  = g_dict["id"]                  ## note: this is not there by default in Egret
            gen : pd.Series = gens.loc[lambda x: (x["BusNum"] == bus) & (x["ID"].str.strip() == id.strip())].squeeze()
            if gen.empty:
                self.logger.warning(f"\tWARNING: Generator {g} not found in PW Gen Table. Skipping. Default Q limits will Remain.")
                continue
            g_dict["q_min"] = gen.MvarMin
            g_dict["q_max"] = gen.MvarMax
            if self.include_qg:
                g_dict["qg"] = gen.Mvar
            ## Note: if this is a renewable model the assumed power factor will be used
        
        ### loop over load in case other-type generators were placed there
        for l, l_dict in self.md.elements(element_type="load"):
            if "gv_generatorkey" in l_dict:
                bus = get_bus_id(self.md, l_dict["bus"]) ## note: this is not there by default in Egret
                id  = l_dict["id"]                  ## note: this is not there by default in Egret
                gen : pd.Series = gens.loc[lambda x: (x["BusNum"] == bus) & (x["ID"].str.strip() == id.strip())].squeeze()
                if gen.empty:
                    self.logger.warning(f"\tWARNING: Generator {g} not found in PW Gen Table. Skipping. Default Q limits will Remain.")
                    continue
                ## use constant Q instead of constant PF
                l_dict["q_load"] = -1*gen.Mvar # flip sign since modeled as load
                ### for information only, but again flipping sign due to model as load
                l_dict["q_min"] = -gen.MvarMax
                l_dict["q_max"] = gen.MvarMin

        self.logger.info("Completed generator reactive limits.")

    def map_shunt_type(self, pw_shunt_type:str) -> str:
        """Map a power word shunt type to either fixed or variable.
        If type is not found in the map returns a warning and defaults to variable

        Args:
            pw_shunt_type (str): Power world shunt type

        Returns:
            str: fixed or variable
        """
        tmp = self.defaults["shunts"]["shunt_type_map"].get(pw_shunt_type,None)
        if tmp is None:
            self.logger.warning(f"Unable to map pw_shunt_type {pw_shunt_type}. Defaulting to 'variable'.")
            tmp = "variable"
        return tmp

    def make_shunts_variable(self, pw_shunt_type:str) -> bool:
        """Returns true if the shunt type should be converted to variable.

        Args:
            pw_shunt_type (str): Power World shunt type

        Returns:
            bool: True => convert to variable shunt, False, keep as originally mapped
        """
        tmp = self.map_shunt_type(pw_shunt_type)
        if tmp == "fixed":
            ### if fixed check whether to change
            return self.defaults["shunts"]["make_variable"].get(pw_shunt_type, False)
        else:
            return True

    def add_shunts(self, remove_existing_shunts:Union[None,bool]=None):
        """Add shunt data to the model.
        Note: this will any existing shunt information if remove_existing_shunts is True
        If none, the value from self.defaults["shunts"]["remove_existing"] is used.

        Args:
            md (ModelData): Egret Model
            remove_existing_shunts (Union[None,bool], optional): remove existing shunts key. Default None -> value in defaults dictionary
        """
        
        self.logger.info("Adding shunt elements...", end="")
        if remove_existing_shunts is None:
            remove_existing_shunts = self.defaults["shunts"]["remove_existing"]
        
        ### remove existing shunt key
        if remove_existing_shunts or ("shunt" not in self.md.data["elements"]):
            self.md.data["elements"].pop("shunt",None)
            self.md.data["elements"]["shunt"] = dict()
        
        ## get all shunts
        shunts = self.sa.extract_object_table("Shunt")
        
        for i in shunts.index:
            s : pd.Series = shunts.loc[i]
            tmp = {
                "busid": s.BusNum,
                "bus": get_bus_from_id(self.md, s.BusNum, field="id"),
                "id": s.ID,
                "pw_status": s.Status,
                "bs": s.Mvar, # initial value
                "pw_mode": s.ShuntMode,
                "bs_min": s.MvarNomMin,
                "bs_max": s.MvarNomMax,
                "step_count": s.loc[lambda x: x.index.str.contains("BlockNumberStep")].sum(),
                "shunt_type": "variable" if self.make_shunts_variable(s.ShuntMode) else "fixed",
                "line_shunt": False
            }
            if (tmp["pw_status"] == "Open") and (tmp["shunt_type"] == "fixed"):
                ## don't included fixed shunts that are out of service
                continue
            elif tmp["bus"] is None:
                ## bus was not found in egret model. skip
                continue
            self.md.data["elements"]["shunt"][f"{s.BusNum}_{s.ID}"] = tmp
        self.logger.info("Completed adding shunt elements.")

    def add_line_shunts(self, remove_existing_shunts:Union[None,bool]=None):
        
        self.logger.info("Adding line shunt elements...", end="")
        if remove_existing_shunts is None:
            remove_existing_shunts = self.defaults["shunts"]["remove_existing"]
        
        ### remove existing shunt key
        if remove_existing_shunts or ("shunt" not in self.md.data["elements"]):
            self.md.data["elements"].pop("shunt",None)
            self.md.data["elements"]["shunt"] = dict()

        ### get all line shunts
        line_shunts = self.sa.extract_object_table("LineShunt",
                                      parameterkeynames=["BusNumFrom", "BusNumTo", "Circuit", "BusNumLoc", "ID", "MvarNom", "Status"],
                                      parameterkeytypes=[int, int, str, int, str, float, str])
        for i in line_shunts.index:
            s : pd.Series = line_shunts.loc[i]
            if s.MvarNom == 0:
                ## there is no data here
                continue
            tmp = {
                "busid": s.BusNumLoc,
                "bus": get_bus_from_id(self.md, s.BusNumLoc, field="id"),
                "id": s.ID,
                "pw_status": s.Status,
                "bs": s.MvarNom,
                "bs_min": s.MvarNom if s.MvarNom < 0 else 0.0,
                "bs_max": s.MvarNom if s.MvarNom > 0 else 0.0,
                "line_shunt": True,
                "shunt_type": "variable" if self.make_shunts_variable("Line Shunt") else "fixed"
            }
            
            if (tmp["pw_status"] == "Open") and (tmp["shunt_type"] == "fixed"):
                ## don't included fixed shunts that are out of service
                continue
            elif tmp["bus"] is None:
                ## bus was not found in egret model. skip
                continue
            self.md.data["elements"]["shunt"][f"{s.BusNumLoc}_{s.ID}"] = tmp
        self.logger.info("Completed adding line shunt elements.")
            
        


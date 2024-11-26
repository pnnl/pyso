from simauto import SimAuto
from egret.data.model_data import ModelData
import pandas as pd
from ..utils.ioutils import merge_configs, Logger
from ..utils.egretutils import get_bus_id
from .pwdefaults import pwdefaults
import numpy as np
from typing import Union

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

    def get_table(self, key:str, parameterkeynames:list=[], parameterkeytypes:list=[]) -> pd.DataFrame:
        """get data table form the power world model

        Args:
            key (str): desired table
            parameterkeynames (list, optional): desired columns. Defaults to [].
            parameterkeytypes (list, optional): data type for columns. Defaults to [].

        Returns:
            pd.DataFrame: returned data
        """
        if key in self._tables:
            return self._tables[key]
        else:
            return self.sa.extract_object_table(key, parameterkeynames=parameterkeynames, parameterkeytypes=parameterkeytypes)

    def update_model(self, md:ModelData):
        """Update the egret model with reactive power information

        Args:
            md (ModelData): Egret model
        """
        self.update_generator_qlims(md)
        self.add_shunts(md)
        self.add_line_shunts(md, remove_existing_shunts=False)

    def update_generator_qlims(self, md:ModelData):
        """Update generator reactive limits

        Args:
            md (ModelData): Egret model
        """
        
        self.logger.info("Updating generator reactive limits...", end="")
        ### get the pw generator table
        gens = self.get_table("Gen")
        ### loop over generators
        for g, g_dict in md.elements(element_type='generator'):
            bus = get_bus_id(md, g_dict["bus"]) ## note: this is not there by default in Egret
            id  = g_dict["id"]                  ## note: this is not there by default in Egret
            gen : pd.Series = gens.loc[lambda x: (x["BusNum"] == bus) & (x["ID"].str.strip() == id.strip())].squeeze()
            if gen.empty:
                self.logger.warning(f"\tWARNING: Generator {g} not found in PW Gen Table. Skipping. Default Q limits will Remain.")
                continue
            g_dict["q_min"] = gen.MvarMin
            g_dict["q_max"] = gen.MvarMax
            ## in case this is a renewable model
            g_dict["power_factor"] = np.sign(gen.Mvar/gen.MW)*np.cos(np.arctan(gen.Mvar/gen.MW))
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

    def add_shunts(self, md:ModelData, remove_existing_shunts:Union[None,bool]=None):
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
        if remove_existing_shunts or ("shunt" not in md["elements"]):
            md["elements"].pop("shunt",None)
            md["elements"]["shunt"] = dict()
        
        ## get all shunts
        shunts = self.sa.extract_object_table("Shunt")
        
        for i in shunts.index:
            s : pd.Series = shunts.loc[i]
            tmp = {
                "bus": s.BusNum,
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
            md["elements"]["shunt"][f"{s.BusNum}_{s.ID}"] = tmp
        self.logger.info("Completed adding shunt elements.")

    def add_line_shunts(self, md:ModelData, remove_existing_shunts:Union[None,bool]=None):
        
        self.logger.info("Adding line shunt elements...", end="")
        if remove_existing_shunts is None:
            remove_existing_shunts = self.defaults["shunts"]["remove_existing"]
        
        ### remove existing shunt key
        if remove_existing_shunts or ("shunt" not in md["elements"]):
            md["elements"].pop("shunt",None)
            md["elements"]["shunt"] = dict()

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
                "bus": s.BusNumLoc,
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
            md["elements"]["shunt"][f"{s.BusNumLoc}_{s.ID}"] = tmp
            self.logger.info("Completed adding line shunt elements.")
            
        


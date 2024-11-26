from simauto import SimAuto
from egret.data.model_data import ModelData
import pandas as pd
from ..utils.egretutils import get_bus_id
import numpy as np

class PWParse():
    def __init__(self, pwbpath:str, config:dict=None, **kwargs):
        """Power World parser for adding reactive power information to
        Egret models.

        Args:
            pwbpath (str): path to power world case (.pwb file)
            config (dict, optional): Overrides to default configurations. Defaults to None.
        """
        
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
        pass

    def update_generator_qlims(self, md:ModelData):
        """Update generator reactive limits

        Args:
            md (ModelData): _description_
        """
        ### get the generator table
        gens = self.get_table("Gen")
        ### loop over generators
        for g, g_dict in md.elements(element_type='generator'):
            bus = get_bus_id(md, g_dict["bus"]) ## note: this is not there by default in Egret
            id  = g_dict["id"]                  ## note: this is not there by default in Egret
            gen = gens.loc[lambda x: (x["BusNum"] == bus) & (x["ID"].str.strip() == id.strip())].squeeze()
            g_dict["q_min"] = gen.MvarMin
            g_dict["q_max"] = gen.MvarMax
            ## in case this is a renewable model
            g_dict["power_factor"] = np.sign(gen.Mvar/gen.MW)*np.cos(np.arctan(gen.Mvar/gen.MW))


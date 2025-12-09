### simple parser for egret data
from pyenergymarket.engine import DataProvider
import pandas as pd
import numpy as np
from typing import Union
from egret.data.model_data import ModelData


class EgretProvider(DataProvider):
    """simple wrapper around the egret GVParse to indicate that this is
    a subclass of DataProvider
    """

    def __init__(self, md:Union[ModelData,str], t0=""):
        """initialze the model data structure

        Args:
            md (Union[ModelData,str]): Egret Model Data
        """
        self.md = ModelData(md)
        self.timestamps = pd.DatetimeIndex(self.md.data["system"]["time_keys"])
        

    def get_model(self, daterange:Union[pd.DatetimeIndex,None]) -> ModelData:
        """Data provider callback for EnergyMarket.
        See also utils.timeutils.mk_daterange

        Args:
            daterange(Union[pd.DatetimeIndex,None], optional): the actual datetime index. Defaults to None

        Returns:
            ModelData: Egret model for specified date range
        """
        
        ### list of time points
        time_indices = np.where(self.timestamps.isin(daterange))[0].tolist()
        # Wrap if times extend beyond end # TODO: make more robust - this only works for a small extension within day
        if max(daterange) > self.timestamps.max():
            num_extra = len(daterange[daterange > self.timestamps.max()])
            time_indices += [e for e in range(num_extra)]

        ### return model
        return self.md.clone_at_time_indices(time_indices)

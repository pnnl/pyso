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

    def __init__(self, md:Union[ModelData,str]):
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
        
        if len(time_indices) < len(daterange):
            print(f"Range {daterange[0]} - {daterange[-1]} exceeds the available data. Returning {self.timestamps[time_indices[0]]} - {self.timestamps[time_indices[-1]]}.")

        ### return model
        return self.md.clone_at_time_indices(time_indices)

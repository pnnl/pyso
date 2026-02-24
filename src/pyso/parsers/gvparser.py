from typing import Union

import pandas as pd
from egret.data.model_data import ModelData
from egret.parsers.gvparser import GVParse as EgretGVParse

from pyso.engine import DataProvider


class GVParse(EgretGVParse, DataProvider):
    """simple wrapper around the egret GVParse to indicate that this is
    a subclass of DataProvider
    """

    def get_model(self, daterange: Union[pd.DatetimeIndex, None]) -> ModelData:
        """Data provider callback for EnergyMarket.
        See also utils.timeutils.mk_daterange

        Args:
            daterange(Union[pd.DatetimeIndex,None], optional): the actual datetime index.
                Defaults to None

        Returns:
            ModelData: Egret model for specified date range
        """

        ### set the date
        self.set_daterange(dt=daterange)
        ### parse
        self.parse()
        ### return model
        return self.mdl

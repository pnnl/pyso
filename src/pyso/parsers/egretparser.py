### simple parser for egret data
import copy
import os
from typing import Union

import numpy as np
import pandas as pd
from egret.data.model_data import ModelData

from pyso.engine import DataProvider
from pyso.utils.egretutils import merge_model_data


class EgretProvider(DataProvider):
    """simple class to provide egret ModelData in a given daterange"""

    def __init__(self, md: Union[ModelData, str]):
        """initialize the model data structure

        Args:
            md (Union[ModelData,str]): Egret Model Data
        """
        self.md = ModelData(md)
        self.timestamps = pd.DatetimeIndex(self.md.data["system"]["time_keys"])

    def get_model(self, daterange: Union[pd.DatetimeIndex, None]) -> ModelData:
        """Data provider callback for EnergyMarket.
        See also utils.timeutils.mk_daterange

        Args:
            daterange(Union[pd.DatetimeIndex,None], optional): the actual datetime index.
                Defaults to None

        Returns:
            ModelData: Egret model for specified date range
        """

        ### list of time points
        time_indices = np.where(self.timestamps.isin(daterange))[0].tolist()

        if len(time_indices) < len(daterange):
            print(
                f"Range {daterange[0]} - {daterange[-1]} exceeds the available data. "
                f"Returning {self.timestamps[time_indices[0]]} - "
                f"{self.timestamps[time_indices[-1]]}."
            )

        ### return model
        return self.md.clone_at_time_indices(time_indices)


class DailyEgretProvider(EgretProvider):
    """
    A class to merge daily egret files with hourly resolution
    """

    def __init__(self, filedir, date_format="%Y-%m-%d"):
        """initialize the model data structure
        Args:
            filedir (str): Path to the Egret data files
            date_format (str, optional): Date format in filenames. Defaults to '%Y-%m-%d'
        """
        self.filedir = filedir
        self.date_format = date_format

    def get_model(self, daterange: Union[pd.DatetimeIndex, None]) -> ModelData:
        """Retrieves the Egret ModelData object for engine.py

        This class will first identify which files need to be loaded (based on daterange)
        load these, merge them, then call the parent get_model on the result to get the
        correct time range.

        TODO: Add support for a time coarsening and interpolation
        (and possibly non-uniform daterange)
        """
        # Select the json file names with unique days (in self.date_format) from the daterange
        md_dates = [d.strftime(self.date_format) for d in np.unique(daterange.date)]
        files = [f for f in os.listdir(self.filedir) if "json" in f]

        # Load the model data objects for each day
        md_objects = []
        for md_date in md_dates:
            for file in files:
                if md_date in file:
                    this_md = ModelData(os.path.join(self.filedir, file))
                    md_objects.append(this_md)
                    break
            if len(md_objects) == len(md_dates):
                break

        if len(md_objects) == 0:
            raise FileNotFoundError(
                f"No egret files found in {self.filedir} for daterange {daterange}"
            )

        # Merge the model data objects into one (unless there is only one file)
        md_merged = copy.deepcopy(md_objects[0])
        if len(md_objects) > 1:
            for md_object in md_objects[1:]:
                md_merged = merge_model_data(md_merged, md_object)

        # Now call the parent EgretProvider for the given daterange
        super().__init__(md_merged)
        selected_md = super().get_model(daterange)
        selected_md.write("merge_test.json")
        return selected_md

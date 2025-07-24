from __future__ import annotations
import pandas as pd
import numpy as np
from typing import Union, Iterable

### This is for type checking and syntax highlighting
### see: https://www.youtube.com/watch?v=UnKa_t-M_kM
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .__init__ import GVParse

#### Ancillary services can be defined on areas and zones in EGRET
#### In GridView they can be defined on Areas, Regions, and Combined Regions
def as_requirements(self:GVParse):
    """Add ancilliary service requirements.
    Based on /mdb/AreaRegionAS. 
    Currently only system and load area based services are possible. 

    Raises:
        ValueError: raises value error if the Type column in AreaRegionAS is not in [0,3]
    """
    as_req = self.h5("/mdb/AreaRegionAS").loc[lambda x: x["EnforceReserve"]]
    for i in as_req.index:
        req = as_req.loc[i]
        if req.Type == 0:
            ### System
            requirement = self.get_as_requirement("system", req, "System")
            self.mdl.data["system"][f"{self.astype2egret[req.ASType]}_requirement"] = requirement
        elif req.Type == 1:
            ### Area
            if "area" not in self.mdl.data["elements"]:
                self.mdl.data["elements"]["area"] = dict()
            area_name = self.h5("/mdb/LoadArea").loc[lambda x: x["LoadAreaID"] == req.ID, "LoadAreaName"].squeeze()
            if area_name not in self.mdl.data["elements"]["area"]:
                self.mdl.data["elements"]["area"][area_name] = dict()
            requirement = self.get_as_requirement("area", req, area_name)
            self.mdl.data["elements"]["area"][area_name][f"{self.astype2egret[req.ASType]}_requirement"] = requirement
        elif req.Type == 2:
            ### Region
            self.logger.warning("WARNING: AS aggregated on Regions is not implemented. Ignoring.")
        elif req.Type == 3:
            ### Combined
            self.logger.warning("WARNING: AS aggregated on combined areas is not implemented. Ignoring.")
        else:
            raise ValueError(f"Unknown AS Requirement Area Type {req.Type}")
        

# def get_as_requirement(self:GVParse, typ:str, req:pd.Series, name:str) -> dict:
#     """get AS requirement

#     Args:
#         str: (str): area or system
#         req (pd.Series): row from the mdb/AreaRegionAS key specifying the requirement 
#         name (str): area name or "System"
#     """

#     if req.ShapeAdderFlag:
#         requirement = self.h5(f"/{typ}/{self.astype2gvkey[req.ASType]}_REQUIREMENT").loc[self.daterange, name].values
#     else:
#         # Base on percentage of load and generation
#         # we'll simplify here and simply add the BaseLoadPercent and Generation Percent
#         requirement = self.h5(f"/{typ}/LOAD").loc[self.daterange, name].values * (req.BaseLoadPercent + req.GenerationPercent)
#     return {"data_type": "time_series", "values": requirement}

def get_as_requirement(self:GVParse, typ:str, req:pd.Series, name:str) -> dict:
    """get AS requirement

    Args:
        str: (str): area or system
        req (pd.Series): row from the mdb/AreaRegionAS key specifying the requirement 
        name (str): area name or "System"
    """

    if req.ShapeAdderFlag:
        requirement = self.h5(f"/{typ}/{self.astype2gvkey[req.ASType]}_REQUIREMENT").loc[self.daterange, name].values
    else:
        # Base on percentage of load and generation
        # we'll simplify here and simply add the BaseLoadPercent and Generation Percent
        requirement = self.h5(f"/{typ}/LOAD").loc[self.daterange, name].values * (req.BaseLoadPercent + req.GenerationPercent)
    # Interpolate requirement to actual times
    # Create dataframe with daterange as index
    df = pd.DataFrame({'requirement': requirement})
    df.index = self.daterange
    # Interpolate
    df = self.interpolate_time(df)
    # Extract values
    requirement = df['requirement'].values
    return {"data_type": "time_series", "values": requirement}
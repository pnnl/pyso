from egret.parsers.gvparser import GVParse as EgretGVParse
from pyenergymarket.engine import DataProvider

class GVParse(EgretGVParse, DataProvider):
    """simple wrapper around the egret GVParse to indicate that this is
    a subclass of DataProvider
    """
    pass



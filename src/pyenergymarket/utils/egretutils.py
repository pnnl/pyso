"""Utilities related to handling egret models
"""
from egret.data.model_data import ModelData

def get_bus_id(md:ModelData, bus:str, field="id") -> int:
    """Under the ASSUMPTION that a field was added to the Egret
    model that stores an integer reference to the bus, this function
    extracts that integer given the bus key in the elements["bus"]
    dictionary

    Args:
        md (ModelData): Egret model
        bus (str): bus key in elements["bus"]
        field (str, optional): fields where integer is stored. Defaults to "id".

    Returns:
        int: bus integer identifier
    """
    return md.data["elements"]["bus"][bus][field]
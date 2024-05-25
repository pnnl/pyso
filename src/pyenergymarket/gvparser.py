from pnnlpcm.h5fun import H5
from egret.data.model_data import ModelData

class GVParse():
    def __init__(self, h5path, **kwargs):
        ## load the h5 file
        self.h5 = H5(h5path, **kwargs)
        self.mdl = ModelData() # create an empty model data object with keys "elements", "system"

    def add_buses(self):
        pass

    def add_branches(self):
        pass
        # note, will want to distinguish between lines and transformers, PARS, and dclines

    def add_generators(self):
        pass

    def add_load(self):
        pass
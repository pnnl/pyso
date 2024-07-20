"""The core functionality of pyenergymarket, encapsulated in the 
EnergyMarket class is here.
"""
from .utils.ioutils import merge_configs
from .pyenergymarket_defaults import energymarket_defaults
import abc
from egret.data.model_data import ModelData
from egret.models.unit_commitment import solve_unit_commitment, SlackType

class DataProvider(abc.ABC):
    
    @abc.abstractmethod
    def get_model(self, starttime:str, stoptime:str) -> ModelData:
        pass

class EnergyMarket:
    def __init__(self, data_provider:DataProvider, config:dict=None, **kwargs):
        """Initalize the energy market wrapper

        Args:
            data_provider (_type_): an object with method get_model 
                    with inputs date_from, date_to that returns an egret model 
        """
        self.data_provider = data_provider
        self.mdl = None
        self.mdl_sol = None
        ### get configuration
        self.configuration = energymarket_defaults.copy()
        if config is not None:
            merge_configs(self.configuration, config)

    def run_model(self, starttime:str, stoptime:str):

        # get the model
        self.mdl = self.data_provider.get_model(starttime, stoptime)

        self.mdl_sol = solve_unit_commitment(self.mdl, self.configuration["solve_arguments"]["solver"], 
                                        slack_type=SlackType[self.configuration["solve_arguments"]["slack"]],
                                        **self.configuration["solve_arguments"]["kwargs"])
        
    def save_model(self, filename:str):
        if self.mdl_sol is not None:
            self.mdl_sol.write(filename)
        elif self.mdl is not None:
            self.mdl.write(filename)
        else:
            raise ValueError("No model currently loaded.")
        

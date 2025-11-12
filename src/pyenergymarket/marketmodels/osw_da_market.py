"""
Created on 06/28/2024

Class market objects in Egret

This assumes EGRET functionality has been implemented as class functions that 
can be called as methods. (This may not be a hard assumption.)


@author: Trevor Hardy
trevor.hardy@pnnl.gov
"""
import datetime as dt
import json
import logging
import pandas as pd
import numpy as np
from transitions import Machine
from .osw_market import OSWMarket

from egret.data.model_data import ModelData

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.WARNING)

class OSWDAMarket(OSWMarket):
    """
    TODO: describe this class

    For the off-shore-wind use case, we only need three market states so
    those will be hard-coded as below. The way this market works, all of 
    the activity of the market takes place at the transitions. I'm
    (TDH) using the "transitions" library which allows the definition
    of callback functions when entering (and exiting) any given state
    and this is the primary method by which the activity will in the
    market will take place. 

    Documentation on the "transitions" library can be found here:
    https://pypi.org/project/transitions/



    """

    def __init__(self, start_date, end_date, market_name:str="da_energy_market", market_timing:dict=None,
                 min_freq:int=60, window:int=24, lookahead:int=0, **kwargs):
        """
        Class the specifically runs the OSW DA energy market

        The only specialization is the definition of the callback method
        that gets called when the market state machine enters the "clearing"
        state.
        """
        super().__init__(market_name, market_timing, start_date, end_date, **kwargs)
        # Do we need to be setting these here or are they passed as part of the EnergyMarket object?
        self.em.configuration["time"]["min_freq"] = min_freq
        self.em.configuration["time"]["window"] = window
        self.em.configuration["time"]["lookahead"] = lookahead
        # This translates all the kwarg key-value pairs into class attributes
        self.__dict__.update(kwargs)
        # if market_timing isn't specified input default vaules.
        if self.market_timing == None:
            self.market_timing = {
                "states": {
                    "idle": {
                        "start_time": 0,
                        "duration": 85800
                    },
                    "bidding": {
                        "start_time": 85800,
                        "duration": 540
                    },
                    "clearing": {
                        "start_time": 86340,
                        "duration": 60
                    },
                },
                "initial_offset": 0,
                "initial_state": "idle",
                "market_interval": 86400
            }

    def clear_market(self, local_save=False):
        """ Calls the base class clear_market method, then also does DA specific functions """
        super().clear_market(local_save=local_save)
        # Day-ahead specific market operations.
        # Right now, all we do in DA only is save the storage state-of-charge
        self.store_storage_soc()

    def store_storage_soc(self, max_intervals:int=24):
        """
        Saves the storage state-of-charge at the corresponding times. This could possible be merged into a
        common function with store_commitment_hist that accepts element type and keys, but that may be hard
        to get correct for general cases.

        Args:
            max_intervals (int): The maximum number of time intervals to save (default is 24, assuming hourly DA)
        """
        # If no storage units are in the model, don't continue
        if 'storage' not in self.em.mdl_sol.data['elements'].keys():
            return
        # Time keys - we pad the last interval since Egret gives soc values at END of interval while keys are START
        time_keys = pd.to_datetime(self.em.mdl_sol.data['system']['time_keys'])[:max_intervals]
        time_delta_end_minutes = int((time_keys[-1] - time_keys[-2]).total_seconds() / 60.0)
        time_keys = time_keys.append(pd.to_datetime([time_keys[-1] + dt.timedelta(minutes=time_delta_end_minutes)]))
        # Create dict if needed with the timestamps as a top level key (shared by all storage units)
        use_soc_init = False
        if self.storage_soc is None:
            self.storage_soc = {'system':{'time_keys': time_keys}, 'elements': {'storage': {}}}
            # The first time through we use soc init (all other times it is same as last of previous)
            use_soc_init = True
        else:
            # Don't copy the first interval (it was added last time by the end padding)
            self.storage_soc['system']['time_keys'] = self.storage_soc['system']['time_keys'].append(time_keys[1:])
        # loop through storage units
        for storage, storage_dict in self.em.mdl_sol.data['elements']['storage'].items():
            soc_values = storage_dict['state_of_charge']['values'][:max_intervals]
            if use_soc_init:
                soc_init = storage_dict['initial_state_of_charge']
                soc_values = np.append(np.array([soc_init]), soc_values)
            # If previous values are in the storage dictionary, we will append new values to the end
            if storage in self.storage_soc['elements']['storage'].keys():
                prev_soc_values = self.storage_soc['elements']['storage'][storage]['state_of_charge']['values']
                soc_values = np.append(prev_soc_values, soc_values)
            self.storage_soc['elements']['storage'][storage] = {'state_of_charge': {'data_type': 'time_series',
                                                                        'values': soc_values}}
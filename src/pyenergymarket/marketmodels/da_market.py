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
from .market import Market

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.WARNING)

class DAMarket(Market):
    """
    We only need three market states so we provide hard-coded defaults.
    The way this market works, market activity takes place at the transitions.
    I'm (TDH) using the "transitions" library which allows the definition
    of callback functions when entering (and exiting) any given state
    and this is the primary method by which the activity will in the
    market will take place.

    Documentation on the "transitions" library can be found here:
    https://pypi.org/project/transitions/
    """

    def __init__(self, start_date, end_date, market_name:str="da_energy_market", market_timing:dict=None,
                 min_freq:int=60, window:int=24, lookahead:int=0, **kwargs):
        """
        Class the specifically runs the DA energy market

        The only specialization is the definition of the callback method
        that gets called when the market state machine enters the "clearing"
        state.
        """
        # if market_timing isn't specified input default vaules.
        if market_timing == None:
            market_timing = {
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
        super().__init__(market_name, market_timing, start_date, end_date, **kwargs)
        # These update the EnergyMarket defaults with specified arguments
        self.em.configuration["time"]["min_freq"] = min_freq
        self.em.configuration["time"]["window"] = window
        self.em.configuration["time"]["lookahead"] = lookahead
        # This translates all the kwarg key-value pairs into class attributes
        self.__dict__.update(kwargs)

    def collect_bids(self):
        """ Overloaded method of Market: adding bids from generators and storage """
        elements = self.em.mdl.data['elements']
        for key in self.bids.keys():
            element_types = ['generator', 'storage']
            for element_type in element_types:
                if element_type not in elements.keys():
                    continue
                if key in elements[element_type].keys():
                    element[key] = self.bids[key]

    def clear_market(self, local_save=False):
        """ Calls the base class clear_market method, then also does DA specific functions """
        super().clear_market(local_save=local_save)
        # Day-ahead specific market operations.
        # Right now, all we do in DA only is save the storage state-of-charge


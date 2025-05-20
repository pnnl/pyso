"""
Created on 06/28/2024

Class market objects in Egret

This assumes EGRET functionality has been implemented as class functions that 
can be called as methods. (This may not be a hard assumption.)


@author: Trevor Hardy
trevor.hardy@pnnl.gov
"""
import datetime
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

    def clear_market(self, local_save:bool=False, get_mdl:bool=True):
        """
        Overloaded method of OSWMarket

        Grab all the bids and run the DA UC optimization and then return the results

        market_results is an attribute of the OSWMarket class
        """
        # Update generator starting status based on previous solution, when available
        # If doing so, do not, create a new model when calling the parent class method
        if self.em.mdl_sol is not None:
            self.em.get_model(self.current_start_time)
            self.update_model_from_previous(self.em.mdl_sol)
            get_mdl = False
        # Call osw_market.py clear market. If model was loaded and updated, do not get the model again
        super().clear_market(local_save=local_save, get_mdl=get_mdl)

    def update_model_from_previous(self, mdl_com:ModelData):
        """
        Pull last setpoint data from mdl_sol timeseries and
        update the current self.mdl with generator values from previous DA market
        """
        if (self.em.mdl is not None) and (mdl_com is not None):
            # Update generator starting output
            for g, g_dict in mdl_com.elements(element_type='generator'):
                # If we have a solution from last market, we load the power from the last time into the initial power
                if self.em.mdl_sol is not None:
                    # Get hour 23 value (if there is a lookahead, this isn't the last value)
                    if self.current_start_time in self.em.mdl_sol.data["system"]["time_keys"]:
                        tidx = np.where(self.current_start_time == np.array(self.em.mdl_sol.data["system"]["time_keys"]))[0][0]
                        tidx -= 1 # tidx above gives the first hour of this day, we want the last hour of previous day
                    # If not, use the last available time
                    else:
                        tidx = -1
                    prev_ending_p = self.em.mdl_sol.data["elements"]["generator"][g]["pg"]["values"][tidx]
                    self.em.mdl.data['elements']['generator'][g]['initial_p_output'] = prev_ending_p
                    # Update initial status for this generator
                    self.update_initial_status(g, 60)
            # Update storage unit initial/ending soc
            for s, s_dict in mdl_com.elements(element_type='storage'):
                self.update_state_of_charge(s, market_type='day_ahead')
        else:
            raise ValueError("no model currently loaded.")
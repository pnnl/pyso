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
import os
import logging
import pandas as pd
import numpy as np
from transitions import Machine
from .osw_market import OSWMarket
from ..utils.ioutils import Logger
from ..utils.timeutils import mk_daterange
import copy

# from typing import TYPE_CHECKING
# if TYPE_CHECKING:
from egret.data.model_data import ModelData

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.WARNING)

class OSWRTMarket(OSWMarket):
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

    def __init__(self, start_date, end_date, market_name:str="rt_energy_market", market_timing:dict=None, min_freq:int=15,
                 window:int=4, lookahead:int=0, **kwargs):
        """
        Class that specifically runs the OSW RT energy market

        The only specialization is the definition of the callback method
        that gets called when the market state machine enters the "clearing"
        state.
        """
        # Supply a default market timing object for a 15-minute real-time
        if market_timing == None:
            market_timing = {
                "states": {
                    "idle": {
                        "start_time": 0,
                        "duration": 600
                    },
                    "bidding": {
                        "start_time": 600,
                        "duration": 180
                    },
                    "clearing": {
                        "start_time": 780,
                        "duration": 120
                    }
                },
                "initial_offset": 0,
                "initial_state": "idle",
                "market_interval": 900
            }
        super().__init__(market_name, market_timing, start_date, end_date, **kwargs)
        self.em.configuration["time"]["min_freq"] = min_freq
        self.em.configuration["time"]["window"] = window
        self.em.configuration["time"]["lookahead"] = lookahead
        self.__dict__.update(kwargs)
            # starts at midnight
        self.start_times = self.interpolate_market_start_times(start_date, end_date, freq=f'{min_freq}min')
        # Space for day-ahead solution (used in the first clear_market call)
        self.da_mdl_sol = None
        self.fixed_commitment = True # Option to use a fixed or flexible commitment

    def update_em_model(self):
        """ Applies updates to the Egret model before solving. Logic to use either previous RT or DA input
        """
        # Default is to calculate values based on previous solution
        update_mode = 'calculate'
        use_sol = self.em.mdl_sol
        # For first RT market, we will copy starting values from the first DA market.
        if self.em.mdl_sol is None:
            update_mode = 'copy'
            use_sol = self.da_mdl_sol
        # Update generator initial power and initial status
        self.em.update_initial_conditions(use_sol, update_mode=update_mode)
        # If using a pre-simulation, there may be infeasibilities in the first RT interval, so we require a fix
        # Check for the conditions in which this can happen
        fix_infeasible = False
        if self.em.mdl_sol is None:
            # Only apply fix_infeasible when no previous real-time model exists and we have at least 1
            # pre-simulation day
            if self.pre_simulation_days is not None:
                if self.pre_simulation_days > 0:
                    fix_infeasible = True
        self.update_model_commitment(fix_infeasible=fix_infeasible)

    def clear_market(self, local_save:bool=False):
        """
        Callback method that runs EGRET and clears a market.

        This method must be overloaded in an instance of this class to
        implement the necessary operates to clear the market in question.

         Args:
            local_save (bool, optional): if True, will save a JSON with the results at each timestep
        """
        if self.current_start_time > max(self.start_times):
            logger.warning(f"RT Market: Current start time {self.current_start_time} is past horizon {max(self.start_times)}"
                           "Market will not be cleared")
            return
        self.em.get_model(self.current_start_time)
        self.update_em_model()
        # self.em.mdl.write(f'data/{self.market_name}_model_{self.timestep}.json')
        self.em.solve_model()
        self.market_results = self.em.mdl_sol
        # If using fixed commitment history we do not want to update this during real-time
        if not self.fixed_commitment:
            self.update_commitment_hist()
        if local_save:
            os.makedirs('data', exist_ok=True)
            self.em.save_model(f'data/{self.market_name}_results_{self.timestep}.json')

        self.timestep += 1
        if self.timestep >= len(self.start_times):
            # Add a day (exact value doesn't matter, just need something past the horizon)
            min_freq = self.em.configuration["time"]["min_freq"]
            self.current_start_time += datetime.timedelta(minutes=min_freq)
        else:
            self.current_start_time = self.start_times[self.timestep]

    def join_da_commitment(self, da_commitment:dict):
        """
        Takes the day-ahead commitment schedule and interpolates onto the real-time intervals
        Commitment values are kept constant for each hour
        Default behavior is to NOT overwrite any existing values. This is intended to be run after each
        day-ahead market clearing to add the coming day's commitment values
        """
        # Duplicate day-ahead values onto the (likely) more frequent real-time intervals
        min_freq = self.em.configuration["time"]["min_freq"]
        # Update the da_commitment timestamps - add an hour to the last timestamp to ensure we go to the end of the day
        end = max(da_commitment["timestamps"])
        if isinstance(end, str):
            # Assumes format "YYYY-mm-dd HH:MM:SS". Convert to datetime, add hour, then convert back to str
            end = pd.to_datetime(end) + datetime.timedelta(hours=1)
            end = end.strftime('%Y-%m-%d %H:%M:%S')
        else: # Hopefully any other datetime form or this will fail
            end += datetime.timedelta(hours=1)
        # Note inclusive='left' ensures we do not get 00:00:00 on the next day (assuming 24hr input)
        da_timestamps_interp = pd.to_datetime(mk_daterange(start=min(da_commitment["timestamps"]),
                                                           end=end, min_freq=min_freq, inclusive='left'))
        # Loop through all generators
        da_commitment_interp = {'timestamps': da_timestamps_interp}
        for etype, edict in da_commitment.items():
            if etype != 'timestamps':
                for unit, u_dict in edict.items():
                    # Create dictionary structure the first time through
                    da_commitment_interp = self._prep_commitment_hist(da_commitment_interp, etype, unit)
                    # Call the fill_real_time function on this set of values
                    da_commitment_interp[etype][unit]['commitment']['values'] = (
                        self.fill_real_time(u_dict['commitment']['values']))
                    # Add initial status
                    da_commitment_interp[etype][unit]['initial_status'] = u_dict['initial_status']
        # Call method from the base class. Keep old ensures RT values aren't overwritten.
        # This will just add any new da_commitment values to the existing commitment history
        self.update_commitment_hist(keep='old', merge_dict=da_commitment_interp)

    def fill_real_time(self, da_list:list) -> list:
        """
        Takes a list of values from the (hourly) day-ahead market and copies into a longer
        list based on the real-time frequency in minutes. For example, if min_freq=15
        this will copy each hourly values four times.

        Args:
            da_list (list): list of any kind of value from market day-ahead market
        Returns:
            rt_list (list): list of values copied into the real-time frequency
        """
        min_freq = self.em.configuration["time"]["min_freq"]
        # Determine the number of times to copy values
        remainder = 60 % min_freq
        if remainder != 0:
            logger.warning(f"Parameter min_freq {min_freq} is not a divisor of 60. Results may be inaccurate")
        num_copy = int(60 / min_freq)
        # Use numpy arrays and repeat function for fast copying
        da_array = np.array(da_list)
        rt_array = da_array.repeat(num_copy)
        return list(rt_array)

    def _fix_infeasible(self, gen:str):
        """ Checks for conflicts with initial status and commitment and adjusts so solution is feasible in Egret
            Note, these fixes ensure feasibility but may not be the ideal choices for all physical scenarios.
        """
        def _get_pmin(g_dict):
            """ Gets pmin value, grabbing 1st value if a timeseries dict is used """
            if isinstance(g_dict["p_min"],dict):
                pmin = g_dict["p_min"]['values'][0]
            else:
                pmin = g_dict["p_min"]
            g_dict['initial_p_output'] = pmin
            return pmin

        g_dict = self.em.mdl.data['elements']['generator'][gen]
        # Don't change wind/solar
        if g_dict["fuel"] in ['Solar', 'Wind']:
            return
        # If starting with power and committed off set to p_min
        if g_dict['initial_p_output'] > 0 and g_dict['fixed_commitment']['values'][0] == 0:
            pmin = _get_pmin(g_dict)
            g_dict['initial_p_output'] = pmin
            # Set status to minimum up time since it just turned off
            minimum_up_time = 0
            if 'minimum_up_time' in g_dict.keys():
                minimum_up_time = g_dict['minimum_up_time']
            elif 'min_up_time' in g_dict.keys():
                minimum_up_time = g_dict['min_up_time']
            g_dict['initial_status'] = max(1, minimum_up_time)
        elif g_dict['initial_p_output'] == 0 and g_dict['fixed_commitment']['values'][0] == 1:
            pmin = _get_pmin(g_dict)
            # Set status to -minimum down time since it just turned on
            minimum_down_time = 0
            if 'minimum_down_time' in g_dict.keys():
                minimum_down_time = g_dict['minimum_down_time']
            elif 'min_down_time' in g_dict.keys():
                minimum_down_time = g_dict['min_down_time']
            g_dict['initial_status'] = -max(1, minimum_down_time)

    def update_model_commitment(self, fix_infeasible:bool=False):
        """
        Pull last setpoint data from mdl_sol timeseries and
        update the current self.mdl with generator values from solution.

        Args:
            fix_infeasible (bool, optional): if True, fix possible infeasible states in self.em.mdl
        """
        # Windows
        time_window = self.em.configuration['time']['window']
        lookahead = self.em.configuration['time']['lookahead']
        logger.debug(f"Updating commitment history for RT market at timestep {self.timestep}"
                     f"(time is {self.current_start_time}")
        if self.em.mdl is not None:
            for g, g_dict in self.em.mdl.elements(element_type='generator'):
                # Load the commitment history for this generator
                commit_hist = self.commitment_hist['generator'][g]
                # Match timestamps to find the appropriate index from the commitment history
                if self.current_start_time in self.commitment_hist['timestamps']:
                    t0idx = np.where(self.current_start_time == np.array(self.commitment_hist['timestamps']))[0][0]
                else:
                    raise ValueError(f"Time {self.current_start_time} is not in commitment history timestamps.")

                # It is possible for t0idx in the last interval to have no commitments available (if no day-ahead
                # lookahead) If so, there are no commitments to add. Otherwise, pass the commitments for the
                # appropriate window
                if t0idx < len(commit_hist['commitment']['values']):
                    commit_hist_window = commit_hist['commitment']['values'][t0idx:t0idx + time_window + lookahead]
                    # If missing lookahead (possible at end of horizon) duplicate the last value
                    if len(commit_hist_window) < time_window + lookahead:
                        add_len = time_window + lookahead - len(commit_hist_window)
                        # Handling for list or array format
                        if isinstance(commit_hist_window, list):
                            commit_hist_window = commit_hist_window + [commit_hist_window[-1]]*add_len
                        elif isinstance(commit_hist_window, np.ndarray):
                            commit_hist_window = np.concatenate((commit_hist_window, np.ones(add_len)*commit_hist_window[-1]))
                    # Standard behavior is to fix commitment, but we can send commitment without fixing if we want
                    # a more flexible RT market.
                    if self.fixed_commitment:
                        # Only fix the values in the window (Set all lookahead values to None)
                        # commit_hist_window[time_window:] = [None for i in range(len(commit_hist_window[time_window:]))]
                        g_dict['fixed_commitment'] = {'data_type':'time_series', 'values': commit_hist_window}
                        # Pass to check for scenarios that give infeasible results (only if taking initial DA input)
                        if fix_infeasible:
                            self._fix_infeasible(g)
                    else:
                        g_dict['commitment'] = {'data_type': 'time_series', 'values': commit_hist_window}
        else:
            raise ValueError("no model currently loaded.")
    

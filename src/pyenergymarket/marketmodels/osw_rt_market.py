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
from ..utils.timeutils import mk_daterange
from ..utils.ioutils import Logger
# from egret.model_library.extensions.pcm_acopf.tools.model_data_manipulation import add_load_curtail
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
                 window:int=4, lookahead:int=0, fixed_commitment=True, unfix_fast_start=False, **kwargs):
        """
        Class that specifically runs the OSW RT energy market

        The only specialization is the definition of the callback method
        that gets called when the market state machine enters the "clearing"
        state.
        """
        super().__init__(market_name, market_timing, start_date, end_date, **kwargs)
        self.em.configuration["min_freq"] = min_freq
        self.em.configuration["time"]["window"] = window
        self.em.configuration["time"]["lookahead"] = lookahead
        self.em.configuration["window"] = window + lookahead
        self.__dict__.update(kwargs)
        if self.market_timing == None:
            self.market_timing = {
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
            # starts at midnight
        # Start times jump ahead by the window size (in intervals)*frequency (in minutes)
        min_window = int(min_freq*window)
        self.start_times = self.interpolate_market_start_times(start_date, end_date, freq=f'{min_window}min')
        # Space for day-ahead solution (used at initialization)
        self.da_mdl_sol = None
        self.fixed_commitment = fixed_commitment # Option to use a fixed or flexible commitment
        self.unfix_fast_start = unfix_fast_start # Fast start units can remain flexible in RT

    # def collect_bids(self, gen_commitment):
    #     """
    #     Callback method that pulls in bids to grid data and moves to the next state.

    #     This method must be overloaded in an instance of this class to
    #     implement the necessary operatations to update the market in question.
    #     """
    #     self.move_to_next_state()


    def interpolate_market_start_times(self, start_date:str, end_date:str, freq:str='15min',
                                       start_time:str=' 00:00:00'):
        """
        Overloaded method of OSWMarket:
        Interpolates 15 (by default) minute data between two date strings.
        """

        # Convert strings to datetime objects
        start_datetime = pd.to_datetime(start_date)# + start_time)
        end_datetime = pd.to_datetime(end_date)# - pd.Timedelta(freq)# + start_time)

        # Generate hourly datetime index
        start_time_index = pd.date_range(start_datetime, end_datetime, freq=freq, inclusive='left')
        return start_time_index

    def update_em_model(self, contingency_list=None):
        """ Applies updates to the Egret model before solving. Logic to use either previous RT or DA input
        """
        # Update generator initial power and initial status
        # For first RT market, we will copy starting values from the first DA market.
        update_mode = 'calculate'
        if self.em.mdl_sol is None:
            update_mode = 'copy'
        self.em.update_initial_conditions(self.em.mdl_sol, update_mode=update_mode)
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
        self.apply_contingencies(contingency_list=contingency_list)
        self.update_storage()
        self.add_gens()

    def clear_market(self, contingency_list:list=None):
        """
        Callback method that runs EGRET and clears a market.

        This method must be overloaded in an instance of this class to
        implement the necessary operates to clear the market in question.

        """
        if self.current_start_time > max(self.start_times):
            logger.warning(f"RT Market: Current start time {self.current_start_time} is past horizon {max(self.start_times)}"
                           "Market will not be cleared")
            return
        self.em.get_model(self.current_start_time)
        self.update_em_model(contingency_list=contingency_list)
        # self.em.mdl.write(f'data/{self.market_name}_model_{self.timestep}.json')

        # self.collect_bids()

        try:
            self.em.solve_model()
        except:
            logger.error("\nException found - error solving model. Retrying with doubled ramp rates.\n")
            for g, g_dict in self.em.mdl.elements(element_type='generator'):
                ramp_keys = ["ramp_up_60min", "ramp_down_60min"]
                for ramp_key in ramp_keys:
                    if ramp_key in g_dict.keys():
                        g_dict[ramp_key] = g_dict[ramp_key] * 2
            for s, s_dict in self.em.mdl.elements(element_type='storage'):
                ramp_keys = ["ramp_up_input_60min", "ramp_down_input_60min", "ramp_up_output_60min", "ramp_down_output_60min"]
                for ramp_key in ramp_keys:
                    if ramp_key in s_dict.keys():
                        s_dict[ramp_key] = s_dict[ramp_key] * 2
            self.em.solve_model()

        for g in self.em.mdl.data['elements']['generator']:
            print(self.market_name, g)

        # Put back in_service=False branches (these are removed by default in Egret solution)
        self.restore_lines()
        self.market_results = self.em.mdl_sol
        # If using fixed commitment history we do not want to update this during real-time
        if not self.fixed_commitment:
            self.store_commitment_hist()
        if self.local_save:
            os.makedirs('data', exist_ok=True)
            self.em.save_model(f'data/{self.market_name}_results_{self.timestep}.json')

        self.timestep += 1
        if self.timestep >= len(self.start_times):
            # Add an interval (exact value doesn't matter, just need something past the horizon)
            min_freq = self.em.configuration["min_freq"]
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
        min_freq = self.em.configuration["min_freq"]
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
        self.store_commitment_hist(keep='old', merge_dict=da_commitment_interp)

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
        min_freq = self.em.configuration["min_freq"]
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
                            commit_hist_window = commit_hist_window + [commit_hist_window[-1]] * add_len
                        elif isinstance(commit_hist_window, np.ndarray):
                            commit_hist_window = np.concatenate(
                                (commit_hist_window, np.ones(add_len) * commit_hist_window[-1]))
                    # Standard behavior is to fix commitment, but we can send commitment without fixing if we want
                    # a more flexible RT market.
                    if self.fixed_commitment:
                        # Only fix the values in the window (Set all lookahead values to None) - Not using this...
                        # commit_hist_window[time_window:] = [None for i in range(len(commit_hist_window[time_window:]))]
                        commit_type = 'fixed_commitment'
                        # Option to unfix commitment for fast-start units. Variables are still passed to 'commitment'
                        # Fixed ON (1) will remain, but fixed off (0) will be allowed to vary
                        if self.unfix_fast_start:
                            if 'fast_start' in g_dict.keys() and g_dict['fast_start']:
                                # If all are on (1) don't change. Otherwise check for all off or mix of on/off
                                if sum(commit_hist_window) == time_window + lookahead:
                                    pass
                                # If all are off, pass these to the commitment variable (starts as off, but allows turn on)
                                elif sum(commit_hist_window) == 0:
                                    commit_type = 'commitment'
                                # Special case - mixed commitment. Pass all to commitment AND fix any 1 values
                                # but use None instead of 0 for off
                                else:
                                    g_dict['commitment'] = {'data_type': 'time_series', 'values': commit_hist_window}
                                    commit_hist_window = [v if v == 1 else None for v in commit_hist_window]
                        # Update the commitment (fixed_commitment or commitment for fast-start units)
                        g_dict[commit_type] = {'data_type': 'time_series', 'values': commit_hist_window}
                        # Pass to check for scenarios that give infeasible results (only if taking initial DA input)
                        if fix_infeasible:
                            self._fix_infeasible(g)
                    else:
                        g_dict['commitment'] = {'data_type': 'time_series', 'values': commit_hist_window}
        else:
            raise ValueError("No Egret model currently loaded.")

    def update_storage(self):
        """ Calls osw_market.update_state_of_charge for each storage unit """
        for s, _ in self.em.mdl.elements(element_type='storage'):
            self.update_state_of_charge(s, market_type='real_time')
### simple parser for egret data
import copy
import gzip
import json
from datetime import datetime
from typing import Union

import h5py
import numpy as np
import pandas as pd
from egret.data.model_data import ModelData

from pyso.engine import DataProvider
from pyso.utils.ioutils import Logger

# Initialize logger
logger = Logger("naermparser", msg_format="[{levelname}] {message}")

########
# Helper functions
########


def read_json_gzip(file_path: str):
    """
    Reads a gzipped JSON file and returns its content as a Python object.
    Args:
        file_path (str): The path to the .json.gz file.
    Returns:
        dict or list: The Python object parsed from the JSON data.
    """
    try:
        with gzip.open(file_path, "rt", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except FileNotFoundError:
        logger.error(f"Error: File not found at {file_path}")
        return None
    except json.JSONDecodeError:
        logger.error(
            f"Error: Could not decode JSON from {file_path}. Ensure it's a valid JSON file."
        )
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        return None


def read_str_array_from_h5(h5f):
    return np.array([e.decode("utf-8") for e in h5f[:]], dtype=str)


def is_time_series(elem):
    if not isinstance(elem, dict):
        return False
    return (
        elem.get("data_type", None) == "time_series"
        and "time_series_uid" in elem
        and "scale_factor" in elem
    )


def create_ts_uid_to_idx_map(ts_uid):
    ts_uid_to_idx = {}
    for idx, uid in enumerate(ts_uid):
        ts_uid_to_idx[uid] = idx
    return ts_uid_to_idx


def clean_egret_time_series(ts):
    del ts["time_series_uid"]
    if isinstance(ts["scale_factor"], list):
        ts["reference_value"] = sum(ts["scale_factor"])
    elif isinstance(ts["scale_factor"], float):
        ts["reference_value"] = ts["scale_factor"]
    else:
        raise TypeError(f"scale factor({ts['scale_factor']}) is neither float or list")
    del ts["scale_factor"]
    if "scale_factor_idx" in ts:
        del ts["scale_factor_idx"]
    return None


def assign_ts_values(elem_ts: dict, ts: dict, ts_uid_to_idx: dict):
    # make values into explicit lists
    ts_uid = elem_ts["time_series_uid"]
    ts_scale_factor = elem_ts["scale_factor"]
    if isinstance(ts_uid, str):
        elem_ts["values"] = np.array(
            ts_scale_factor * ts["values"][:, ts_uid_to_idx[ts_uid]], dtype=float
        ).tolist()
    elif isinstance(ts_uid, list):
        if len(ts_uid) != len(ts_scale_factor):
            raise ValueError("incorrect dimensions")
        elem_ts["values"] = np.zeros(ts["values"].shape[0], dtype=float)
        for i in range(len(ts_uid)):
            elem_ts["values"] += np.array(
                ts_scale_factor[i] * ts["values"][:, ts_uid_to_idx[ts_uid[i]]], dtype=float
            )
        elem_ts["values"] = elem_ts["values"].tolist()
    else:
        raise TypeError(f"unexpected time series structure: {ts_uid}")
    # remove metadata not necessary for Egret and return
    clean_egret_time_series(elem_ts)
    return None


def is_persistent_time_series(x):
    return isinstance(x, dict) and x.get("data_type", None) == "persistent_time_series"


def get_persistent_ts_value(pts: dict, unixtime: int):
    idx = next((i for i, x in enumerate(pts["timestamps"]) if x > unixtime), None)
    if idx is None:
        idx = -1
    elif idx > 0:
        idx = idx - 1
    else:
        raise ValueError(f"persistent time series {pts} does not contain {unixtime}")
    return pts["values"][idx]


def is_egret_time_series(x):
    return isinstance(x, dict) and x.get("data_type", None) == "time_series"


def enforce_p_min_p_max_consistency(md_elem_gen: dict):
    corrected_gens = []
    lost_production = 0.0
    for gen_uid, gen in md_elem_gen.items():
        if gen["generator_type"] != "renewable" or gen.get("model_type", None) not in (
            "HY",
            "WT",
            "PV",
        ):
            continue
        if is_egret_time_series(gen.get("p_max", None)) and is_egret_time_series(
            gen.get("p_min", None)
        ):
            if len(gen["p_min"]["values"]) != len(gen["p_max"]["values"]):
                raise ValueError(f"incompatible time series dimensions for gen_uid={gen_uid}.")
            gen_p_min = gen["p_min"]["values"]
            gen_p_max = gen["p_max"]["values"]
            nsteps = len(gen_p_min)
            idx = [i for i in range(nsteps) if gen_p_min[i] > gen_p_max[i]]
            if len(idx) > 0:
                corrected_gens.append(gen_uid)
                lost_production += sum(gen_p_max[i] for i in idx)
                for i in idx:
                    gen["p_min"]["values"][i] = 0.0
                    gen["p_max"]["values"][i] = 0.0
        elif is_egret_time_series(gen.get("p_max", None)):
            gen_p_min = gen["p_min"]
            gen_p_max = gen["p_max"]["values"]
            nsteps = len(gen_p_max)
            idx = [i for i in range(nsteps) if gen_p_min > gen_p_max[i]]
            if len(idx) > 0:
                corrected_gens.append(gen_uid)
                lost_production += sum(gen_p_max[i] for i in idx)
                gen["p_min"] = copy.deepcopy(gen["p_max"])
                gen["p_min"]["reference_value"] = gen_p_min
                idx_set = set(idx)
                for i in range(nsteps):
                    if i in idx_set:
                        gen["p_min"]["values"][i] = 0.0
                        gen["p_max"]["values"][i] = 0.0
                    else:
                        gen["p_min"]["values"][i] = gen_p_min
        elif is_egret_time_series(gen.get("p_min", None)):
            gen_p_min = gen["p_min"]["values"]
            gen_p_max = gen["p_max"]
            nsteps = len(gen_p_min)
            idx = [i for i in range(nsteps) if gen_p_min[i] > gen_p_max]
            if len(idx) > 0:
                corrected_gens.append(gen_uid)
                lost_production += sum(gen_p_min[i] - gen_p_max for i in idx)
                idx_set = set(idx)
                for i in idx_set:
                    gen["p_min"]["values"][i] = gen_p_max
    if len(corrected_gens) > 0:
        logger.warning(
            f"Removed {lost_production:.1f}MWh of generation to ensure consistency "
            f"of p_min/p_max. Affected {len(corrected_gens)} generators: {corrected_gens}"
        )
    return None


def remove_non_time_series(md_elem):
    for elem_type in md_elem:
        fixed_elem_fields = []
        for elem_k, elem in md_elem[elem_type].items():
            fixed_fields = {}
            for prop_k, prop in elem.items():
                if is_egret_time_series(prop) and len(prop.get("values", [])) == 1:
                    fixed_fields[prop_k] = prop["values"][0]
            for prop_k, value in fixed_fields.items():
                elem[prop_k] = value
            if len(fixed_fields) > 0:
                fixed_elem_fields.append((elem_k, list(k for k in fixed_fields)))
        if len(fixed_elem_fields) > 0:
            logger.warning(
                f"Fixed single-valued time series at {elem_type} with (key, properties) = {fixed_elem_fields}"
            )
    return None


def create_egret_md(md: dict, ts: dict):
    # replace time series references with values
    ts_uid_to_idx = create_ts_uid_to_idx_map(ts["uid"])
    for _h, elem in md["elements"]["generator"].items():
        for _k, v in elem.items():
            if not is_time_series(v):
                continue
            assign_ts_values(v, ts, ts_uid_to_idx)
    for _h, elem in md["elements"]["load"].items():
        for _k, v in elem.items():
            if not is_time_series(v):
                continue
            assign_ts_values(v, ts, ts_uid_to_idx)
    # replace persistent time series for values
    # NOTE:
    if ts["timestamp"][-1] - ts["timestamp"][0] > 168 * 3600:
        logger.warning(
            "You have selected a date range spanning more than 1 week. Note that "
            "Persistent Time Series are converted to values instead of Egret time series, "
            "which works well for persistence beyond market clearing timelines. Supporting "
            "conversion to time series will require modification of Egret to support "
            "time_series in all parameters."
        )
    ref_unixtime = np.floor(np.mean([ts["timestamp"][0], ts["timestamp"][-1]]))
    for _h, elem in md["elements"]["branch"].items():
        for k, v in elem.items():
            if not is_persistent_time_series(v):
                continue
            elem[k] = get_persistent_ts_value(v, ref_unixtime)
    for _h, elem in md["elements"]["generator"].items():
        for k, v in elem.items():
            if not is_persistent_time_series(v):
                continue
            elem[k] = get_persistent_ts_value(v, ref_unixtime)
    # ensure values for p_min/p_max are consistent
    enforce_p_min_p_max_consistency(md["elements"]["generator"])
    # remove all time series that actually fixed values
    remove_non_time_series(md["elements"])
    # add time series keys to system
    # md["system"]["time_keys"] = [
    #    datetime.fromtimestamp(tstamp).strftime("%Y-%m-%d %H:%M GMT") for tstamp in ts["timestamp"]
    # ]
    md["system"]["time_keys"] = [int(tstamp) for tstamp in ts["timestamp"]]
    # all done, return dictionary to caller
    return md


########
# Time series handler definition
########


class TimeSeries:
    def __init__(self, time_series_fname: str):
        """initialize the metadata time series strucutre
        Args:
            time_series_fname (str): path to HDF5 time series file. h5 object contains 4 keys:
                name (np.array[str]): vector of time series' names
                uid (np.array[str]): vector of time series' uids
                timestamps (np.array[double]): vector of unix timestamps
                values (np.array[float]): array of time series values with dimensions
                                          #timestamps x #time series
        """
        self.__ts_file_handle = h5py.File(time_series_fname, "r")
        self.name = read_str_array_from_h5(self.__ts_file_handle["name"])
        self.uid = read_str_array_from_h5(self.__ts_file_handle["uid"])
        self._timestamp = self.__ts_file_handle["timestamp"][:]
        self._values = self.__ts_file_handle["values"]

    def __del__(self):
        """close HDF5 file"""
        self.__ts_file_handle.close()

    def _unix_tmstamp_to_idx_forw(self, unix_tmstamp: int):
        """finds relative index of first timestamp equal or greater than unix_tmstamp"""
        idx = next((i for i, x in enumerate(self._timestamp) if x >= unix_tmstamp), None)
        if idx is None:
            raise ValueError(f"{unix_tmstamp} not contained within or after time series range")
        return idx

    def _unix_tmstamp_to_idx_back(self, unix_tmstamp: int):
        """finds relative index of last timestamp equal or smaller than unix_tmstamp"""
        n = len(self._timestamp)
        idx = next(
            (n - 1 - j for j, x in enumerate(reversed(self._timestamp)) if x <= unix_tmstamp), None
        )
        if idx is None:
            raise ValueError(f"{unix_tmstamp} not contained within or before time series range")
        return idx

    def asdict(self, unix_tstart: Union[int, None] = None, unix_tend: Union[int, None] = None):
        """constructs and returns time series dictionary with timestamps within a time interval
        Args:
            unix_tstart (Union[int, None]): unix timestamp for start of time interval. Defaults to
                                            None, which indicates start of the timestamps in the
                                            TimeSeries object.
            unix_tend (Union[int, None]): unix timestamp for end of time interval. Defaults to
                                          None, which indicates end of the timestamps in the
                                          TimeSeries object.
        Returns:
            dict: time series dictionary with all timestamps within the specified window
        """
        # get relative indices
        if unix_tstart is None:
            idx_start = 0
        else:
            idx_start = self._unix_tmstamp_to_idx_forw(unix_tstart)
        if unix_tend is None:
            idx_end = len(self._timestamp)
        else:
            idx_end = self._unix_tmstamp_to_idx_back(unix_tend) + 1
        # create dictionary and return
        ts_dict = {
            "name": self.name,
            "uid": self.uid,
            "timestamp": self._timestamp[idx_start:idx_end],
            "values": np.array(self._values[idx_start:idx_end, :], order="F"),
        }
        return ts_dict


########
# GPCM Interface helper functions
########

# Canonical mapping of common US time abbreviations to UTC offsets
_ABBREV_TO_UTC_OFFSET = {
    # Pacific
    "PST": "-08:00",
    "PDT": "-07:00",
    # Mountain
    "MST": "-07:00",
    "MDT": "-06:00",
    # Central
    "CST": "-06:00",
    "CDT": "-05:00",
    # Eastern
    "EST": "-05:00",
    "EDT": "-04:00",
}


def tz_abbrev_to_utc_offset(abbrev: str) -> str:
    """
    Map a common US time zone abbreviation to a UTC offset string.

    Supported abbreviations:
      PST, PDT, MST, MDT, CST, CDT, EST, EDT

    Parameters
    ----------
    abbrev : str
        Time zone abbreviation, case insensitive. For example:
          "PST", "pst", "EDT", "edt"

    Returns
    -------
    str
        UTC offset string in the form "+HH:MM" or "-HH:MM", for example:
          "-08:00", "-05:00", "+00:00"

    Raises
    ------
    ValueError
        If the abbreviation is not recognized.
    """
    key = abbrev.strip().upper()
    try:
        return _ABBREV_TO_UTC_OFFSET[key]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported time zone abbreviation: {abbrev}. "
            f"Supported values: {', '.join(sorted(_ABBREV_TO_UTC_OFFSET.keys()))}"
        ) from exc


def date_value_to_persistent_time_series(date_value_dict: dict, utc_shift: str):
    out = {"data_type": "persistent_time_series", "timestamps": [], "values": []}
    for date, value in sorted(date_value_dict.items()):
        timestamp = int(datetime.fromisoformat(f"{date}T00:00:00{utc_shift}").timestamp())
        out["timestamps"].append(timestamp)
        out["values"].append(value)
    return out


def parse_monthly_gas_prices(monthly_gas_prices_fname: str, tz_abbrev: str = "EST"):
    """function to parse monthly gas prices coming from GPCM
    Args:
        monthly_gas_prices_fname (str): path to JSON gas prices file, structured as dict
                                        {
                                            "plantid": {
                                                "yyyy-mm-dd": price, ...
                                            }
                                        }
        tz_abbrev (str, optional): time zone used to go from yyyy-mm-dd to timestamp
                                   (instead of relying on locale)
    """

    # read JSON file with prices
    try:
        with open(monthly_gas_prices_fname) as f:
            gas_prices = json.load(f)
    except FileNotFoundError:
        logger.error(f"Error: File not found at {monthly_gas_prices_fname}")
        return None
    except json.JSONDecodeError:
        logger.error(
            f"Error: Could not decode JSON from {monthly_gas_prices_fname}. Ensure it's a valid JSON file."
        )
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        return None

    # convert each value onto a persistent time series
    utc_shift = tz_abbrev_to_utc_offset(tz_abbrev)
    out = {}
    for k, v in gas_prices.items():
        out[int(k)] = date_value_to_persistent_time_series(v, utc_shift)

    # return parsed file
    return out


def is_gas_generator(gen: dict):
    return "NG" in gen.get("fuel", "NA")

def get_eia_plantid_fraction(eia_data: dict, eia_pmax_used_key: str):
    if "plantid" in eia_data:
        return { int(eia_data["plantid"]): 1.0 }
    elif eia_data.get("data_type", None) == "multiple_eia":
        out = { int(eia_record["plantid"]): eia_record["eia_allocation"] * \
                eia_record[eia_pmax_used_key] \
                for eia_record in eia_data["values"]}
        eia_capacity = sum(out.values())
        if eia_capacity != 0.0:
            for k in out:
                out[k] /= eia_capacity
        else:
            unif_fraction = 1.0/len(eia_data["values"])
            for k in out:
                out[k] = unif_fraction
        return out
    else:
        raise ValueError(f"unexpected EIA data structure: {eia_data}")

def linear_combination_gas_prices(gas_prices: dict, eia_plantid_fraction: dict, abs_tol: float=1E-8):
    combined_gas_price = None
    cumm_fraction = 0.0
    missing_eia_codes = []
    for plantid, fraction in eia_plantid_fraction.items():
        if plantid in gas_prices:
            gas_price_contrib = copy.deepcopy(gas_prices[plantid])
            gas_price_contrib["values"] = [gp * fraction for gp in gas_price_contrib["values"]]
            if combined_gas_price is None:
                combined_gas_price = gas_price_contrib
            else:
                for i in range(len(combined_gas_price["values"])):
                    combined_gas_price["values"][i] += gas_price_contrib["values"][i]
            cumm_fraction += fraction
        else:
            missing_eia_codes.append(plantid)
    if combined_gas_price is None:
        return combined_gas_price, missing_eia_codes
    if abs(cumm_fraction - 1.0) > abs_tol:
        logger.warning(
            f"Non unitary factor (cumm_fraction={cumm_fraction}) for "
            f"eia_plantid_fraction={eia_plantid_fraction}. Will re-scale gas prices."
        )
        combined_gas_price["values"] = [gp / cumm_fraction for gp in combined_gas_price["values"]]
    return combined_gas_price, missing_eia_codes


########
# NAERM Data provider definition
########


class NAERMProvider(DataProvider):
    def __init__(
        self, static_fname: str, time_series_fname: str, gas_prices_fname: Union[str, None] = None
    ):
        """initialize the static structure and opens handle to time series data
        Args:
            static_fname (str): path to static information JSON (Egret precursor) file
            time_series_fname (str): path to HDF5 time series file (see TimeSeries class for
                                     format details)
            gas_prices_fname (str, optional): path to JSON file containing gas prices from GPCM
                                              (see parse_monthly_gas_prices for format details)
        """
        # read all data into memory (this will be revisited later, as necessary)
        self.__static_data = read_json_gzip(static_fname)
        if gas_prices_fname is not None:
            self._override_gas_prices(gas_prices_fname)
        self.__time_series = TimeSeries(time_series_fname)

    def _override_gas_prices(self, gas_prices_fname: str):
        """function to override gas prices with monthly gas prices coming from GPCM
        Args:
            gas_prices_fname (str): path to JSON file containing gas prices from GPCM
                                    see parse_monthly_gas_prices for format details
        """
        # parse gas prices
        gas_prices = parse_monthly_gas_prices(gas_prices_fname)
        # assign gas prices to gas generators using EIA plant IDs
        eia_pmax_used_key = self.__static_data["system"]["eia_pmax_used"]
        missing_generators = []
        missing_eia_codes = []
        for gen_uid, gen in self.__static_data["elements"]["generator"].items():
            if not is_gas_generator(gen):
                continue
            eia_plantid_fraction = get_eia_plantid_fraction(gen["eia"], eia_pmax_used_key)
            gen_gas_price, gen_missing_eia_codes = \
                linear_combination_gas_prices(gas_prices, eia_plantid_fraction)
            if gen_gas_price is not None:
                old_fuel_cost = gen["fuel_cost"]
                gen["fuel_cost"] = gen_gas_price
                if isinstance(old_fuel_cost, float):
                    gen["fuel_cost"]["reference_value"] = old_fuel_cost
                elif isinstance(old_fuel_cost, dict):
                    gen["fuel_cost"]["reference_value"] = old_fuel_cost["reference_value"]
            else:
                missing_generators.append(gen_uid)
            missing_eia_codes.extend(gen_missing_eia_codes)
        # print warning for generators that we were not able to find
        if len(missing_generators) > 0:
            missing_generators_set = set(missing_generators)
            missing_capacity = sum(
                gen["p_max"] if isinstance(gen["p_max"], float) else gen["p_max"]["reference_value"]
                for gen_uid, gen in self.__static_data["elements"]["generator"].items()
                if gen_uid in missing_generators_set
            )
            logger.warning(
                f"Unable to find monthly prices for {len(missing_generators)} gas generators ({missing_capacity} MW) with uids: {missing_generators}"
            )
        # print warning for missing gas EIA codes in gas_prices
        if len(missing_eia_codes) > 0:
            missing_eia_codes = list(set(missing_eia_codes))
            logger.warning(f"Unable to find these EIA codes in gas price data: {missing_eia_codes}")
        # return to caller
        return None

    def _get_time_series(self, daterange: Union[pd.DatetimeIndex, None] = None):
        """method that interfaces with underlying TimeSeries object
        Args:
            daterange(Union[pd.DatetimeIndex,None], optional): the actual datetime index. Defaults
                to None.
        Returns:
            dict: time series dictionary with all timestamps within the specified daterange.
        """
        # handle the none case (return all data)
        if daterange is None:
            return self.__time_series.asdict()
        # check daterange contains some dates
        if len(daterange) == 0:
            raise ValueError("empty daterange")
        # get daterange parameters to call TimeSeries methods
        unix_tstart = int(round(daterange[0].timestamp()))
        unix_tend = int(round(daterange[-1].timestamp()))
        # generate time series dictionary
        ts_dict = self.__time_series.asdict(unix_tstart, unix_tend)
        # check consistency: lengths should match
        if len(ts_dict["timestamp"]) != len(daterange):
            ts_len = len(ts_dict["timestamp"])
            dr_len = len(daterange)
            raise ValueError(
                f"mismatch in number of steps in time series dictionary ({ts_len}) "
                f"and in provided daterange ({dr_len}). Only hourly resolution is supported."
            )
        # all is good, return time series dictionary
        return ts_dict

    def get_model(self, daterange: Union[pd.DatetimeIndex, None] = None) -> ModelData:
        """Data provider callback for EnergyMarket.
        Args:
            daterange(Union[pd.DatetimeIndex,None], optional): the actual datetime index. Defaults
                to None
        Returns:
            ModelData: Egret model for specified date range
        """
        # create copy of model data and instantiate time series for the provided range
        md_dict = copy.deepcopy(self.__static_data)
        ts_dict = self._get_time_series(daterange)
        # populate md dictionary with time series data
        md_dict = create_egret_md(md_dict, ts_dict)
        # create ModelData from dictionary and return
        return ModelData(md_dict)


"""
Example usage:
```
import pandas as pd
from naermparser import NAERMProvider

# instantiate the data provider
instance_path = './../../../pcm-data-pipeline/datatrack/PCM_Instances/Year_Long/'
ndp = NAERMProvider(instance_path + 'WI_2024.json.gz', instance_path + 'WI_2024_time_series.h5')

# create a date range (in locale)
daterange = pd.date_range(start='2024-01-02', periods=36, freq='h')

# call data provider to create a single day-ahead market md
md = ndp.get_model(daterange)

```

A few notes:
    * Need to add h5py to dependencies of PySO.
    * Tons of warnings still printed for last-pass data fixes, e.g., making gs and bs values instead
      of time series. As we improve the data, these should disapear, thus I would prefer to keep
      those warnings, albeit we can direct them to stderr if they make the logs unreadable.
    * PersistentTimeSeries are converted to values, not to Egret time series. This is because these
      values change seasonally and Egret does not support time series on some of them. If we want to
      change this behavior, we need to make coordinated changes to Egret as well.
    * pd.DatetimeIndex does not seem to have a time zone. We need to specify time on GMT or UTC per
      DOE requirements. Any ideas of how to fit them in there.
"""

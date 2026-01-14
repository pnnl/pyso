import logging
from typing import Union

import numpy as np
from egret.data.model_data import ModelData

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.WARNING)


def add_load_curtail(md: ModelData, load_curtail_cost: Union[int, float] = 1000):
    """
    Adds a generator at each load bus with capacity equal to load and cost equal to
    load_curtail_cost.
    """
    logger = logging.getLogger()
    bus_attrs = md.attributes(element_type="bus")
    load_attrs = md.attributes(element_type="load")

    logger.info("--- LOAD CURTAIL ---")
    logger.info("identifying loads")

    load_slack = {}
    total = 0.0

    for b in bus_attrs["names"]:
        # pick loads at this bus, optionally filtering by 'ncl' flag
        if "ncl" in load_attrs:
            loads = [
                l
                for l, bus in load_attrs["bus"].items()
                if (bus == b) and (load_attrs["ncl"].get(l, True) is False)
            ]
        else:
            loads = [l for l, bus in load_attrs["bus"].items() if bus == b]

        # returns float or dict
        p_load = sum_loads(loads, load_attrs)

        if isinstance(p_load, dict):
            ts_values = p_load["values"]
            scalar_for_total = sum(ts_values) / len(ts_values)
            total += scalar_for_total
        else:
            total += p_load

        if (isinstance(p_load, dict) and any(v > 0 for v in p_load["values"])) or (
            isinstance(p_load, (int, float)) and p_load > 0
        ):
            load_slack[f"{b}_load_curtail"] = {
                "bus": b,
                "p_max": p_load,
                "p_cost": load_curtail_cost,
                "unit_type": "load_curtail",
            }
        elif isinstance(p_load, (int, float)) and p_load < 0:
            raise ValueError(f"Warning: Negative load at bus {b}")

    logger.info(f"\t{len(bus_attrs['names'])} buses processed")
    # Log information about load curtailment setup
    slack_count = len(load_slack)
    logger.info(
        f"\tload_curtail_cost={load_curtail_cost} ({slack_count} slack units, "
        f"total scalar equivalent {total:.2f} MW)"
    )

    add_generators(md, new_gens=load_slack)
    return list(load_slack.keys())


def add_generators(md: ModelData, new_gens: dict, update_duplicates=False):
    """Adds new generators to ModelData by merging new_gens with default generator data."""
    logger = logging.getLogger()
    logger.info("adding generators")
    duplicates = []
    md_gens = md.data["elements"]["generator"]
    default_gen = {
        "bus": None,
        "in_service": True,
        # "mbase": 100,
        # "pg": 0,
        # "qg": 0,
        "p_min": 0,
        "p_max": 0,
        # "q_min": 0,
        # "q_max": 0,
        # "ramp_q": 99,
        "fuel": "other",
        "unit_type": "other",
        "area": None,
        "zone": None,
        "generator_type": "renewable",
        # "fixed_commitment": 1,  #
        # "fixed_regulation": 0,  #
        "initial_status": 1,  #
        "initial_p_output": 0,  #
        "initial_q_output": 0,  #
        "ramp_p": 99999,
        # "ramp_up_60min": 99999,
        # "ramp_down_60min": 99999,
        "p_cost": 2000,
        # "p_cost": {
        #    "data_type": "cost_curve",
        #    "cost_curve_type": "polynomial",
        #    "values": {0: 0, 1: 0}
        # }
        # "q_cost": {
        #    "data_type": "cost_curve",
        #    "cost_curve_type": "polynomial",
        #    "values": {0: 0, 1: 0}
        # }
    }
    # adding bus_attrs so that we can append bus area and zone to generator
    bus_attrs = md.data["elements"]["bus"]
    for gn, gen in new_gens.items():
        if gn in md_gens:
            if update_duplicates:
                if gen["bus"] != md_gens[gn]["bus"]:
                    raise ValueError(
                        f"Generator {gn} bus mismatch: {gen['bus']} != {md_gens[gn]['bus']}"
                    )
                # If gen already exists, we reuse existing values and update new ones
                # (e.g., assume area and zone have already been added). It would be wise to
                # check that the updated gen exists at the same bus as before.
                md_gens[gn].update(gen)
            else:
                duplicates.append(gn)
                continue
        if "bus" not in gen:
            raise ValueError("attempting to add a generator without a bus location")
        for region in ["area", "zone"]:
            if region in bus_attrs[gen["bus"]].keys():
                gen[region] = bus_attrs[gen["bus"]][region]
        md_gens[gn] = {**default_gen, **gen}

    total_added = len(new_gens) - len(duplicates)
    logger.info(f"\t{total_added} added")

    if duplicates:
        logger.info(f"\t{len(duplicates)} duplicates were skipped")


def sum_loads(loads: list, load_attrs: dict):
    # Initialize scalar sum accumulator
    scalar_sum = 0.0
    # Initialize time series sum accumulator
    ts_sum = None

    for l in loads:
        load = load_attrs["p_load"][l]

        # Case 1: scalar load (int or float)
        if isinstance(load, (int, float)):
            scalar_sum += load

        # Case 2: time series load
        elif isinstance(load, dict) and load.get("data_type") == "time_series":
            values = load.get("values", [])
            if ts_sum is None:
                # First time series: copy initial values
                ts_sum = list(values)
            else:
                # Check matching lengths
                if len(values) != len(ts_sum):
                    raise ValueError(f"Time series length mismatch: {len(values)} vs {len(ts_sum)}")
                # Element-wise addition
                ts_sum = [a + b for a, b in zip(ts_sum, values)]

        else:
            # Unknown load type
            raise TypeError(f"Unsupported load type: {load!r}")

    # Finalize result
    if ts_sum is not None:
        # Add scalar sum to each time series element
        return {"data_type": "time_series", "values": [v + scalar_sum for v in ts_sum]}
    else:
        # Only scalar loads
        return scalar_sum


def convert_64(json_dict):
    """Recursively converts np.int64/np.float64 to int/float to save in json format"""

    # Helper function to convert int/float
    def _convert_64(number):
        if isinstance(number, int) or isinstance(number, np.int64):
            return int(number)
        elif isinstance(number, float) or isinstance(number, np.float64):
            return float(number)
        else:
            return number

    # Loop through dictionary, recursing if another dict is found
    for key, value in json_dict.items():
        if isinstance(value, dict):
            value = convert_64(value)
        elif isinstance(value, list):
            value = [_convert_64(v) for v in value]
        # Isinstance is also true for int64/float64
        elif isinstance(value, int) or isinstance(value, float):
            value = _convert_64(value)
        json_dict[key] = value
    return json_dict

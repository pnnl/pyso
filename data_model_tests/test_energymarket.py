import pyenergymarket as pyen
import argparse, sys

def print_daterange(gv:pyen.GVParse):
    print(gv.h5("/area/LOAD"))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="test gvparser")
    parser.add_argument("h5path", help="path to h5 file to test")
    parser.add_argument("--loglevel", help="logging level: INFO, DEBUG etc.", default="INFO")
    parser.add_argument("--fuelmodel", help="use fuel model instead of converting to cost", action="store_true")
    parser.add_argument("--ignore-startup", help="ignore non fuel start up costs", action="store_true")
    parser.add_argument("--scale-fuelcost", type=float, help="scale fuel cost", default=1.0)
    parser.add_argument("--get-daterange", help="print the daterange in the h5", action="store_true")
    # parser.add_argument("--savename", help="name of output json file", default="gv2egret_test.json")
    args = parser.parse_args()
    
    default = {
        "time": {
            "datefrom": "2032-02-01"
        },
        "simulation": {
            "thermal_model": "cost", # this is the default
        },
        "elements": {
            "branch":{
                "rating_long_term": "A",
                "rating_short_term": "A",
                "rating_emergency": "B"
            },
            "generator": {
                "generator_type_map":{
                    "storage": [3, 10]
                },
                "renewable_type_override": {3: "Solar"},
                "ignore_non_fuel_startup": False,
                "scale_fuel_cost": args.scale_fuelcost
            }
        }
    }

    if args.fuelmodel:
        default["simulation"]["thermal_model"] = "fuel"
        savename = "gv2egret_test_fuelmode.json"
    else:
        savename = "gv2egret_test.json"

    if args.ignore_startup:
        default["elements"]["generator"]["ignore_non_fuel_startup"] = True

    gv = pyen.GVParse(args.h5path, default=default, logger_options={"level": args.loglevel})
    if args.get_daterange:
        print_daterange(gv)
        sys.exit(0)
    

    em =pyen.EnergyMarket(gv)
    em.run_model(default["time"]["datefrom"], default["time"]["datefrom"])
    
import pyenergymarket as pyen
import argparse, sys

def print_daterange(gv:pyen.GVParse):
    print(gv.h5("/area/LOAD"))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="test gvparser")
    parser.add_argument("h5path", help="path to h5 file to test")
    parser.add_argument("--get-daterange", help="print the daterange in the h5", action="store_true")
    args = parser.parse_args()
    
    default = {
        "time": {
            "datefrom": "2032-01-01"
        },
        "elements": {
            "branch":{
                "rating_long_term": "WinterC",
                "rating_short_term": "WinterC",
                "rating_emergency": "WinterB"
            }
        },
        "generator": {
            "generator_type_map":{
                "storage": [3, 10]
            }
        }
    }

    gv = pyen.GVParse(args.h5path, default=default)
    if args.get_daterange:
        print_daterange(gv)
        sys.exit(0)
    gv.add_sys_info()
    gv.add_buses()
    gv.add_branches()
    gv.add_load()
    gv.data_convert()
    gv.h5.close()
    gv.mdl.write("gv2egret_test.json")
    
import pyenergymarket as pyen
import argparse


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="test gvparser")
    parser.add_argument("h5path", help="path to h5 file to test")
    args = parser.parse_args()
    
    default = {"elements": {
        "branch":{
            "rating_long_term": "WinterC",
            "rating_short_term": "WinterC",
            "rating_emergency": "WinterB"
        }
    }}

    gv = pyen.GVParse(args.h5path, default=default)
    gv.add_sys_info()
    gv.add_buses()
    gv.add_branches()
    gv.data_convert()
    gv.h5.close()
    gv.mdl.write("gv2egret_test.json")
    